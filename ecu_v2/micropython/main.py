# bike2 ECU v2 — MicroPython top layer.
#
# The C real-time core (imported as `ecu`) owns the entire ignition path:
# crank decode, sync state machine, hardware-alarm scheduling, coil GPIO.
# This file owns ONLY:
#   - boot / load profile / push to C
#   - UART telemetry framing (50 Hz)
#   - UART config TLV ingest + sanitize + push
#   - dash response framing
#
# Wire protocol matches v1 byte-for-byte. The dash firmware does not
# need any changes for this migration.
#
# What is INTENTIONALLY absent compared to v1:
#   - No Pin.irq() handler — PIO + C core handle every crank edge
#   - No machine.Timer — C core's repeating SDK timer runs the soft tick
#   - No hard/soft IRQ Python paths at all
#   - No `disable_irq() ... enable_irq()` — IPC seqlock handles concurrency

from machine import Pin, UART
import machine, micropython, utime, ujson

import config_layer
import ecu  # the C native module — see ecu_v2/micropython/ecu_native.c

micropython.alloc_emergency_exception_buf(256)

# -----------------------------------------------------------------------
# Pin / protocol constants — preserved from v1 for wire-compat
# -----------------------------------------------------------------------
UART_ID, UART_TX_PIN, UART_RX_PIN, UART_BAUD = 0, 0, 1, 230400

FRAME_START_0 = 0xAA
FRAME_START_1 = 0x55
PROTO_MAJOR, PROTO_MINOR = 1, 0
MSG_TYPE_ENGINE_STATE    = 1
MSG_TYPE_CONFIG_SET      = 2
MSG_TYPE_CONFIG_RESPONSE = 3

TLV_RPM_U16                  = 1
TLV_SYNC_STATE_U8            = 2
TLV_IGNITION_MODE_U8         = 3
TLV_FAULT_BITS_U32           = 4
TLV_VALIDITY_BITS_U16        = 5
TLV_ECU_CYCLE_ID_U32         = 8
TLV_SPARK_COUNTER_U32        = 9
TLV_IGNITION_OUTPUT_STATE_U8 = 10
TLV_FAULT_LOG                = 11

TLV_CFG_MODE_U8         = 1
TLV_CFG_JSON            = 2
TLV_CFG_STATUS_U8       = 3
TLV_CFG_FLAGS_U16       = 4
TLV_CFG_PROFILE_CRC_U16 = 5
TLV_CFG_TEXT            = 6

CFG_MODE_PREVIEW, CFG_MODE_APPLY, CFG_MODE_COMMIT = 0, 1, 2
CFG_STATUS_OK, CFG_STATUS_REJECTED, CFG_STATUS_DEFERRED = 0, 1, 2

CFG_FLAG_SANITIZED        = 1 << 0
CFG_FLAG_RUNTIME_APPLIED  = 1 << 1
CFG_FLAG_PERSISTED        = 1 << 2
CFG_FLAG_REBOOT_REQUIRED  = 1 << 3
CFG_FLAG_GEOMETRY_CHANGED = 1 << 4
CFG_FLAG_PARSE_ERROR      = 1 << 5

TELEMETRY_PERIOD_MS = 20  # 50 Hz

# -----------------------------------------------------------------------
# Frame helpers (wire-identical to v1)
# -----------------------------------------------------------------------
def _u16le(buf, v): buf.append(v & 0xFF); buf.append((v >> 8) & 0xFF)
def _u32le(buf, v):
    buf.append(v & 0xFF); buf.append((v >> 8) & 0xFF)
    buf.append((v >> 16) & 0xFF); buf.append((v >> 24) & 0xFF)
def _i16le(buf, v):
    if v < 0: v = 0x10000 + v
    _u16le(buf, v)

def _tlv_u8(buf, t, v):  buf.append(t); buf.append(1); buf.append(v & 0xFF)
def _tlv_u16(buf, t, v): buf.append(t); buf.append(2); _u16le(buf, v)
def _tlv_u32(buf, t, v): buf.append(t); buf.append(4); _u32le(buf, v)
def _tlv_bytes(buf, t, b):
    n = len(b)
    if n > 255: n = 255
    buf.append(t); buf.append(n); buf.extend(memoryview(b)[:n])

def _crc16_ccitt(data):
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc

def _build_frame(msg_type, seq, payload):
    header = bytearray()
    header.append(PROTO_MAJOR); header.append(PROTO_MINOR); header.append(msg_type)
    _u16le(header, seq & 0xFFFF)
    _u32le(header, utime.ticks_ms() & 0xFFFFFFFF)
    _u16le(header, len(payload))
    crc = _crc16_ccitt(header + payload)
    frame = bytearray()
    frame.append(FRAME_START_0); frame.append(FRAME_START_1)
    frame.extend(header); frame.extend(payload); _u16le(frame, crc)
    return frame

# -----------------------------------------------------------------------
# Telemetry — pulls from C core via ecu.read_state() / ecu.drain_faults()
# -----------------------------------------------------------------------
_drained_faults = []   # accumulator across telemetry ticks; transmitted then cleared

def _build_engine_payload():
    st = ecu.read_state()
    new_faults = ecu.drain_faults()
    if new_faults:
        # Cap at 8 to match v1's FAULT_LOG_SIZE wire expectation. If more
        # than 8 accumulate between ticks, prefer the most recent.
        for f in new_faults:
            if len(_drained_faults) >= 8:
                _drained_faults.pop(0)
            _drained_faults.append(f)

    p = bytearray()
    _tlv_u16(p, TLV_RPM_U16,                  st["rpm"] & 0xFFFF)
    _tlv_u8 (p, TLV_SYNC_STATE_U8,            st["sync_state"])
    _tlv_u8 (p, TLV_IGNITION_MODE_U8,         st["ignition_mode"])
    _tlv_u32(p, TLV_FAULT_BITS_U32,           st["fault_bits"] & 0xFFFFFFFF)
    _tlv_u16(p, TLV_VALIDITY_BITS_U16,        st["validity_bits"] & 0xFFFF)
    _tlv_u32(p, TLV_ECU_CYCLE_ID_U32,         st["cycle_id"] & 0xFFFFFFFF)
    _tlv_u32(p, TLV_SPARK_COUNTER_U32,        st["spark_counter"] & 0xFFFFFFFF)
    _tlv_u8 (p, TLV_IGNITION_OUTPUT_STATE_U8, st["ignition_output"])

    if _drained_faults:
        body = bytearray()
        for f in _drained_faults:
            _u32le(body, f["fault_bit"]       & 0xFFFFFFFF)
            _u16le(body, f["rpm"]             & 0xFFFF)
            _u32le(body, f["tooth_period_us"] & 0xFFFFFFFF)
            _u32le(body, f["avg_period_us"]   & 0xFFFFFFFF)
            _u32le(body, f["timestamp_ms"]    & 0xFFFFFFFF)
            _u16le(body, f["count"]           & 0xFFFF)
        _tlv_bytes(p, TLV_FAULT_LOG, body)
    return p

# -----------------------------------------------------------------------
# Config TLV ingest — wire-identical to v1
# -----------------------------------------------------------------------
_active_profile = None  # last sanitized profile
_pending_seq = 0

def _expand_aliases(cfg):
    if not isinstance(cfg, dict): return None
    aliases = {
        "tpr": "teeth_per_rev", "sti": "sync_tooth_index",
        "tmin": "tooth_min_us", "tmax": "tooth_max_us",
        "sfd": "safe_fire_delay_us", "sdw": "safe_dwell_us",
        "mtr": "missing_tooth_ratio",
        "amr": "advance_map_rpm", "amc": "advance_map_cd",
    }
    out = {}
    for k in cfg:
        out[aliases[k] if k in aliases else k] = cfg[k]
    if "advance_map_cd" in out and "advance_map_rpm" not in out:
        cd = out["advance_map_cd"]
        if isinstance(cd, list) and len(cd) == 21:
            out["advance_map_rpm"] = [i * 500 for i in range(21)]
    return out

def _parse_cfg_payload(payload):
    mode = CFG_MODE_PREVIEW; cfg = None
    i = 0; n = len(payload)
    while i + 2 <= n:
        t = payload[i]; l = payload[i+1]; i += 2
        if i + l > n: return None, None
        v = payload[i:i+l]; i += l
        if t == TLV_CFG_MODE_U8 and l >= 1: mode = v[0]
        elif t == TLV_CFG_JSON:
            try: cfg = ujson.loads(bytes(v).decode("utf-8"))
            except Exception: return None, None
    return mode, cfg

def _send_config_response(uart, seq, status, flags, text):
    payload = bytearray()
    _tlv_u8 (payload, TLV_CFG_STATUS_U8,       status)
    _tlv_u16(payload, TLV_CFG_FLAGS_U16,       flags & 0xFFFF)
    _tlv_u16(payload, TLV_CFG_PROFILE_CRC_U16, ecu.get_profile_crc16() & 0xFFFF)
    if text:
        _tlv_bytes(payload, TLV_CFG_TEXT, text.encode("utf-8"))
    uart.write(_build_frame(MSG_TYPE_CONFIG_RESPONSE, seq, payload))

def _geometry_changed(old, new):
    if old is None: return False
    keys = ("teeth_per_rev","sync_tooth_index","tooth_min_us","tooth_max_us",
            "debounce_us","sync_edges_to_lock")
    for k in keys:
        if int(old.get(k, 0)) != int(new.get(k, 0)): return True
    return False

def _handle_config_message(uart, seq, payload):
    global _active_profile
    mode, cfg = _parse_cfg_payload(payload)
    if cfg is None:
        _send_config_response(uart, seq, CFG_STATUS_REJECTED,
                              CFG_FLAG_PARSE_ERROR, "invalid cfg payload"); return
    cfg = _expand_aliases(cfg)
    if cfg is None:
        _send_config_response(uart, seq, CFG_STATUS_REJECTED,
                              CFG_FLAG_PARSE_ERROR, "invalid cfg object"); return

    merged = {}
    if _active_profile is not None: merged.update(_active_profile)
    merged.update(cfg)
    sanitized = config_layer.sanitize_profile(merged)
    flags = CFG_FLAG_GEOMETRY_CHANGED if _geometry_changed(_active_profile, sanitized) else 0
    if sanitized != merged: flags |= CFG_FLAG_SANITIZED

    if mode == CFG_MODE_PREVIEW:
        _send_config_response(uart, seq, CFG_STATUS_OK, flags, "preview ok"); return

    # Geometry changes are reboot-required (CLAUDE.md rule). We persist
    # but do not push to C until next boot.
    if flags & CFG_FLAG_GEOMETRY_CHANGED:
        if mode == CFG_MODE_COMMIT:
            if config_layer.save_profile_pair(sanitized):
                flags |= CFG_FLAG_PERSISTED
        flags |= CFG_FLAG_REBOOT_REQUIRED
        _send_config_response(uart, seq, CFG_STATUS_OK, flags,
                              "geometry stored; reboot required")
        return

    # Non-geometry changes apply at runtime via the IPC shadow swap.
    ecu.set_profile(sanitized)
    ecu.set_profile_crc16(config_layer.crc16_ccitt(
        ujson.dumps(sanitized).encode("utf-8")) & 0xFFFF)
    _active_profile = sanitized
    flags |= CFG_FLAG_RUNTIME_APPLIED
    if mode == CFG_MODE_COMMIT:
        if config_layer.save_profile_pair(sanitized):
            flags |= CFG_FLAG_PERSISTED
    _send_config_response(uart, seq, CFG_STATUS_OK, flags, "applied")

# -----------------------------------------------------------------------
# Frame ingest
# -----------------------------------------------------------------------
class FrameIngest:
    def __init__(self, uart):
        self.uart = uart
        self.buf = bytearray()
    def poll(self, on_msg):
        try: waiting = self.uart.any()
        except Exception: return
        if waiting <= 0: return
        try: data = self.uart.read(waiting)
        except Exception: data = None
        if not data: return
        self.buf.extend(data)
        while self._consume(on_msg): pass
    def _consume(self, on_msg):
        if len(self.buf) >= 2:
            seek, max_seek = 0, len(self.buf) - 1
            while seek < max_seek and (self.buf[seek] != FRAME_START_0
                                        or self.buf[seek+1] != FRAME_START_1):
                seek += 1
            if seek > 0: self.buf = self.buf[seek:]
        if len(self.buf) < 12: return False
        plen = self.buf[10] | (self.buf[11] << 8)
        total = 2 + 10 + plen + 2
        if len(self.buf) < total: return False
        body = self.buf[2:2+10+plen]
        crc_rx = self.buf[2+10+plen] | (self.buf[2+10+plen+1] << 8)
        if _crc16_ccitt(body) == crc_rx:
            mt = body[2]; seq = body[3] | (body[4] << 8)
            payload = body[10:10+plen]
            on_msg(mt, seq, payload)
        self.buf = self.buf[total:]
        return True

# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
def main():
    global _active_profile

    profile, recovered = config_layer.load_profile_with_recovery()
    if profile is None: profile = config_layer.default_profile()
    _active_profile = config_layer.sanitize_profile(profile)
    if recovered: print("Config recovered from backup")

    if not ecu.start():
        print("ECU C core already started"); return

    # Push profile + CRC into the C core's first shadow.
    ecu.set_profile(_active_profile)
    ecu.set_profile_crc16(config_layer.crc16_ccitt(
        ujson.dumps(_active_profile).encode("utf-8")) & 0xFFFF)

    uart = UART(UART_ID, baudrate=UART_BAUD,
                tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN),
                txbuf=512, rxbuf=512)
    ingest = FrameIngest(uart)

    def on_msg(msg_type, seq, payload):
        if msg_type == MSG_TYPE_CONFIG_SET:
            _handle_config_message(uart, seq, payload)

    seq = 0
    next_telemetry_ms = utime.ticks_add(utime.ticks_ms(), TELEMETRY_PERIOD_MS)

    while True:
        ingest.poll(on_msg)

        now = utime.ticks_ms()
        if utime.ticks_diff(now, next_telemetry_ms) >= 0:
            next_telemetry_ms = utime.ticks_add(next_telemetry_ms,
                                                 TELEMETRY_PERIOD_MS)
            payload = _build_engine_payload()
            uart.write(_build_frame(MSG_TYPE_ENGINE_STATE, seq, payload))
            seq = (seq + 1) & 0xFFFF
            _drained_faults.clear()

        utime.sleep_ms(2)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        ecu.stop()
        print("ECU stopped")
