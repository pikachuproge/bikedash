from machine import Pin, Timer, UART, disable_irq, enable_irq
from micropython import const
import micropython
import utime
import ujson
import config_layer

micropython.alloc_emergency_exception_buf(256)

# GPIO + UART mapping (ECU Pico)
# - Crank digital pulse input (from external VR conditioner): GP2
# - Coil drive output: GP15
# - Safety inhibit input: GP14 (active-low)
# - UART0 TX to Dash RX: GP0 -> Dash GP5
# - UART0 RX from Dash TX: GP1 <- Dash GP4
# - Onboard debug LED: GP25

# -----------------------------
# Pin / protocol configuration
# -----------------------------
CRANK_PIN = const(2)
COIL_PIN = const(15)
SAFETY_INHIBIT_PIN = const(14)
LED_PIN = const(25)

UART_ID = const(0)
UART_TX_PIN = const(0)
UART_RX_PIN = const(1)
UART_BAUD = const(230400)

FRAME_START_0 = const(0xAA)
FRAME_START_1 = const(0x55)
PROTO_MAJOR = const(1)
PROTO_MINOR = const(0)
MSG_TYPE_ENGINE_STATE = const(1)
MSG_TYPE_CONFIG_SET = const(2)
MSG_TYPE_CONFIG_RESPONSE = const(3)

TLV_RPM_U16 = const(1)
TLV_SYNC_STATE_U8 = const(2)
TLV_IGNITION_MODE_U8 = const(3)
TLV_FAULT_BITS_U32 = const(4)
TLV_VALIDITY_BITS_U16 = const(5)
TLV_SPEED_KPH_X10_I16 = const(6)      # optional (not produced by ECU control core)
TLV_TEMP_C_X10_I16 = const(7)         # optional (not produced by ECU control core)
TLV_ECU_CYCLE_ID_U32 = const(8)
TLV_SPARK_COUNTER_U32 = const(9)
TLV_IGNITION_OUTPUT_STATE_U8 = const(10)
TLV_FAULT_LOG = const(11)

TLV_CFG_MODE_U8 = const(1)
TLV_CFG_JSON = const(2)
TLV_CFG_STATUS_U8 = const(3)
TLV_CFG_FLAGS_U16 = const(4)
TLV_CFG_PROFILE_CRC_U16 = const(5)
TLV_CFG_TEXT = const(6)

CFG_MODE_PREVIEW = const(0)
CFG_MODE_APPLY = const(1)
CFG_MODE_COMMIT = const(2)

CFG_STATUS_OK = const(0)
CFG_STATUS_REJECTED = const(1)
CFG_STATUS_DEFERRED = const(2)

CFG_FLAG_NONE = const(0)
CFG_FLAG_SANITIZED = const(1 << 0)
CFG_FLAG_RUNTIME_APPLIED = const(1 << 1)
CFG_FLAG_PERSISTED = const(1 << 2)
CFG_FLAG_REBOOT_REQUIRED = const(1 << 3)
CFG_FLAG_GEOMETRY_CHANGED = const(1 << 4)
CFG_FLAG_PARSE_ERROR = const(1 << 5)

# -----------------------------
# Real-time state / mode enums
# -----------------------------
SYNC_LOST = const(0)
SYNC_SYNCING = const(1)
SYNC_SYNCED = const(2)

IGN_MODE_INHIBIT = const(0)
IGN_MODE_SAFE = const(1)
IGN_MODE_PRECISION = const(2)

# -----------------------------
# Fault flags
# -----------------------------
FAULT_SYNC_TIMEOUT = const(1 << 0)
FAULT_EDGE_PLAUSIBILITY = const(1 << 1)
FAULT_UNSCHEDULABLE = const(1 << 2)
FAULT_STALE_EVENT = const(1 << 3)
FAULT_ISR_OVERRUN = const(1 << 4)
FAULT_SAFETY_INHIBIT = const(1 << 5)
FAULT_UNSTABLE_SYNC = const(1 << 6)

# -----------------------------
# Validity flags
# -----------------------------
VALID_RPM = const(1 << 0)
VALID_SYNC = const(1 << 1)
VALID_IGN_MODE = const(1 << 2)
VALID_FAULTS = const(1 << 3)
VALID_IGN_OUT = const(1 << 4)
VALID_SPEED = const(1 << 5)
VALID_TEMP = const(1 << 6)

# -----------------------------
# Timing/scheduling constants
# -----------------------------
CRANK_DEBOUNCE_US = const(40)
SYNC_TIMEOUT_US = const(250000)  # no tooth edge timeout => UNSYNCED/INHIBIT

# Defaults sized for Strategy B (multi-tooth ring-gear Hall on the dry-clutch
# REDUCTION ring gear with one tooth filed off). The ring gear rotates slower
# than the crank by the reduction ratio, so the effective teeth-per-crank-rev
# is ring_gear_physical_teeth / reduction_ratio. Worked example: 84 physical
# teeth with 4:1 reduction => teeth_per_rev = 21. Confirm the actual ratio on
# engine arrival and update this constant + the active profile to match.
# At 9500 RPM with teeth_per_rev = 21, normal tooth period = 60e6/(9500*21)
# = ~301 us, so tooth_min_us must be < 301 us. At slow pedal cranking the
# missing-tooth gap is detected directly by the missing_tooth_ratio path
# below, so tooth_max_us only needs to bound NORMAL teeth.
GEAR_DEFAULT_TEETH = const(21)
GEAR_DEFAULT_SYNC_TOOTH = const(0)
GEAR_DEFAULT_MIN_US = const(300)
GEAR_DEFAULT_MAX_US = const(8000)
GEAR_DEFAULT_DEBOUNCE_US = const(40)
GEAR_DEFAULT_LOCK_EDGES = const(8)
GEAR_DEFAULT_MTR_X10 = const(18)
GEAR_NOISE_STREAK_LIMIT = const(6)
GEAR_RANGE_STREAK_LIMIT = const(4)

DWELL_TARGET_US = const(1800)
DWELL_MIN_US = const(1200)
DWELL_MAX_US = const(2600)

SAFE_DWELL_US = const(1700)
SAFE_FIRE_DELAY_US = const(2500)
SAFE_PERIOD_MIN_US = const(2000)
SAFE_PERIOD_MAX_US = const(150000)

LEAD_GUARD_ON_US = const(200)
LEAD_GUARD_FIRE_US = const(200)
MIN_COIL_ON_US = const(400)
LATE_SLACK_US = const(200)

SCHEDULER_TICK_HZ = const(5000)
WATCHDOG_HZ = const(200)
TELEMETRY_HZ = const(50)
ALLOW_TIMER_FALLBACK = const(0)
APPLY_MAX_RPM = const(300)
COMMIT_MAX_RPM = const(100)

# Sync/precision anti-flap
PRECISION_REENTRY_LOCKOUT_MS = const(1500)

# ISR overrun threshold. With 80-100 teeth/rev at redline, tooth-to-tooth
# spacing falls to ~60-80 us. Reference-edge ISRs additionally call
# _interp_map twice and schedule_cycle_events. 100 us leaves headroom for
# both the hot per-tooth path and the heavier per-rev reference path.
ISR_OVERRUN_LIMIT_US = const(100)

# Degradation/inhibit behavior
MAX_UNSCHED_STREAK_PRECISION = const(4)
MAX_UNSCHED_STREAK_SAFE = const(6)
MAX_SAFE_BOUNDS_FAIL = const(6)
COUNTER_MASK = const(0x3FFFFFFF)

# Fault log ring buffer
FAULT_LOG_SIZE = const(8)

# -----------------------------
# Runtime globals
# -----------------------------
crank_pin = None
coil_pin = None
safety_inhibit_pin = None
led_pin = None
uart = None
crank_gear = None
config_ingest = None

sync_state = SYNC_LOST
ignition_mode = IGN_MODE_INHIBIT
fault_bits = 0
validity_bits = VALID_SYNC | VALID_IGN_MODE | VALID_FAULTS | VALID_IGN_OUT

# Structured fault log: parallel flat arrays so set_fault() never allocates
# while running in hard-IRQ context. fault_log_used tracks how many slots
# are populated (0..FAULT_LOG_SIZE). Repeat occurrences of the same
# fault_bit increment count and refresh timestamp/context in place.
fault_log_bits = [0] * FAULT_LOG_SIZE
fault_log_rpm = [0] * FAULT_LOG_SIZE
fault_log_tooth = [0] * FAULT_LOG_SIZE
fault_log_avg = [0] * FAULT_LOG_SIZE
fault_log_ts = [0] * FAULT_LOG_SIZE
fault_log_count_arr = [0] * FAULT_LOG_SIZE
fault_log_used = 0

cycle_id = 0
spark_counter = 0
telemetry_seq = 0
telemetry_due = False
telemetry_tx_pending = None
telemetry_tx_offset = 0
config_tx_pending = None
config_tx_offset = 0

rpm_value = 0
crank_angle_deg = 0

sync_soft_fails = 0
unsched_streak = 0
safe_bounds_fail_count = 0
precision_lockout_until_ms = 0
led_flash_until_ms = 0
led_flash_period_ms = 0
led_last_toggle_ms = 0
led_output_state = 0

coil_active = 0

active_profile = None
advance_map_rpm_cache = ()
advance_map_cd_cache = ()
dwell_map_rpm_cache = ()
dwell_map_us_cache = ()
pending_profile = None
pending_commit = False
pending_cfg_flags = CFG_FLAG_NONE
pending_cfg_status = CFG_STATUS_OK
pending_cfg_text = ""
pending_cfg_seq = 0

# Scheduler event slots
fire_armed = False
fire_time_us = 0
fire_cycle_id = 0

on_armed = False
on_time_us = 0
on_cycle_id = 0

# CRANK_GEAR_LAYER status codes
GEAR_EDGE_NONE = const(0)
GEAR_EDGE_REFERENCE = const(1)
GEAR_EDGE_FAIL = const(2)

GEAR_ERR_NONE = const(0)
GEAR_ERR_NOISE = const(1)
GEAR_ERR_RANGE = const(2)
GEAR_ERR_TIMEOUT = const(3)


@micropython.viper
def _crc16_ccitt_over(crc: int, data: ptr8, length: int) -> int:
    for i in range(length):
        b = int(data[i])
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def crc16_ccitt(data):
    return _crc16_ccitt_over(0xFFFF, data, len(data))


def put_u16_le(buf, value):
    buf.append(value & 0xFF)
    buf.append((value >> 8) & 0xFF)


def put_u32_le(buf, value):
    buf.append(value & 0xFF)
    buf.append((value >> 8) & 0xFF)
    buf.append((value >> 16) & 0xFF)
    buf.append((value >> 24) & 0xFF)


def put_i16_le(buf, value):
    if value < 0:
        value = 0x10000 + value
    put_u16_le(buf, value)


def tlv_u8(buf, field_type, value):
    buf.append(field_type)
    buf.append(1)
    buf.append(value & 0xFF)


def tlv_u16(buf, field_type, value):
    buf.append(field_type)
    buf.append(2)
    put_u16_le(buf, value)


def tlv_u32(buf, field_type, value):
    buf.append(field_type)
    buf.append(4)
    put_u32_le(buf, value)


def tlv_i16(buf, field_type, value):
    buf.append(field_type)
    buf.append(2)
    put_i16_le(buf, value)


def tlv_bytes(buf, field_type, value_bytes):
    ln = len(value_bytes)
    if ln > 255:
        ln = 255
    buf.append(field_type)
    buf.append(ln)
    buf.extend(memoryview(value_bytes)[:ln])


def force_coil_off():
    global coil_active
    if coil_pin is not None:
        coil_pin.off()
    coil_active = 0


def led_set(value):
    global led_output_state
    if led_pin is None:
        return
    try:
        if value:
            led_pin.on()
            led_output_state = 1
        else:
            led_pin.off()
            led_output_state = 0
    except Exception:
        led_output_state = 0


def led_flash(ms, period_ms=0):
    global led_flash_until_ms, led_flash_period_ms, led_last_toggle_ms
    now = utime.ticks_ms()
    led_flash_until_ms = utime.ticks_add(now, ms)
    led_flash_period_ms = period_ms
    led_last_toggle_ms = now


def led_tick():
    global led_flash_until_ms, led_flash_period_ms, led_last_toggle_ms, led_output_state
    now = utime.ticks_ms()
    if led_flash_until_ms and utime.ticks_diff(now, led_flash_until_ms) < 0:
        if led_flash_period_ms <= 0:
            led_set(1)
            return
        if utime.ticks_diff(now, led_last_toggle_ms) >= led_flash_period_ms:
            led_last_toggle_ms = now
            led_set(0 if led_output_state else 1)
        return

    if led_flash_until_ms:
        led_flash_until_ms = 0
        led_flash_period_ms = 0

    if fault_bits != 0:
        if sync_state == SYNC_LOST:
            if utime.ticks_diff(now, led_last_toggle_ms) >= 600:
                led_last_toggle_ms = now
                led_set(0 if led_output_state else 1)
        elif sync_state == SYNC_SYNCING:
            if utime.ticks_diff(now, led_last_toggle_ms) >= 220:
                led_last_toggle_ms = now
                led_set(0 if led_output_state else 1)
        else:
            led_set(1)
    else:
        if sync_state == SYNC_SYNCED:
            led_set(1)
        elif sync_state == SYNC_SYNCING:
            if utime.ticks_diff(now, led_last_toggle_ms) >= 220:
                led_last_toggle_ms = now
                led_set(0 if led_output_state else 1)
        else:
            if utime.ticks_diff(now, led_last_toggle_ms) >= 600:
                led_last_toggle_ms = now
                led_set(0 if led_output_state else 1)


def set_fault(bit):
    global fault_bits, fault_log_used
    fault_bits |= bit

    # Capture context atomically. disable_irq is harmless when already in a
    # hard-IRQ path (returns 0, restored by hardware on ISR exit) and
    # protects the flat arrays against concurrent ISR/timer callers.
    irq = disable_irq()
    rpm_now = rpm_value
    cur_dt = 0
    cur_avg = 0
    if crank_gear is not None:
        cur_dt = crank_gear.last_dt_us
        cur_avg = crank_gear.tooth_period_us
    now_ms = utime.ticks_ms()

    found = -1
    i = 0
    while i < fault_log_used:
        if fault_log_bits[i] == bit:
            found = i
            break
        i += 1

    if found >= 0:
        c = fault_log_count_arr[found] + 1
        if c > 65535:
            c = 65535
        fault_log_count_arr[found] = c
        fault_log_ts[found] = now_ms
        fault_log_rpm[found] = rpm_now
        fault_log_tooth[found] = cur_dt
        fault_log_avg[found] = cur_avg
    elif fault_log_used < FAULT_LOG_SIZE:
        slot = fault_log_used
        fault_log_bits[slot] = bit
        fault_log_rpm[slot] = rpm_now
        fault_log_tooth[slot] = cur_dt
        fault_log_avg[slot] = cur_avg
        fault_log_ts[slot] = now_ms
        fault_log_count_arr[slot] = 1
        fault_log_used = slot + 1
    enable_irq(irq)


def clear_fault(bit):
    global fault_bits
    fault_bits &= (~bit)


def mul_div_smallint(value, mul, div):
    # Avoid large intermediate products in hard IRQ context.
    # Negate before integer division so negative advance_cd rounds symmetrically
    # (truncate toward zero) instead of Python's floor (toward -infinity).
    if mul < 0:
        q = value // div
        r = value - (q * div)
        return -((q * (-mul)) + ((r * (-mul)) // div))
    q = value // div
    r = value - (q * div)
    return (q * mul) + ((r * mul) // div)


def event_due(now_us, target_us):
    return utime.ticks_diff(now_us, target_us) >= 0


def event_late_by(now_us, target_us):
    late = utime.ticks_diff(now_us, target_us)
    if late <= 0:
        return 0
    return late


def cancel_events():
    global fire_armed, on_armed
    fire_armed = False
    on_armed = False


def clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


class CRANK_GEAR_LAYER:
    def __init__(self, profile):
        self.apply_profile(profile)
        self.reset()

    def apply_profile(self, profile):
        self.teeth_per_rev = int(profile.get("teeth_per_rev", GEAR_DEFAULT_TEETH))
        self.sync_tooth_index = int(profile.get("sync_tooth_index", GEAR_DEFAULT_SYNC_TOOTH))
        self.tooth_min_us = int(profile.get("tooth_min_us", GEAR_DEFAULT_MIN_US))
        self.tooth_max_us = int(profile.get("tooth_max_us", GEAR_DEFAULT_MAX_US))
        self.debounce_us = int(profile.get("debounce_us", GEAR_DEFAULT_DEBOUNCE_US))
        self.sync_edges_to_lock = int(profile.get("sync_edges_to_lock", GEAR_DEFAULT_LOCK_EDGES))
        if self.sync_edges_to_lock < 1:
            self.sync_edges_to_lock = 1
        # Stored as ratio*10 so missing-tooth detection in on_edge stays in
        # integer arithmetic for the hard-IRQ path.
        try:
            ratio = float(profile.get("missing_tooth_ratio", 1.8))
        except (TypeError, ValueError):
            ratio = 1.8
        ratio_x10 = int(ratio * 10 + 0.5)
        if ratio_x10 < 12:
            ratio_x10 = 12
        elif ratio_x10 > 30:
            ratio_x10 = 30
        self.missing_tooth_ratio_x10 = ratio_x10

    def reset(self):
        self.last_edge_us = 0
        self.last_dt_us = 0
        self.tooth_period_us = 0
        self.rev_period_us = 0
        self.tooth_index = 0
        self.sync_edge_count = 0
        self.noise_streak = 0
        self.range_streak = 0
        self.rpm = 0
        self.crank_angle_deg = 0
        self.sync_state = SYNC_LOST
        self.last_error = GEAR_ERR_NONE

    def force_unsynced(self, error_code):
        self.reset()
        self.last_error = error_code

    def _update_period(self, dt_us):
        if self.tooth_period_us == 0:
            self.tooth_period_us = dt_us
        else:
            self.tooth_period_us = (self.tooth_period_us * 3 + dt_us) // 4
        self.rev_period_us = self.tooth_period_us * self.teeth_per_rev
        if self.rev_period_us > 0:
            self.rpm = 60000000 // self.rev_period_us
        else:
            self.rpm = 0

    def _update_angle(self):
        self.crank_angle_deg = (self.tooth_index * 360) // self.teeth_per_rev

    def on_edge(self, now_us):
        if self.last_edge_us == 0:
            self.last_edge_us = now_us
            self.last_error = GEAR_ERR_NONE
            return GEAR_EDGE_NONE

        dt_us = utime.ticks_diff(now_us, self.last_edge_us)
        if dt_us < self.debounce_us:
            self.noise_streak += 1
            if self.noise_streak >= GEAR_NOISE_STREAK_LIMIT:
                self.force_unsynced(GEAR_ERR_NOISE)
                return GEAR_EDGE_FAIL
            return GEAR_EDGE_NONE

        self.last_edge_us = now_us
        self.last_dt_us = dt_us

        # Missing-tooth detection MUST run before the range check, otherwise
        # the gap interval (which is naturally > tooth_max_us) accumulates
        # range_streak and triggers GEAR_ERR_RANGE instead of providing the
        # sync reference.
        if self.tooth_period_us > 0 and (dt_us * 10) > (self.tooth_period_us * self.missing_tooth_ratio_x10):
            self.noise_streak = 0
            self.range_streak = 0
            self._update_period(dt_us)
            if self.sync_state == SYNC_LOST:
                self.sync_state = SYNC_SYNCING
            self.tooth_index = self.sync_tooth_index
            self._update_angle()
            if self.sync_state == SYNC_SYNCING:
                self.sync_edge_count += 1
                if self.sync_edge_count >= self.sync_edges_to_lock:
                    self.sync_state = SYNC_SYNCED
            self.last_error = GEAR_ERR_NONE
            return GEAR_EDGE_REFERENCE

        if dt_us < self.tooth_min_us or dt_us > self.tooth_max_us:
            self.range_streak += 1
            if self.range_streak >= GEAR_RANGE_STREAK_LIMIT:
                self.force_unsynced(GEAR_ERR_RANGE)
                return GEAR_EDGE_FAIL
            return GEAR_EDGE_NONE

        self.noise_streak = 0
        self.range_streak = 0
        self._update_period(dt_us)

        if self.sync_state == SYNC_LOST:
            self.sync_state = SYNC_SYNCING

        self.tooth_index += 1
        if self.tooth_index >= self.teeth_per_rev:
            self.tooth_index = 0
        self._update_angle()

        if self.sync_state == SYNC_SYNCING:
            self.sync_edge_count += 1
            if self.sync_edge_count >= self.sync_edges_to_lock:
                self.sync_state = SYNC_SYNCED

        self.last_error = GEAR_ERR_NONE
        if self.tooth_index == self.sync_tooth_index:
            return GEAR_EDGE_REFERENCE
        return GEAR_EDGE_NONE

    def on_timeout(self, now_us):
        if self.last_edge_us == 0:
            return False
        if utime.ticks_diff(now_us, self.last_edge_us) > SYNC_TIMEOUT_US:
            self.force_unsynced(GEAR_ERR_TIMEOUT)
            return True
        return False


def _interp_map(rpm, x_points, y_points):
    n = len(x_points)
    if n <= 0 or n != len(y_points):
        return 0
    if rpm <= x_points[0]:
        return y_points[0]
    i = 1
    while i < n:
        if rpm <= x_points[i]:
            x0 = x_points[i - 1]
            x1 = x_points[i]
            y0 = y_points[i - 1]
            y1 = y_points[i]
            if x1 <= x0:
                return y1
            return y0 + ((rpm - x0) * (y1 - y0)) // (x1 - x0)
        i += 1
    return y_points[n - 1]


def compute_advance_cd(rpm):
    if not advance_map_rpm_cache or not advance_map_cd_cache:
        return 1200
    return _interp_map(rpm, advance_map_rpm_cache, advance_map_cd_cache)


def compute_dwell_us(rpm):
    if not dwell_map_rpm_cache or not dwell_map_us_cache:
        return clamp(DWELL_TARGET_US, DWELL_MIN_US, DWELL_MAX_US)
    dwell = _interp_map(rpm, dwell_map_rpm_cache, dwell_map_us_cache)
    return clamp(dwell, DWELL_MIN_US, DWELL_MAX_US)


def _cfg_flags(current_profile, new_profile):
    flags = CFG_FLAG_NONE
    if current_profile is None:
        return flags
    keys = ("teeth_per_rev", "sync_tooth_index", "tooth_min_us", "tooth_max_us", "debounce_us", "sync_edges_to_lock")
    for k in keys:
        if int(current_profile.get(k, 0)) != int(new_profile.get(k, 0)):
            return CFG_FLAG_GEOMETRY_CHANGED
    return flags


def _build_config_response(seq, status, flags, text):
    payload = bytearray()
    tlv_u8(payload, TLV_CFG_STATUS_U8, status)
    tlv_u16(payload, TLV_CFG_FLAGS_U16, flags & 0xFFFF)
    if active_profile is not None:
        tlv_u16(payload, TLV_CFG_PROFILE_CRC_U16, config_layer.profile_crc16(active_profile) & 0xFFFF)
    if text:
        tlv_bytes(payload, TLV_CFG_TEXT, text.encode("utf-8"))

    header = bytearray()
    header.append(PROTO_MAJOR)
    header.append(PROTO_MINOR)
    header.append(MSG_TYPE_CONFIG_RESPONSE)
    put_u16_le(header, seq & 0xFFFF)
    put_u32_le(header, utime.ticks_ms() & 0xFFFFFFFF)
    put_u16_le(header, len(payload))

    crc_data = bytearray()
    crc_data.extend(header)
    crc_data.extend(payload)
    crc = crc16_ccitt(crc_data)

    frame = bytearray()
    frame.append(FRAME_START_0)
    frame.append(FRAME_START_1)
    frame.extend(header)
    frame.extend(payload)
    put_u16_le(frame, crc)
    return frame


def _queue_config_response(seq, status, flags, text):
    global config_tx_pending, config_tx_offset
    config_tx_pending = _build_config_response(seq, status, flags, text)
    config_tx_offset = 0


def _safe_apply_window(commit_now=False):
    if fire_armed or on_armed or coil_active:
        return False
    rpm_limit = COMMIT_MAX_RPM if commit_now else APPLY_MAX_RPM
    if rpm_value > rpm_limit:
        return False
    return True


def _apply_profile_runtime(profile):
    global active_profile, crank_gear
    irq_state = disable_irq()
    active_profile = profile
    if crank_gear is not None:
        crank_gear.apply_profile(profile)
    _refresh_profile_caches(profile)
    enable_irq(irq_state)


def _refresh_profile_caches(profile):
    global advance_map_rpm_cache, advance_map_cd_cache, dwell_map_rpm_cache, dwell_map_us_cache
    if profile is None:
        advance_map_rpm_cache = ()
        advance_map_cd_cache = ()
        dwell_map_rpm_cache = ()
        dwell_map_us_cache = ()
        return
    advance_map_rpm_cache = tuple(profile.get("advance_map_rpm", ()))
    advance_map_cd_cache = tuple(profile.get("advance_map_cd", ()))
    dwell_map_rpm_cache = tuple(profile.get("dwell_map_rpm", ()))
    dwell_map_us_cache = tuple(profile.get("dwell_map_us", ()))


def _parse_cfg_tlvs(payload):
    mode = CFG_MODE_PREVIEW
    cfg_obj = None
    i = 0
    plen = len(payload)
    while i + 2 <= plen:
        t = payload[i]
        l = payload[i + 1]
        i += 2
        if i + l > plen:
            return None, None
        v = payload[i:i + l]
        i += l
        if t == TLV_CFG_MODE_U8 and l >= 1:
            mode = v[0]
        elif t == TLV_CFG_JSON:
            try:
                cfg_obj = ujson.loads(bytes(v).decode("utf-8"))
            except Exception:
                return None, None
    return mode, cfg_obj


def _expand_cfg_aliases(cfg_obj):
    if not isinstance(cfg_obj, dict):
        return None

    out = {}
    alias_map = {
        "tpr": "teeth_per_rev",
        "sti": "sync_tooth_index",
        "tmin": "tooth_min_us",
        "tmax": "tooth_max_us",
        "sfd": "safe_fire_delay_us",
        "sdw": "safe_dwell_us",
        "mtr": "missing_tooth_ratio",
        "amr": "advance_map_rpm",
        "amc": "advance_map_cd",
    }

    for k in cfg_obj:
        if k in alias_map:
            out[alias_map[k]] = cfg_obj[k]
        else:
            out[k] = cfg_obj[k]

    if "advance_map_cd" in out and "advance_map_rpm" not in out:
        cd = out.get("advance_map_cd")
        if isinstance(cd, list) and len(cd) == 21:
            out["advance_map_rpm"] = [i * 500 for i in range(21)]

    return out


def _handle_config_message(seq, payload):
    global pending_profile, pending_commit, pending_cfg_flags, pending_cfg_status, pending_cfg_text, pending_cfg_seq

    mode, cfg_obj = _parse_cfg_tlvs(payload)
    if cfg_obj is None:
        _queue_config_response(seq, CFG_STATUS_REJECTED, CFG_FLAG_PARSE_ERROR, "invalid cfg payload")
        return

    cfg_obj = _expand_cfg_aliases(cfg_obj)
    if cfg_obj is None:
        _queue_config_response(seq, CFG_STATUS_REJECTED, CFG_FLAG_PARSE_ERROR, "invalid cfg object")
        return

    merged = {}
    if active_profile is not None:
        merged.update(active_profile)
    for k in cfg_obj:
        merged[k] = cfg_obj[k]

    sanitized = config_layer.sanitize_profile(merged)
    flags = _cfg_flags(active_profile, sanitized)
    if sanitized != merged:
        flags |= CFG_FLAG_SANITIZED

    if mode == CFG_MODE_PREVIEW:
        _queue_config_response(seq, CFG_STATUS_OK, flags, "preview ok")
        return

    pending_profile = sanitized
    pending_commit = (mode == CFG_MODE_COMMIT)
    pending_cfg_flags = flags
    pending_cfg_status = CFG_STATUS_DEFERRED
    pending_cfg_text = "pending safe apply"
    pending_cfg_seq = seq
    _queue_config_response(seq, CFG_STATUS_DEFERRED, flags, "queued")


def _apply_pending_config_if_safe():
    global pending_profile, pending_commit, pending_cfg_flags, pending_cfg_status, pending_cfg_text, pending_cfg_seq

    if pending_profile is None or not _safe_apply_window(pending_commit):
        return

    apply_flags = pending_cfg_flags
    prof = pending_profile
    commit_now = pending_commit

    pending_profile = None
    pending_commit = False

    if apply_flags & CFG_FLAG_GEOMETRY_CHANGED:
        if commit_now:
            if config_layer.save_profile_pair(prof):
                apply_flags |= CFG_FLAG_PERSISTED
        apply_flags |= CFG_FLAG_REBOOT_REQUIRED
        pending_cfg_status = CFG_STATUS_OK
        pending_cfg_text = "geometry stored; reboot required"
        _queue_config_response(pending_cfg_seq, CFG_STATUS_OK, apply_flags, pending_cfg_text)
        return

    _apply_profile_runtime(prof)
    apply_flags |= CFG_FLAG_RUNTIME_APPLIED
    if commit_now:
        if config_layer.save_profile_pair(prof):
            apply_flags |= CFG_FLAG_PERSISTED
    pending_cfg_status = CFG_STATUS_OK
    pending_cfg_text = "applied"
    _queue_config_response(pending_cfg_seq, CFG_STATUS_OK, apply_flags, pending_cfg_text)


def degrade_to_safe(bit):
    global sync_state, ignition_mode, precision_lockout_until_ms, sync_soft_fails
    set_fault(bit)
    if sync_state == SYNC_SYNCED:
        sync_state = SYNC_SYNCING
    ignition_mode = IGN_MODE_SAFE
    sync_soft_fails = 0
    precision_lockout_until_ms = utime.ticks_add(utime.ticks_ms(), PRECISION_REENTRY_LOCKOUT_MS)
    cancel_events()
    force_coil_off()


def transition_to_lost(bit):
    global sync_state, ignition_mode, precision_lockout_until_ms, sync_soft_fails
    global rpm_value, crank_angle_deg
    set_fault(bit)
    sync_state = SYNC_LOST
    ignition_mode = IGN_MODE_INHIBIT
    sync_soft_fails = 0
    rpm_value = 0
    crank_angle_deg = 0
    precision_lockout_until_ms = utime.ticks_add(utime.ticks_ms(), PRECISION_REENTRY_LOCKOUT_MS)
    if crank_gear is not None:
        crank_gear.force_unsynced(GEAR_ERR_NONE)
    cancel_events()
    force_coil_off()


def schedule_cycle_events(now_us, fire_delay_us, dwell_us):
    global fire_armed, fire_time_us, fire_cycle_id
    global on_armed, on_time_us, on_cycle_id
    global unsched_streak

    if fire_delay_us <= 0:
        set_fault(FAULT_UNSCHEDULABLE)
        unsched_streak += 1
        return False

    fire_time = utime.ticks_add(now_us, fire_delay_us)
    on_time = utime.ticks_add(fire_time, -dwell_us)

    lead_on = utime.ticks_diff(on_time, now_us)
    lead_fire = utime.ticks_diff(fire_time, now_us)
    coil_on_width = utime.ticks_diff(fire_time, on_time)

    if lead_on < LEAD_GUARD_ON_US or lead_fire < LEAD_GUARD_FIRE_US or coil_on_width < MIN_COIL_ON_US:
        set_fault(FAULT_UNSCHEDULABLE)
        unsched_streak += 1
        return False

    irq = disable_irq()
    fire_time_us = fire_time
    fire_cycle_id = cycle_id
    fire_armed = True

    on_time_us = on_time
    on_cycle_id = cycle_id
    on_armed = True
    enable_irq(irq)

    unsched_streak = 0
    return True


def arm_precision_from_edge(now_us, dt_us):
    rpm_now = rpm_value
    dwell_eff = clamp(_interp_map(rpm_now, dwell_map_rpm_cache, dwell_map_us_cache), DWELL_MIN_US, DWELL_MAX_US)
    advance_cd = _interp_map(rpm_now, advance_map_rpm_cache, advance_map_cd_cache)

    # Final timestamp is edge-anchored to the measured interval for this cycle.
    fire_delay = dt_us - mul_div_smallint(dt_us, advance_cd, 36000)
    return schedule_cycle_events(now_us, fire_delay, dwell_eff)


def arm_safe_from_edge(now_us, dt_us):
    global safe_bounds_fail_count

    if dt_us < SAFE_PERIOD_MIN_US or dt_us > SAFE_PERIOD_MAX_US:
        set_fault(FAULT_UNSCHEDULABLE)
        safe_bounds_fail_count += 1
        return False

    safe_bounds_fail_count = 0
    safe_delay = SAFE_FIRE_DELAY_US
    safe_dwell = SAFE_DWELL_US
    if active_profile is not None:
        safe_delay = int(active_profile.get("safe_fire_delay_us", SAFE_FIRE_DELAY_US))
        safe_dwell = int(active_profile.get("safe_dwell_us", SAFE_DWELL_US))
    dwell_eff = clamp(safe_dwell, DWELL_MIN_US, DWELL_MAX_US)
    return schedule_cycle_events(now_us, safe_delay, dwell_eff)


def crank_isr(pin):
    global sync_state, rpm_value, crank_angle_deg
    global cycle_id, ignition_mode, unsched_streak, validity_bits

    isr_start = utime.ticks_us()

    if safety_inhibit_pin is not None and safety_inhibit_pin.value() == 0:
        set_fault(FAULT_SAFETY_INHIBIT)
        transition_to_lost(FAULT_SAFETY_INHIBIT)
        return

    now_us = utime.ticks_us()

    if crank_gear is None:
        transition_to_lost(FAULT_EDGE_PLAUSIBILITY)
        return

    edge_state = crank_gear.on_edge(now_us)

    if edge_state == GEAR_EDGE_FAIL:
        err = crank_gear.last_error
        if err == GEAR_ERR_TIMEOUT:
            transition_to_lost(FAULT_SYNC_TIMEOUT)
        elif err == GEAR_ERR_NOISE:
            transition_to_lost(FAULT_UNSTABLE_SYNC)
        else:
            transition_to_lost(FAULT_EDGE_PLAUSIBILITY)
        validity_bits = VALID_SYNC | VALID_IGN_MODE | VALID_FAULTS | VALID_IGN_OUT
        isr_elapsed = utime.ticks_diff(utime.ticks_us(), isr_start)
        if isr_elapsed > ISR_OVERRUN_LIMIT_US:
            set_fault(FAULT_ISR_OVERRUN)
        return

    sync_state = crank_gear.sync_state
    rpm_value = crank_gear.rpm
    crank_angle_deg = crank_gear.crank_angle_deg

    if sync_state == SYNC_SYNCED and utime.ticks_diff(utime.ticks_ms(), precision_lockout_until_ms) < 0:
        sync_state = SYNC_SYNCING

    if rpm_value > 0 and sync_state != SYNC_LOST:
        validity = VALID_RPM | VALID_SYNC | VALID_IGN_MODE | VALID_FAULTS | VALID_IGN_OUT
    else:
        validity = VALID_SYNC | VALID_IGN_MODE | VALID_FAULTS | VALID_IGN_OUT

    if sync_state == SYNC_LOST:
        ignition_mode = IGN_MODE_INHIBIT
        cancel_events()
        force_coil_off()

    if edge_state == GEAR_EDGE_REFERENCE:
        dt_us = crank_gear.rev_period_us
        cycle_id = (cycle_id + 1) & COUNTER_MASK

        if dt_us <= 0:
            transition_to_lost(FAULT_UNSCHEDULABLE)
            validity = VALID_SYNC | VALID_IGN_MODE | VALID_FAULTS | VALID_IGN_OUT
        elif sync_state == SYNC_SYNCED:
            ignition_mode = IGN_MODE_PRECISION
            if not arm_precision_from_edge(now_us, dt_us):
                if unsched_streak >= MAX_UNSCHED_STREAK_PRECISION:
                    degrade_to_safe(FAULT_UNSCHEDULABLE)
        elif sync_state == SYNC_SYNCING:
            ignition_mode = IGN_MODE_SAFE
            if not arm_safe_from_edge(now_us, dt_us):
                if safe_bounds_fail_count >= MAX_SAFE_BOUNDS_FAIL or unsched_streak >= MAX_UNSCHED_STREAK_SAFE:
                    transition_to_lost(FAULT_UNSCHEDULABLE)
        else:
            ignition_mode = IGN_MODE_INHIBIT
            cancel_events()
            force_coil_off()

    # Update validity atomically after edge processing.
    validity_bits = validity

    isr_elapsed = utime.ticks_diff(utime.ticks_us(), isr_start)
    if isr_elapsed > ISR_OVERRUN_LIMIT_US:
        set_fault(FAULT_ISR_OVERRUN)


def scheduler_tick(timer):
    global fire_armed, on_armed, spark_counter, coil_active

    now_us = utime.ticks_us()
    fire_processed = False
    fire_due = False
    fire_due_time = 0
    fire_due_cycle = 0

    # FIRE_OFF has highest priority and OFF is dominant when timestamps collide.
    irq = disable_irq()
    if fire_armed and event_due(now_us, fire_time_us):
        fire_due = True
        fire_due_time = fire_time_us
        fire_due_cycle = fire_cycle_id
        fire_armed = False
    enable_irq(irq)

    if fire_due:
        late = event_late_by(now_us, fire_due_time)
        if late > LATE_SLACK_US:
            set_fault(FAULT_STALE_EVENT)
            force_coil_off()
        elif fire_due_cycle != cycle_id or sync_state == SYNC_LOST or ignition_mode == IGN_MODE_INHIBIT:
            set_fault(FAULT_STALE_EVENT)
            force_coil_off()
        else:
            force_coil_off()
            spark_counter = (spark_counter + 1) & COUNTER_MASK
        fire_processed = True

    on_due = False
    on_due_time = 0
    on_due_cycle = 0

    irq = disable_irq()
    if on_armed and event_due(now_us, on_time_us):
        on_due = True
        on_due_time = on_time_us
        on_due_cycle = on_cycle_id
        on_armed = False
    enable_irq(irq)

    if on_due:
        late = event_late_by(now_us, on_due_time)
        if late > LATE_SLACK_US:
            set_fault(FAULT_STALE_EVENT)
            force_coil_off()
        elif on_due_cycle != cycle_id or sync_state == SYNC_LOST or ignition_mode == IGN_MODE_INHIBIT:
            set_fault(FAULT_STALE_EVENT)
            force_coil_off()
        elif fire_processed:
            set_fault(FAULT_STALE_EVENT)
            force_coil_off()
        else:
            if coil_pin is not None:
                coil_pin.on()
            coil_active = 1


def watchdog_tick(timer):
    now_us = utime.ticks_us()

    if crank_gear is not None and crank_gear.on_timeout(now_us):
        transition_to_lost(FAULT_SYNC_TIMEOUT)


def telemetry_tick(timer):
    global telemetry_due
    telemetry_due = True


def build_payload():
    irq = disable_irq()
    rpm_now = rpm_value
    sync_now = sync_state
    ign_mode_now = ignition_mode
    faults_now = fault_bits
    validity_now = validity_bits
    cycle_now = cycle_id
    spark_now = spark_counter
    ign_out_now = coil_active
    flog_used = fault_log_used
    flog_bits_snap = list(fault_log_bits[:flog_used])
    flog_rpm_snap = list(fault_log_rpm[:flog_used])
    flog_tooth_snap = list(fault_log_tooth[:flog_used])
    flog_avg_snap = list(fault_log_avg[:flog_used])
    flog_ts_snap = list(fault_log_ts[:flog_used])
    flog_count_snap = list(fault_log_count_arr[:flog_used])
    enable_irq(irq)

    payload = bytearray()

    tlv_u16(payload, TLV_RPM_U16, rpm_now & 0xFFFF)
    tlv_u8(payload, TLV_SYNC_STATE_U8, sync_now)
    tlv_u8(payload, TLV_IGNITION_MODE_U8, ign_mode_now)
    tlv_u32(payload, TLV_FAULT_BITS_U32, faults_now & 0xFFFFFFFF)
    tlv_u16(payload, TLV_VALIDITY_BITS_U16, validity_now & 0xFFFF)

    tlv_u32(payload, TLV_ECU_CYCLE_ID_U32, cycle_now)
    tlv_u32(payload, TLV_SPARK_COUNTER_U32, spark_now)
    tlv_u8(payload, TLV_IGNITION_OUTPUT_STATE_U8, ign_out_now)

    if flog_used > 0:
        flog_buf = bytearray()
        for i in range(flog_used):
            put_u32_le(flog_buf, flog_bits_snap[i] & 0xFFFFFFFF)
            put_u16_le(flog_buf, flog_rpm_snap[i] & 0xFFFF)
            put_u32_le(flog_buf, flog_tooth_snap[i] & 0xFFFFFFFF)
            put_u32_le(flog_buf, flog_avg_snap[i] & 0xFFFFFFFF)
            put_u32_le(flog_buf, flog_ts_snap[i] & 0xFFFFFFFF)
            put_u16_le(flog_buf, flog_count_snap[i] & 0xFFFF)
        tlv_bytes(payload, TLV_FAULT_LOG, flog_buf)

    # Optional fields are intentionally omitted by ECU core unless dedicated sensors are added.
    return payload


def _telemetry_uart_write(buf, offset):
    if uart is None:
        return 0
    try:
        n = uart.write(memoryview(buf)[offset:])
        if n is None:
            return 0
        return n
    except Exception:
        return 0


def flush_pending_config_tx():
    global config_tx_pending, config_tx_offset
    if config_tx_pending is None:
        return True
    wrote = _telemetry_uart_write(config_tx_pending, config_tx_offset)
    if wrote <= 0:
        return False
    config_tx_offset += wrote
    if config_tx_offset >= len(config_tx_pending):
        config_tx_pending = None
        config_tx_offset = 0
        return True
    return False


class ConfigIngest:
    def __init__(self, uart_obj):
        self.uart = uart_obj
        self.buf = bytearray()

    def _consume_frame(self):
        # Compact at most once while seeking sync to reduce allocation churn.
        if len(self.buf) >= 2:
            seek = 0
            seek_max = len(self.buf) - 1
            while seek < seek_max and (self.buf[seek] != FRAME_START_0 or self.buf[seek + 1] != FRAME_START_1):
                seek += 1
            if seek > 0:
                self.buf = self.buf[seek:]

        if len(self.buf) < 12:
            return False

        payload_len = self.buf[10] | (self.buf[11] << 8)
        total = 2 + 10 + payload_len + 2
        if len(self.buf) < total:
            return False

        body = self.buf[2:2 + 10 + payload_len]
        crc_rx = self.buf[2 + 10 + payload_len] | (self.buf[2 + 10 + payload_len + 1] << 8)
        if crc16_ccitt(body) == crc_rx:
            msg_type = body[2]
            seq = body[3] | (body[4] << 8)
            payload = body[10:10 + payload_len]
            if msg_type == MSG_TYPE_CONFIG_SET:
                _handle_config_message(seq, payload)

        self.buf = self.buf[total:]
        return True

    def poll(self):
        if self.uart is None:
            return
        try:
            waiting = self.uart.any()
        except Exception:
            return
        if waiting <= 0:
            return
        try:
            data = self.uart.read(waiting)
        except Exception:
            data = None
        if not data:
            return
        self.buf.extend(data)
        while self._consume_frame():
            pass


def flush_pending_telemetry():
    global telemetry_tx_pending, telemetry_tx_offset, telemetry_seq

    if telemetry_tx_pending is None:
        return True

    wrote = _telemetry_uart_write(telemetry_tx_pending, telemetry_tx_offset)
    if wrote <= 0:
        return False

    telemetry_tx_offset += wrote
    if telemetry_tx_offset >= len(telemetry_tx_pending):
        telemetry_tx_pending = None
        telemetry_tx_offset = 0
        telemetry_seq = (telemetry_seq + 1) & 0xFFFF
        return True

    return False


def send_telemetry():
    global telemetry_seq, telemetry_tx_pending, telemetry_tx_offset

    if not flush_pending_telemetry():
        return

    payload = build_payload()
    payload_len = len(payload)

    header = bytearray()
    header.append(PROTO_MAJOR)
    header.append(PROTO_MINOR)
    header.append(MSG_TYPE_ENGINE_STATE)
    put_u16_le(header, telemetry_seq)
    put_u32_le(header, utime.ticks_ms() & 0xFFFFFFFF)
    put_u16_le(header, payload_len)

    crc_data = bytearray()
    crc_data.extend(header)
    crc_data.extend(payload)
    crc = crc16_ccitt(crc_data)

    frame = bytearray()
    frame.append(FRAME_START_0)
    frame.append(FRAME_START_1)
    frame.extend(header)
    frame.extend(payload)
    put_u16_le(frame, crc)

    wrote = _telemetry_uart_write(frame, 0)
    if wrote <= 0:
        return

    if wrote < len(frame):
        telemetry_tx_pending = frame
        telemetry_tx_offset = wrote
        return

    telemetry_seq = (telemetry_seq + 1) & 0xFFFF


def load_boot_config_profile():
    global active_profile
    profile, recovered = config_layer.load_profile_with_recovery()
    if profile is None:
        profile = config_layer.default_profile()
    active_profile = config_layer.sanitize_profile(profile)
    _refresh_profile_caches(active_profile)
    if recovered:
        print("Config recovered from backup")
        led_flash(800, 120)


def init_hardware():
    global crank_pin, coil_pin, safety_inhibit_pin, led_pin, uart, crank_gear, config_ingest
    global scheduler_timer, watchdog_timer, telemetry_timer

    coil_pin = Pin(COIL_PIN, Pin.OUT)
    force_coil_off()

    safety_inhibit_pin = Pin(SAFETY_INHIBIT_PIN, Pin.IN, Pin.PULL_UP)
    led_pin = Pin(LED_PIN, Pin.OUT)
    led_set(0)

    crank_gear = CRANK_GEAR_LAYER(active_profile)

    crank_pin = Pin(CRANK_PIN, Pin.IN, Pin.PULL_DOWN)
    try:
        crank_pin.irq(trigger=Pin.IRQ_RISING, handler=crank_isr, hard=True)
    except TypeError:
        crank_pin.irq(trigger=Pin.IRQ_RISING, handler=crank_isr)

    try:
        uart = UART(UART_ID, baudrate=UART_BAUD, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN), txbuf=256, rxbuf=256)
    except TypeError:
        uart = UART(UART_ID, baudrate=UART_BAUD, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))
    config_ingest = ConfigIngest(uart)
    led_flash(200, 0)

    scheduler_timer = _new_timer(0)
    scheduler_timer.init(freq=SCHEDULER_TICK_HZ, callback=scheduler_tick)

    watchdog_timer = _new_timer(1)
    watchdog_timer.init(freq=WATCHDOG_HZ, callback=watchdog_tick)

    telemetry_timer = _new_timer(2)
    telemetry_timer.init(freq=TELEMETRY_HZ, callback=telemetry_tick)


def _new_timer(timer_id):
    candidates = (timer_id, 0, 1, -1, 2, 3)
    last_err = None
    for candidate in candidates:
        try:
            return Timer(candidate)
        except (TypeError, ValueError) as err:
            last_err = err
    if last_err is not None:
        if ALLOW_TIMER_FALLBACK:
            class _FallbackTimer:
                def init(self, *args, **kwargs):
                    return None

                def deinit(self):
                    return None

            print("Timer unavailable; running without timer interrupts")
            return _FallbackTimer()
        raise RuntimeError("No hardware timer available")
    raise RuntimeError("No available timer")


def run_loop():
    global telemetry_due

    while True:
        if config_ingest is not None:
            config_ingest.poll()

        _apply_pending_config_if_safe()
        flush_pending_config_tx()

        led_tick()

        if telemetry_due:
            telemetry_due = False
            send_telemetry()

        # Keep main loop lightweight; all control timing is in ISR/timer callbacks.
        utime.sleep_ms(2)


def stop_ecu():
    scheduler_timer.deinit()
    watchdog_timer.deinit()
    telemetry_timer.deinit()
    cancel_events()
    force_coil_off()
    led_set(0)


def start_ecu():
    load_boot_config_profile()
    init_hardware()
    print("ECU control started")
    try:
        run_loop()
    except KeyboardInterrupt:
        stop_ecu()
        print("ECU control stopped")


start_ecu()
