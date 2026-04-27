from machine import Pin, I2C, SPI, Timer, UART, disable_irq, enable_irq
from micropython import const
import micropython
import framebuf
import utime
import ujson
import uos
import machine
import gc

micropython.alloc_emergency_exception_buf(200)

# GPIO + UART mapping (Dash Pico)
# - OLED SDA/SCL: GP0/GP1
# - Button inputs: GP6..GP10
# - UART RX/TX from ECU: GP5/GP4 (UART1)
# - Legacy local sensor path (disabled by default):
#   RPM GP2, Speed GP3, MAX6675 SPI GP16/17/18/19

# -----------------------------
# USER SETTINGS (edit here)
# -----------------------------
machine.freq(266_000_000)
# Display hardware
I2C_ID = const(0)
I2C_SDA = const(0)
I2C_SCL = const(1)
I2C_FREQ = const(1000000)
OLED_ADDR = const(0x3C)
OLED_DRIVER = "SSD1309"  # "SSD1306" or "SSD1309"
OLED_RESET_PIN = -1

# ECU telemetry UART
UART_ID = const(1)
UART_TX_PIN = const(4)
UART_RX_PIN = const(5)
UART_BAUD = const(230400)

# Legacy local engine path (kept for compatibility only)
LEGACY_LOCAL_ENGINE_ENABLE = const(0)
SPI_ID = const(0)
SPI_SCK = const(18)
SPI_MOSI = const(19)
SPI_MISO = const(16)
SPI_CS = const(17)
RPM_PIN = const(2)
SPD_PIN = const(3)

# Local/legacy tuning values kept to preserve menu + persistence structure
RPM_PULSES_PER_REV = const(1)
RPM_DEBOUNCE_US = const(4000)
RPM_TIMEOUT_US = const(2000000)
RPM_PERIOD_RING_SIZE = const(7)
RPM_BAR_MAX = const(10000)
SPEED_MULTIPLIER = const(10)
WHEEL_SIZE_MM = const(2100)
SPEED_PULSES_PER_REV = const(1)

# Buttons (5 total)
BTN_UP_PIN = const(6)
BTN_DOWN_PIN = const(7)
BTN_LEFT_PIN = const(8)
BTN_RIGHT_PIN = const(9)
BTN_OK_PIN = const(10)
BTN_DEBOUNCE_MS = const(100)
OK_LONG_PRESS_MS = const(800)
MENU_SCROLL_STEP_MS = const(50)

# Display refresh and loop timing
RPM_UPDATE_HZ = const(30)  # used only in legacy mode
DISPLAY_PERIOD_MS = const(16)
MAIN_LOOP_SLEEP_MS = const(10)
GC_INTERVAL_MS = const(1000)
OLED_FAIL_RECOVER_THRESHOLD = const(3)
TRIP_SAVE_INTERVAL_MS = const(15000)
TEMP_READ_INTERVAL_MS = const(250)
SAVE_WHEN_RPM_BELOW = const(1800)
SENSOR_STATUS_TIMEOUT_MS = const(3000)
DEBUG_OVERLAY_DEFAULT = const(0)
DEMO_MODE_DEFAULT = const(1)
GRAPH_HISTORY_LEN = const(96)
GRAPH_SAMPLE_MS = const(200)
GRAPH_VIEW_POINTS = (24, 48, 72, 96)
TIMING_MAP_RPM_MIN = const(0)
TIMING_MAP_RPM_MAX = const(10000)
TIMING_MAP_RPM_STEP = const(500)
TIMING_MAP_ADV_MIN_CD = const(-1000)
TIMING_MAP_ADV_MAX_CD = const(4500)
TIMING_MAP_ADV_STEP_CD = const(10)

# Link state thresholds
LINK_STALE_MS = const(450)
LINK_LOST_MS = const(1800)
PARSER_STALL_MS = const(120)
CFG_TX_STALL_MS = const(1200)
CFG_TX_RETRY_MS = const(20)
CFG_TX_CHUNK_MAX = const(48)

# UI layout
RPM_BAR_X = const(4)
RPM_BAR_Y = const(2)
RPM_BAR_W = const(124)
RPM_BAR_H = const(10)
RPM_TICK_COUNT = const(5)
RPM_TICK_Y_OFFSET = const(11)
RPM_TICK_H = const(3)
RPM_SCALE_LABEL_Y = const(17)
RPM_TEXT_Y = const(26)
RPM_LABEL_GAP = const(4)
RPM_NUMBER_OFFSET = const(-5)
RPM_LABEL_OFFSET = const(-2)

BIG_DIGIT_W = const(16)
BIG_DIGIT_H = const(24)
BIG_DIGIT_THICK = const(2)
BIG_DIGIT_GAP = const(2)
BIG_DIGIT_SPACING = const(3)
SPEED_TEXT_Y = const(36)

KMH_TEXT = "km/h"
KMH_GAP_X = const(4)
KMH_Y_OFFSET = const(10)
TEMP_FAULT_TEXT = "TC ERR"
TEMP_TEXT_Y = const(56)

# Telemetry protocol constants (frozen contract)
FRAME_START_0 = const(0xAA)
FRAME_START_1 = const(0x55)
PROTO_MAJOR = const(1)
PROTO_MINOR = const(0)
MSG_TYPE_ENGINE_STATE = const(1)
MSG_TYPE_CONFIG_SET = const(2)
MSG_TYPE_CONFIG_RESPONSE = const(3)
# Bumped from 128 to fit the optional TLV_FAULT_LOG payload (up to
# 8 entries x 20 bytes = 160 bytes) alongside the existing TLVs.
MAX_PAYLOAD_LEN = const(256)

TLV_RPM_U16 = const(1)
TLV_SYNC_STATE_U8 = const(2)
TLV_IGNITION_MODE_U8 = const(3)
TLV_FAULT_BITS_U32 = const(4)
TLV_VALIDITY_BITS_U16 = const(5)
TLV_SPEED_KPH_X10_I16 = const(6)
TLV_TEMP_C_X10_I16 = const(7)
TLV_ECU_CYCLE_ID_U32 = const(8)
TLV_SPARK_COUNTER_U32 = const(9)
TLV_IGNITION_OUTPUT_STATE_U8 = const(10)
TLV_FAULT_LOG = const(11)

# Fault log entry layout (must match ECU build_payload encoding):
# fault_bit u32 LE | rpm u16 LE | tooth_period_us u32 LE | avg_period_us u32 LE | timestamp_ms u32 LE | count u16 LE
FAULT_LOG_ENTRY_LEN = const(20)
FAULT_LOG_MAX_ENTRIES = const(8)

# ECU fault bit numeric values (must match ecu/main.py).
FAULT_SYNC_TIMEOUT = const(1)
FAULT_EDGE_PLAUSIBILITY = const(2)
FAULT_UNSCHEDULABLE = const(4)
FAULT_STALE_EVENT = const(8)
FAULT_ISR_OVERRUN = const(16)
FAULT_SAFETY_INHIBIT = const(32)
FAULT_UNSTABLE_SYNC = const(64)

# ECU ignition modes
IGN_MODE_INHIBIT = const(0)
IGN_MODE_SAFE = const(1)
IGN_MODE_PRECISION = const(2)

TLV_CFG_MODE_U8 = const(1)
TLV_CFG_JSON = const(2)
TLV_CFG_STATUS_U8 = const(3)
TLV_CFG_FLAGS_U16 = const(4)
TLV_CFG_PROFILE_CRC_U16 = const(5)
TLV_CFG_TEXT = const(6)

CFG_MODE_PREVIEW = const(0)
CFG_MODE_APPLY = const(1)
CFG_MODE_COMMIT = const(2)

# Validity bits (must match ECU contract)
VALID_RPM = const(1 << 0)
VALID_SYNC = const(1 << 1)
VALID_IGN_MODE = const(1 << 2)
VALID_FAULTS = const(1 << 3)
VALID_IGN_OUT = const(1 << 4)
VALID_SPEED = const(1 << 5)
VALID_TEMP = const(1 << 6)

# Link states
LINK_OK = const(0)
LINK_STALE = const(1)
LINK_LOST = const(2)


# -----------------------------
# Utilities
# -----------------------------
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


@micropython.viper
def crc16_ccitt_update(crc: int, data: ptr8, length: int) -> int:
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
    return crc16_ccitt_update(0xFFFF, data, len(data))


def u16_from_le(data, idx):
    return data[idx] | (data[idx + 1] << 8)


def u32_from_le(data, idx):
    return (
        data[idx]
        | (data[idx + 1] << 8)
        | (data[idx + 2] << 16)
        | (data[idx + 3] << 24)
    )


def i16_from_le(data, idx):
    val = u16_from_le(data, idx)
    if val & 0x8000:
        val -= 0x10000
    return val


def put_u16_le(buf, value):
    buf.append(value & 0xFF)
    buf.append((value >> 8) & 0xFF)


def put_u32_le(buf, value):
    buf.append(value & 0xFF)
    buf.append((value >> 8) & 0xFF)
    buf.append((value >> 16) & 0xFF)
    buf.append((value >> 24) & 0xFF)


def tlv_u8(buf, field_type, value):
    buf.append(field_type)
    buf.append(1)
    buf.append(value & 0xFF)


def tlv_bytes(buf, field_type, value_bytes):
    ln = len(value_bytes)
    if ln > 255:
        ln = 255
    buf.append(field_type)
    buf.append(ln)
    buf.extend(memoryview(value_bytes)[:ln])


def seq_newer_u16(new_seq, old_seq):
    diff = (new_seq - old_seq) & 0xFFFF
    return diff != 0 and diff < 0x8000


def format_cd_text(value_cd):
    sign = ""
    v = value_cd
    if v < 0:
        sign = "-"
        v = -v
    whole = v // 100
    frac = v % 100
    return sign + str(whole) + "." + "{:02d}".format(frac)


def build_default_adv_map_cd(rpm_points):
    out = []
    for rpm in rpm_points:
        # 6.00 deg at 0 RPM to 22.00 deg at 10k RPM.
        cd = 600 + ((rpm * 16) // 100)
        out.append(clamp(cd, TIMING_MAP_ADV_MIN_CD, TIMING_MAP_ADV_MAX_CD))
    return out


def _interp_map(rpm, x_points, y_points):
    # Same algorithm as ECU _interp_map: clamp to endpoints, otherwise
    # piecewise-linear interpolation in integer space. Used by the dash to
    # mirror the ECU's commanded advance locally for the ADV display.
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


# Plain-English fault descriptions for the FLOG screen. The ECU transmits
# raw bit values; the dash maps each to a short label and a longer line.
FAULT_NAMES = (
    (FAULT_SYNC_TIMEOUT,      "SYNC TIMEOUT",  "No teeth seen >250ms"),
    (FAULT_EDGE_PLAUSIBILITY, "EDGE BAD",      "Implausible tooth edge"),
    (FAULT_UNSCHEDULABLE,     "UNSCHED",       "Fire delay too short"),
    (FAULT_STALE_EVENT,       "STALE FIRE",    "Missed fire window"),
    (FAULT_ISR_OVERRUN,       "ISR SLOW",      "ISR took >20us"),
    (FAULT_SAFETY_INHIBIT,    "KILL ACTIVE",   "Kill switch open"),
    (FAULT_UNSTABLE_SYNC,     "SYNC UNSTABLE", "Noise on crank signal"),
)


def fault_short_name(bit):
    for fbit, short, _ in FAULT_NAMES:
        if fbit == bit:
            return short
    return "FLT 0x" + "{:X}".format(bit & 0xFFFFFFFF)


def fault_long_name(bit):
    for fbit, _, long in FAULT_NAMES:
        if fbit == bit:
            return long
    return "Unknown fault"


def file_exists(path):
    try:
        uos.stat(path)
        return True
    except Exception:
        return False


# -----------------------------
# SSD1306/SSD1309 (I2C)
# -----------------------------
class SSD1306(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C, driver="SSD1306"):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.driver = driver
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        self._cmd_buf = bytearray(2)
        self._page_buf = bytearray(1 + width)
        self._page_buf[0] = 0x40
        self._init_display()

    def _write_cmd(self, cmd):
        try:
            self._cmd_buf[1] = cmd
            self.i2c.writeto(self.addr, self._cmd_buf)
            return True
        except Exception:
            return False

    def _init_display(self):
        driver = self.driver.upper()

        if driver == "SSD1309":
            cmds = (
                0xAE,
                0x20, 0x00,
                0x40,
                0xA1,
                0xC8,
                0x81, 0xCF,
                0xA6,
                0xA8, 0x3F,
                0xD3, 0x00,
                0xD5, 0x80,
                0xD9, 0x22,
                0xDA, 0x12,
                0xDB, 0x34,
                0xAF,
            )
        else:
            cmds = (
                0xAE,
                0x20, 0x00,
                0x40,
                0xA1,
                0xC8,
                0x81, 0xCF,
                0xA6,
                0xA8, 0x3F,
                0xD3, 0x00,
                0xD5, 0x80,
                0xD9, 0xF1,
                0xDA, 0x12,
                0xDB, 0x40,
                0x8D, 0x14,
                0xAF,
            )

        for cmd in cmds:
            if not self._write_cmd(cmd):
                return False

        self.fill(0)
        self.show()
        return True

    def show(self):
        try:
            for page in range(self.pages):
                if not self._write_cmd(0xB0 | page):
                    return False
                if not self._write_cmd(0x00):
                    return False
                if not self._write_cmd(0x10):
                    return False
                start = self.width * page
                self._page_buf[1:] = self.buffer[start:start + self.width]
                self.i2c.writeto(self.addr, self._page_buf)
            return True
        except Exception:
            return False


# -----------------------------
# Legacy sensor class (optional)
# -----------------------------
class MAX6675:
    def __init__(self, spi, cs_pin):
        self.spi = spi
        self.cs = Pin(cs_pin, Pin.OUT)
        self.cs.on()

    def read_temp_with_diag(self):
        self.cs.off()
        utime.sleep_us(1)
        raw = self.spi.read(2)
        self.cs.on()

        if not raw or len(raw) != 2:
            return None, "RAW ----"

        value = (raw[0] << 8) | raw[1]
        if value & 0x0004:
            return None, "RAW " + hex(value) + " O1"
        # Raw counts are 0.25 C units; round to whole int degrees, no float.
        counts = (value >> 3) & 0x0FFF
        return (counts + 2) // 4, "RAW " + hex(value) + " O0"


# -----------------------------
# Telemetry ingest + snapshot
# -----------------------------
class EngineSnapshot:
    def __init__(self):
        self.seq = 0
        self.ecu_time_ms = 0
        self.rx_time_ms = 0

        self.rpm = -1
        self.sync_state = 0
        self.ignition_mode = 0
        self.fault_bits = 0
        self.validity_bits = 0

        self.speed_x10 = None
        self.temp_x10 = None
        self.ecu_cycle_id = 0
        self.spark_counter = 0
        self.ign_output = 0

        # Structured fault log mirrored from ECU. Each entry is a tuple of
        # (fault_bit, rpm, tooth_period_us, avg_period_us, timestamp_ms, count).
        # Empty list = ECU reports no faults.
        self.fault_log = []


class TelemetryIngest:
    ST_SEEK_0 = const(0)
    ST_SEEK_1 = const(1)
    ST_HEADER = const(2)
    ST_PAYLOAD = const(3)
    ST_CRC = const(4)

    HEADER_LEN = const(11)  # major/minor/msg/seq/u32time/payload_len

    def __init__(self, uart_obj):
        self.uart = uart_obj

        self.state = self.ST_SEEK_0
        self.header = bytearray(self.HEADER_LEN)
        self.header_i = 0
        self.payload = bytearray(MAX_PAYLOAD_LEN)
        self.payload_len = 0
        self.payload_i = 0
        self.crc_bytes = bytearray(2)
        self.crc_i = 0

        self.h_major = 0
        self.h_minor = 0
        self.h_msg_type = 0
        self.h_seq = 0
        self.h_ecu_time_ms = 0

        self.snapshot = EngineSnapshot()
        self.has_snapshot = False
        self.last_seq = None
        self.last_rx_ms = 0

        self.frames_ok = 0
        self.frames_crc_fail = 0
        self.frames_parse_fail = 0
        self.frames_old_seq = 0
        self.last_progress_ms = utime.ticks_ms()
        self.rx_buf = bytearray(64)

        self.dec_seq = 0
        self.dec_ecu_time_ms = 0
        self.dec_rx_time_ms = 0
        self.dec_rpm = 0
        self.dec_sync_state = 0
        self.dec_ignition_mode = 0
        self.dec_fault_bits = 0
        self.dec_validity_bits = 0
        self.dec_speed_x10 = None
        self.dec_temp_x10 = None
        self.dec_ecu_cycle_id = 0
        self.dec_spark_counter = 0
        self.dec_ign_output = 0
        self.dec_fault_log = []

    def _reset(self):
        self.state = self.ST_SEEK_0
        self.header_i = 0
        self.payload_len = 0
        self.payload_i = 0
        self.crc_i = 0
        self.last_progress_ms = utime.ticks_ms()

    def poll(self):
        now_ms = utime.ticks_ms()
        if self.has_snapshot and utime.ticks_diff(now_ms, self.last_rx_ms) > LINK_LOST_MS:
            irq = disable_irq()
            self.has_snapshot = False
            self.last_seq = None
            enable_irq(irq)

        if self.state != self.ST_SEEK_0 and utime.ticks_diff(now_ms, self.last_progress_ms) > PARSER_STALL_MS:
            self.frames_parse_fail += 1
            self._reset()

        chunks = 0
        while chunks < 8:
            n = self.uart.any()
            if n <= 0:
                return

            got = 0
            try:
                got = self.uart.readinto(self.rx_buf)
            except Exception:
                data = self.uart.read(32)
                if not data:
                    return
                self.last_progress_ms = utime.ticks_ms()
                for b in data:
                    self._feed_byte(b)
                continue

            if not got:
                return

            self.last_progress_ms = utime.ticks_ms()
            if got > len(self.rx_buf):
                got = len(self.rx_buf)
            for i in range(got):
                self._feed_byte(self.rx_buf[i])

            chunks += 1

    def _feed_byte(self, b):
        if self.state == self.ST_SEEK_0:
            if b == FRAME_START_0:
                self.state = self.ST_SEEK_1
            return

        if self.state == self.ST_SEEK_1:
            if b == FRAME_START_1:
                self.state = self.ST_HEADER
                self.header_i = 0
            elif b == FRAME_START_0:
                self.state = self.ST_SEEK_1
            else:
                self.state = self.ST_SEEK_0
            return

        if self.state == self.ST_HEADER:
            self.header[self.header_i] = b
            self.header_i += 1
            if self.header_i >= self.HEADER_LEN:
                self.h_major = self.header[0]
                self.h_minor = self.header[1]
                self.h_msg_type = self.header[2]
                self.h_seq = u16_from_le(self.header, 3)
                self.h_ecu_time_ms = u32_from_le(self.header, 5)
                self.payload_len = u16_from_le(self.header, 9)

                if self.h_major != PROTO_MAJOR:
                    self.frames_parse_fail += 1
                    self._reset()
                    return

                if self.h_msg_type != MSG_TYPE_ENGINE_STATE and self.h_msg_type != MSG_TYPE_CONFIG_RESPONSE:
                    self.frames_parse_fail += 1
                    self._reset()
                    return

                if self.payload_len > MAX_PAYLOAD_LEN:
                    self.frames_parse_fail += 1
                    self._reset()
                    return

                if self.payload_len <= 0:
                    self.frames_parse_fail += 1
                    self._reset()
                    return

                self.payload_i = 0
                self.state = self.ST_PAYLOAD
            return

        if self.state == self.ST_PAYLOAD:
            self.payload[self.payload_i] = b
            self.payload_i += 1
            if self.payload_i >= self.payload_len:
                self.crc_i = 0
                self.state = self.ST_CRC
            return

        if self.state == self.ST_CRC:
            self.crc_bytes[self.crc_i] = b
            self.crc_i += 1
            if self.crc_i >= 2:
                self._finalize_frame()
                self._reset()

    def _finalize_frame(self):
        global ecu_cfg_last_status, ecu_cfg_last_flags

        crc_recv = u16_from_le(self.crc_bytes, 0)
        crc_calc = crc16_ccitt(self.header)
        crc_calc = crc16_ccitt_update(crc_calc, self.payload, self.payload_len)

        if crc_calc != crc_recv:
            self.frames_crc_fail += 1
            return

        if self.h_msg_type == MSG_TYPE_CONFIG_RESPONSE:
            resp = self._decode_cfg_response(self.payload, self.payload_len)
            if resp is None:
                self.frames_parse_fail += 1
                return
            ecu_cfg_last_flags = resp.get("flags", 0)
            ecu_cfg_last_status = resp.get("status_text", "CFG rsp")
            self.frames_ok += 1
            return

        if not self._decode_tlv(self.payload, self.payload_len):
            self.frames_parse_fail += 1
            return

        if self.has_snapshot and not seq_newer_u16(self.dec_seq, self.last_seq):
            self.frames_old_seq += 1
            return

        irq = disable_irq()
        snap = self.snapshot
        snap.seq = self.dec_seq
        snap.ecu_time_ms = self.dec_ecu_time_ms
        snap.rx_time_ms = self.dec_rx_time_ms
        snap.rpm = self.dec_rpm
        snap.sync_state = self.dec_sync_state
        snap.ignition_mode = self.dec_ignition_mode
        snap.fault_bits = self.dec_fault_bits
        snap.validity_bits = self.dec_validity_bits
        snap.speed_x10 = self.dec_speed_x10
        snap.temp_x10 = self.dec_temp_x10
        snap.ecu_cycle_id = self.dec_ecu_cycle_id
        snap.spark_counter = self.dec_spark_counter
        snap.ign_output = self.dec_ign_output
        snap.fault_log = self.dec_fault_log
        self.has_snapshot = True
        self.last_seq = self.dec_seq
        self.last_rx_ms = self.dec_rx_time_ms
        enable_irq(irq)

        self.frames_ok += 1

    def _decode_tlv(self, payload, payload_len):
        idx = 0
        seen_required = 0
        rpm = None
        sync_state = None
        ignition_mode = None
        fault_bits = None
        validity_bits = None
        speed_x10 = None
        temp_x10 = None
        ecu_cycle_id = 0
        spark_counter = 0
        ign_output = 0
        fault_log = []
        rx_time_ms = utime.ticks_ms()

        while idx < payload_len:
            if idx + 2 > payload_len:
                return False

            field_type = payload[idx]
            field_len = payload[idx + 1]
            idx += 2

            if idx + field_len > payload_len:
                return False

            if field_type == TLV_RPM_U16:
                if field_len != 2:
                    return False
                if rpm is None:
                    rpm = u16_from_le(payload, idx)
                    seen_required |= 1

            elif field_type == TLV_SYNC_STATE_U8:
                if field_len != 1:
                    return False
                if sync_state is None:
                    sync_state = payload[idx]
                    seen_required |= 2

            elif field_type == TLV_IGNITION_MODE_U8:
                if field_len != 1:
                    return False
                if ignition_mode is None:
                    ignition_mode = payload[idx]
                    seen_required |= 4

            elif field_type == TLV_FAULT_BITS_U32:
                if field_len != 4:
                    return False
                if fault_bits is None:
                    fault_bits = u32_from_le(payload, idx)
                    seen_required |= 8

            elif field_type == TLV_VALIDITY_BITS_U16:
                if field_len != 2:
                    return False
                if validity_bits is None:
                    validity_bits = u16_from_le(payload, idx)
                    seen_required |= 16

            elif field_type == TLV_SPEED_KPH_X10_I16:
                if field_len != 2:
                    return False
                if speed_x10 is None:
                    speed_x10 = i16_from_le(payload, idx)

            elif field_type == TLV_TEMP_C_X10_I16:
                if field_len != 2:
                    return False
                if temp_x10 is None:
                    temp_x10 = i16_from_le(payload, idx)

            elif field_type == TLV_ECU_CYCLE_ID_U32:
                if field_len != 4:
                    return False
                ecu_cycle_id = u32_from_le(payload, idx)

            elif field_type == TLV_SPARK_COUNTER_U32:
                if field_len != 4:
                    return False
                spark_counter = u32_from_le(payload, idx)

            elif field_type == TLV_IGNITION_OUTPUT_STATE_U8:
                if field_len != 1:
                    return False
                ign_output = payload[idx]

            elif field_type == TLV_FAULT_LOG:
                # Length must be a non-zero multiple of FAULT_LOG_ENTRY_LEN
                # and bounded by FAULT_LOG_MAX_ENTRIES. Fail the frame if
                # malformed so we never display garbage in the FLOG screen.
                if field_len == 0 or (field_len % FAULT_LOG_ENTRY_LEN) != 0:
                    return False
                n_entries = field_len // FAULT_LOG_ENTRY_LEN
                if n_entries > FAULT_LOG_MAX_ENTRIES:
                    return False
                fault_log = []
                for k in range(n_entries):
                    off = idx + (k * FAULT_LOG_ENTRY_LEN)
                    fbit = u32_from_le(payload, off)
                    fr = u16_from_le(payload, off + 4)
                    ft = u32_from_le(payload, off + 6)
                    fa = u32_from_le(payload, off + 10)
                    fts = u32_from_le(payload, off + 14)
                    fc = u16_from_le(payload, off + 18)
                    fault_log.append((fbit, fr, ft, fa, fts, fc))

            # Unknown TLV fields are safely skipped.
            idx += field_len

        # required: rpm/sync/ignition/fault/validity
        if seen_required != 31:
            return False

        self.dec_seq = self.h_seq
        self.dec_ecu_time_ms = self.h_ecu_time_ms
        self.dec_rx_time_ms = rx_time_ms
        self.dec_rpm = 0 if rpm is None else rpm
        self.dec_sync_state = 0 if sync_state is None else sync_state
        self.dec_ignition_mode = 0 if ignition_mode is None else ignition_mode
        self.dec_fault_bits = 0 if fault_bits is None else fault_bits
        self.dec_validity_bits = 0 if validity_bits is None else validity_bits
        self.dec_speed_x10 = speed_x10
        self.dec_temp_x10 = temp_x10
        self.dec_ecu_cycle_id = ecu_cycle_id
        self.dec_spark_counter = spark_counter
        self.dec_ign_output = ign_output
        self.dec_fault_log = fault_log
        return True

    def _decode_cfg_response(self, payload, payload_len):
        idx = 0
        status = None
        flags = 0
        text = ""
        while idx < payload_len:
            if idx + 2 > payload_len:
                return None
            t = payload[idx]
            l = payload[idx + 1]
            idx += 2
            if idx + l > payload_len:
                return None
            if t == TLV_CFG_STATUS_U8 and l >= 1:
                status = payload[idx]
            elif t == TLV_CFG_FLAGS_U16 and l == 2:
                flags = u16_from_le(payload, idx)
            elif t == TLV_CFG_TEXT and l > 0:
                try:
                    text = bytes(payload[idx:idx + l]).decode("utf-8")
                except Exception:
                    text = "cfg"
            idx += l

        if status is None:
            return None

        if status == 0:
            st = "OK"
        elif status == 1:
            st = "REJ"
        else:
            st = "DEF"

        if text:
            status_text = "CFG " + st + " " + text
        else:
            status_text = "CFG " + st
        return {"status": status, "flags": flags, "status_text": status_text}


class EngineSnapshotAdapter:
    def __init__(self, ingest):
        self.ingest = ingest
        self.link_state = LINK_LOST

    def update_link_state(self):
        irq = disable_irq()
        has_snapshot = self.ingest.has_snapshot
        last_rx_ms = self.ingest.last_rx_ms
        enable_irq(irq)

        if not has_snapshot:
            self.link_state = LINK_LOST
            return

        age_ms = utime.ticks_diff(utime.ticks_ms(), last_rx_ms)
        if age_ms <= LINK_STALE_MS:
            self.link_state = LINK_OK
        elif age_ms <= LINK_LOST_MS:
            self.link_state = LINK_STALE
        else:
            self.link_state = LINK_LOST

    def get_link_state(self):
        return self.link_state

    def get_link_mark(self):
        if self.link_state == LINK_OK:
            return "L+"
        if self.link_state == LINK_STALE:
            return "L~"
        return "L-"

    def _snapshot(self):
        irq = disable_irq()
        has_snapshot = self.ingest.has_snapshot
        snap = self.ingest.snapshot if has_snapshot else None
        enable_irq(irq)
        return snap

    def get_display_rpm(self):
        snap = self._snapshot()
        if snap is None:
            return -1
        if self.link_state == LINK_LOST:
            return -1
        if (snap.validity_bits & VALID_RPM) == 0:
            return -1
        return snap.rpm

    def get_display_sync_state(self):
        snap = self._snapshot()
        if snap is None:
            return -1
        if self.link_state == LINK_LOST:
            return -1
        if (snap.validity_bits & VALID_SYNC) == 0:
            return -1
        return snap.sync_state

    def get_display_ignition_mode(self):
        snap = self._snapshot()
        if snap is None:
            return -1
        if self.link_state == LINK_LOST:
            return -1
        if (snap.validity_bits & VALID_IGN_MODE) == 0:
            return -1
        return snap.ignition_mode

    def get_display_faults(self):
        snap = self._snapshot()
        if snap is None:
            return 0
        if self.link_state == LINK_LOST:
            return 0
        if (snap.validity_bits & VALID_FAULTS) == 0:
            return 0
        return snap.fault_bits

    def get_display_speed(self):
        snap = self._snapshot()
        if snap is None:
            return -1
        if self.link_state != LINK_OK:
            return -1
        if (snap.validity_bits & VALID_SPEED) == 0:
            return -1
        if snap.speed_x10 is None:
            return -1

        v = snap.speed_x10
        if v >= 0:
            return (v + 5) // 10
        return -((-v + 5) // 10)

    def get_display_temp(self):
        snap = self._snapshot()
        if snap is None:
            return None
        if self.link_state != LINK_OK:
            return None
        if (snap.validity_bits & VALID_TEMP) == 0:
            return None
        if snap.temp_x10 is None:
            return None
        t = snap.temp_x10
        if t >= 0:
            return (t + 5) // 10
        return -((-t + 5) // 10)

    def get_fault_log(self):
        # Return a snapshot tuple (entries, ecu_time_ms) so the caller can
        # compute "seconds since last" against the same ECU timeline that
        # produced each entry's timestamp_ms.
        irq = disable_irq()
        has_snapshot = self.ingest.has_snapshot
        if has_snapshot:
            snap = self.ingest.snapshot
            entries = list(snap.fault_log)
            ecu_time_ms = snap.ecu_time_ms
        else:
            entries = []
            ecu_time_ms = 0
        enable_irq(irq)
        return entries, ecu_time_ms


# -----------------------------
# Runtime state
# -----------------------------
# Legacy local engine state (kept behind compatibility flag)
rpm_last_pulse_us = 0
rpm_value = 0
rpm_period_us = [0] * RPM_PERIOD_RING_SIZE
rpm_period_head = 0
rpm_period_count = 0

spd_ticks = 0
spd_value = 0
speed_last_pulse_ms = utime.ticks_ms()

# Sensor/telemetry view values used by UI flow
legacy_temp = None
legacy_temp_diag = "RAW ----"
temp_last_read_ms = utime.ticks_ms()
display_last_recover_ms = utime.ticks_ms()
display_last_draw_ms = utime.ticks_ms()
oled_consecutive_fails = 0
gc_last_ms = utime.ticks_ms()

# Runtime-tunable values (editable from menu; persisted for compatibility)
rpm_debounce_us = RPM_DEBOUNCE_US
rpm_pulses_per_rev = RPM_PULSES_PER_REV
wheel_size_mm = WHEEL_SIZE_MM
speed_pulses_per_rev = SPEED_PULSES_PER_REV
rpm_bar_max = RPM_BAR_MAX
speed_multiplier = SPEED_MULTIPLIER
speed_last_update_ms = utime.ticks_ms()
telemetry_dist_last_ms = utime.ticks_ms()

# Menu state
menu_active = False
info_active = False
graph_active = False
flog_active = False
flog_index = 0
map_editor_active = False
graph_channel = 0  # 0=RPM, 1=SPD, 2=TMP
graph_view_idx = 2
graph_paused = False
map_point_index = 0
menu_index = 0
last_btn_ms = 0
ok_press_start_ms = None
ok_long_fired = False
btn_prev_up = False
btn_prev_down = False
btn_prev_left = False
btn_prev_right = False
btn_prev_ok = False
menu_scroll_x = 128
menu_scroll_last_ms = 0
MENU_HELP_TEXT = "U/D select  L/R adjust  OK exit"
MENU_HELP_RESET_ARM = "RSET: OK arm  U/D cancel"
MENU_HELP_RESET_CONFIRM = "RSET: OK confirm  U/D cancel"
MENU_HELP_TCLR_ARM = "TCLR: OK arm  U/D cancel"
MENU_HELP_TCLR_CONFIRM = "TCLR: OK confirm  U/D cancel"
SETTINGS_FILE = "dashboard_settings.json"
settings_dirty = False
ecu_cfg_dirty = False
reset_confirm_armed = False
trip_clear_confirm_armed = False
ecu_commit_confirm_armed = False
trip_mm = 0
odo_mm = 0
engine_runtime_s = 0
trip_dirty = False
odo_dirty = False
runtime_dirty = False
runtime_accum_ms = 0
runtime_last_ms = utime.ticks_ms()
persistent_last_save_ms = utime.ticks_ms()
debug_overlay_enabled = DEBUG_OVERLAY_DEFAULT
demo_mode_enabled = DEMO_MODE_DEFAULT
debug_loop_ms = 0
demo_last_ms = utime.ticks_ms()
demo_phase = 0

ecu_teeth_per_rev = 21
ecu_sync_tooth_index = 0
ecu_tooth_min_us = 300
ecu_tooth_max_us = 8000
ecu_safe_fire_delay_us = 2500
ecu_safe_dwell_us = 1700
# Stored as ratio*10 so the menu adjusts in integer 0.1 steps. Sent over
# the wire as a float (mtr alias -> missing_tooth_ratio) — see
# build_ecu_config_payload below.
ecu_missing_tooth_ratio_x10 = 18
ecu_adv_map_rpm = [TIMING_MAP_RPM_MIN + (i * TIMING_MAP_RPM_STEP) for i in range((TIMING_MAP_RPM_MAX // TIMING_MAP_RPM_STEP) + 1)]
ecu_adv_map_cd = build_default_adv_map_cd(ecu_adv_map_rpm)

config_tx_seq = 0
config_tx_pending = None
config_tx_offset = 0
config_tx_started_ms = 0
config_tx_last_progress_ms = 0
config_tx_next_try_ms = 0
ecu_cfg_last_status = "CFG --"
ecu_cfg_last_flags = 0

# History buffers: -1 marks invalid/gap sample
graph_hist_rpm = [-1] * GRAPH_HISTORY_LEN
graph_hist_spd = [-1] * GRAPH_HISTORY_LEN
graph_hist_tmp = [-1] * GRAPH_HISTORY_LEN
graph_hist_head = 0
graph_hist_count = 0
graph_last_sample_ms = utime.ticks_ms()

# Telemetry ingest + adapter singletons
class _NullTelemetryIngest:
    def poll(self):
        return


class _NullEngineAdapter:
    def update_link_state(self):
        return

    def get_link_state(self):
        return LINK_LOST

    def get_link_mark(self):
        return "L-"

    def get_display_rpm(self):
        return -1

    def get_display_sync_state(self):
        return -1

    def get_display_ignition_mode(self):
        return -1

    def get_display_faults(self):
        return 0

    def get_display_speed(self):
        return -1

    def get_display_temp(self):
        return None

    def get_fault_log(self):
        return [], 0


telemetry_ingest = _NullTelemetryIngest()
engine_adapter = _NullEngineAdapter()
telemetry_uart = None


# -----------------------------
# Persistence
# -----------------------------
def load_settings():
    global rpm_debounce_us, rpm_pulses_per_rev
    global wheel_size_mm, speed_pulses_per_rev, rpm_bar_max, speed_multiplier
    global trip_mm, odo_mm, engine_runtime_s, debug_overlay_enabled, demo_mode_enabled
    global ecu_teeth_per_rev, ecu_sync_tooth_index, ecu_tooth_min_us, ecu_tooth_max_us
    global ecu_safe_fire_delay_us, ecu_safe_dwell_us, ecu_adv_map_cd
    global ecu_missing_tooth_ratio_x10

    tmp_file = SETTINGS_FILE + ".tmp"
    if file_exists(tmp_file):
        if file_exists(SETTINGS_FILE):
            try:
                uos.remove(tmp_file)
            except Exception:
                pass
        else:
            try:
                uos.rename(tmp_file, SETTINGS_FILE)
            except Exception:
                pass

    try:
        with open(SETTINGS_FILE, "r") as f:
            data = ujson.load(f)

        rpm_debounce_us = clamp(int(data.get("rpm_debounce_us", rpm_debounce_us)), 2000, 9000)
        rpm_pulses_per_rev = clamp(int(data.get("rpm_pulses_per_rev", rpm_pulses_per_rev)), 1, 4)
        wheel_size_mm = clamp(int(data.get("wheel_size_mm", wheel_size_mm)), 1000, 3000)
        speed_pulses_per_rev = clamp(int(data.get("speed_pulses_per_rev", speed_pulses_per_rev)), 1, 20)
        rpm_bar_max = clamp(int(data.get("rpm_bar_max", rpm_bar_max)), 4000, 20000)
        speed_multiplier = clamp(int(data.get("speed_multiplier", speed_multiplier)), 1, 50)
        trip_mm = clamp(int(data.get("trip_mm", trip_mm)), 0, 99999999)
        odo_mm = clamp(int(data.get("odo_mm", odo_mm)), 0, 999999999)
        engine_runtime_s = clamp(int(data.get("engine_runtime_s", engine_runtime_s)), 0, 999999999)
        debug_overlay_enabled = clamp(int(data.get("debug_overlay_enabled", debug_overlay_enabled)), 0, 1)
        demo_mode_enabled = clamp(int(data.get("demo_mode_enabled", demo_mode_enabled)), 0, 1)
        ecu_teeth_per_rev = clamp(int(data.get("ecu_teeth_per_rev", ecu_teeth_per_rev)), 8, 240)
        ecu_sync_tooth_index = clamp(int(data.get("ecu_sync_tooth_index", ecu_sync_tooth_index)), 0, ecu_teeth_per_rev - 1)
        ecu_tooth_min_us = clamp(int(data.get("ecu_tooth_min_us", ecu_tooth_min_us)), 20, 20000)
        ecu_tooth_max_us = clamp(int(data.get("ecu_tooth_max_us", ecu_tooth_max_us)), 200, 500000)
        if ecu_tooth_max_us <= ecu_tooth_min_us:
            ecu_tooth_max_us = ecu_tooth_min_us + 200
        ecu_safe_fire_delay_us = clamp(int(data.get("ecu_safe_fire_delay_us", ecu_safe_fire_delay_us)), 500, 25000)
        ecu_safe_dwell_us = clamp(int(data.get("ecu_safe_dwell_us", ecu_safe_dwell_us)), 800, 4000)
        ecu_missing_tooth_ratio_x10 = clamp(int(data.get("ecu_missing_tooth_ratio_x10", ecu_missing_tooth_ratio_x10)), 12, 30)

        cd_list = data.get("ecu_adv_map_cd", ecu_adv_map_cd)
        if isinstance(cd_list, list) and len(cd_list) == len(ecu_adv_map_rpm):
            clean = []
            for i in range(len(ecu_adv_map_rpm)):
                clean.append(clamp(int(cd_list[i]), TIMING_MAP_ADV_MIN_CD, TIMING_MAP_ADV_MAX_CD))
            ecu_adv_map_cd = clean
    except Exception:
        pass


def save_settings():
    data = {
        "rpm_debounce_us": rpm_debounce_us,
        "rpm_pulses_per_rev": rpm_pulses_per_rev,
        "wheel_size_mm": wheel_size_mm,
        "speed_pulses_per_rev": speed_pulses_per_rev,
        "rpm_bar_max": rpm_bar_max,
        "speed_multiplier": speed_multiplier,
        "trip_mm": trip_mm,
        "odo_mm": odo_mm,
        "engine_runtime_s": engine_runtime_s,
        "debug_overlay_enabled": debug_overlay_enabled,
        "demo_mode_enabled": demo_mode_enabled,
        "ecu_teeth_per_rev": ecu_teeth_per_rev,
        "ecu_sync_tooth_index": ecu_sync_tooth_index,
        "ecu_tooth_min_us": ecu_tooth_min_us,
        "ecu_tooth_max_us": ecu_tooth_max_us,
        "ecu_safe_fire_delay_us": ecu_safe_fire_delay_us,
        "ecu_safe_dwell_us": ecu_safe_dwell_us,
        "ecu_missing_tooth_ratio_x10": ecu_missing_tooth_ratio_x10,
        "ecu_adv_map_cd": ecu_adv_map_cd,
    }
    tmp_file = SETTINGS_FILE + ".tmp"

    try:
        with open(tmp_file, "w") as f:
            ujson.dump(data, f)
            try:
                f.flush()
            except Exception:
                pass

        try:
            uos.rename(tmp_file, SETTINGS_FILE)
        except Exception:
            try:
                uos.remove(SETTINGS_FILE)
            except Exception:
                pass
            uos.rename(tmp_file, SETTINGS_FILE)
        return True
    except Exception:
        try:
            uos.remove(tmp_file)
        except Exception:
            pass
        return False


# -----------------------------
# Legacy interrupt handlers (optional path)
# -----------------------------
def rpm_interrupt(pin):
    if not LEGACY_LOCAL_ENGINE_ENABLE:
        return
    if demo_mode_enabled:
        return

    global rpm_last_pulse_us, rpm_period_us, rpm_period_head, rpm_period_count
    now = utime.ticks_us()
    if not rpm_last_pulse_us:
        rpm_last_pulse_us = now
        return

    dt = utime.ticks_diff(now, rpm_last_pulse_us)
    if dt < rpm_debounce_us:
        return

    rpm_last_pulse_us = now
    if dt <= RPM_TIMEOUT_US:
        rpm_period_us[rpm_period_head] = dt
        rpm_period_head = (rpm_period_head + 1) % RPM_PERIOD_RING_SIZE
        if rpm_period_count < RPM_PERIOD_RING_SIZE:
            rpm_period_count += 1


def spd_interrupt(pin):
    if demo_mode_enabled:
        return

    global spd_ticks, speed_last_pulse_ms
    spd_ticks += 1
    speed_last_pulse_ms = utime.ticks_ms()




# -----------------------------
# Engine snapshot adapter getters (MANDATORY UI API)
# -----------------------------
def get_display_rpm():
    if demo_mode_enabled:
        return rpm_value
    if LEGACY_LOCAL_ENGINE_ENABLE:
        return get_rpm_legacy()
    return engine_adapter.get_display_rpm()


def get_display_sync_state():
    if demo_mode_enabled:
        return 2 if rpm_value > 0 else 0
    if LEGACY_LOCAL_ENGINE_ENABLE:
        return 2 if get_rpm_legacy() > 0 else 0
    return engine_adapter.get_display_sync_state()


def get_display_ignition_mode():
    if demo_mode_enabled:
        return 2 if rpm_value > 0 else 0
    if LEGACY_LOCAL_ENGINE_ENABLE:
        return 2 if get_rpm_legacy() > 0 else 0
    return engine_adapter.get_display_ignition_mode()


def get_display_faults():
    if demo_mode_enabled:
        return 0
    if LEGACY_LOCAL_ENGINE_ENABLE:
        return 0
    return engine_adapter.get_display_faults()


def get_display_speed():
    if demo_mode_enabled:
        return spd_value
    if LEGACY_LOCAL_ENGINE_ENABLE:
        return spd_value
    ecu_speed = engine_adapter.get_display_speed()
    if ecu_speed >= 0:
        return ecu_speed
    return spd_value


def get_display_temp():
    if demo_mode_enabled:
        return legacy_temp
    if LEGACY_LOCAL_ENGINE_ENABLE:
        return legacy_temp
    ecu_temp = engine_adapter.get_display_temp()
    if ecu_temp is not None:
        return ecu_temp
    return legacy_temp


# -----------------------------
# Calculations
# -----------------------------
def update_rpm_legacy(timer):
    if not LEGACY_LOCAL_ENGINE_ENABLE:
        return
    if demo_mode_enabled:
        return

    global rpm_value, rpm_last_pulse_us, rpm_period_us, rpm_period_count

    irq_state = disable_irq()
    last_pulse = rpm_last_pulse_us
    period_count = rpm_period_count
    period_copy = rpm_period_us[:]
    enable_irq(irq_state)

    if not last_pulse or utime.ticks_diff(utime.ticks_us(), last_pulse) >= RPM_TIMEOUT_US:
        rpm_value = 0
        return

    if period_count == 0:
        return

    values = []
    for i in range(period_count):
        p = period_copy[i]
        if p > 0:
            values.append(p)

    if not values:
        return

    values.sort()
    med_period = values[len(values) // 2]
    if med_period <= 0:
        return

    rpm_value = int(60000000 / (med_period * rpm_pulses_per_rev))


def get_rpm_legacy():
    if not LEGACY_LOCAL_ENGINE_ENABLE:
        return 0
    if demo_mode_enabled:
        return rpm_value

    if not rpm_last_pulse_us:
        return 0
    if utime.ticks_diff(utime.ticks_us(), rpm_last_pulse_us) >= RPM_TIMEOUT_US:
        return 0
    return rpm_value


def update_speed_legacy():
    if demo_mode_enabled:
        return

    global spd_ticks, spd_value, speed_last_update_ms
    global trip_mm, trip_dirty, odo_mm, odo_dirty

    irq_state = disable_irq()
    ticks = spd_ticks
    spd_ticks = 0
    enable_irq(irq_state)

    now_ms = utime.ticks_ms()
    elapsed_ms = utime.ticks_diff(now_ms, speed_last_update_ms)
    speed_last_update_ms = now_ms

    if elapsed_ms <= 0:
        return

    if speed_pulses_per_rev > 0 and wheel_size_mm > 0:
        circ_mm = (wheel_size_mm * 31416) // 10000
        dist_num = ticks * circ_mm
        denom = speed_pulses_per_rev * elapsed_ms * 10
        if denom > 0:
            spd_value = (dist_num * 36) // denom
        else:
            spd_value = 0

        dist_int = (dist_num + (speed_pulses_per_rev // 2)) // speed_pulses_per_rev
        if dist_int > 0:
            apply_distance_mm(dist_int)
    else:
        spd_value = ticks * speed_multiplier


def update_distance_from_telemetry_speed():
    global telemetry_dist_last_ms

    now_ms = utime.ticks_ms()
    elapsed_ms = utime.ticks_diff(now_ms, telemetry_dist_last_ms)
    telemetry_dist_last_ms = now_ms
    if elapsed_ms <= 0:
        return

    speed_kph = get_display_speed()
    if speed_kph < 0:
        return

    dist_mm = (speed_kph * elapsed_ms * 1000) // 3600
    if dist_mm > 0:
        apply_distance_mm(dist_mm)


def apply_distance_mm(dist_mm):
    global trip_mm, odo_mm, trip_dirty, odo_dirty

    trip_mm += dist_mm
    odo_mm += dist_mm

    if trip_mm < 0:
        trip_mm = 0
    elif trip_mm > 99999999:
        trip_mm = 99999999

    if odo_mm < 0:
        odo_mm = 0
    elif odo_mm > 999999999:
        odo_mm = 999999999

    trip_dirty = True
    odo_dirty = True


def format_temp_text(temp_value):
    if temp_value is None:
        return "--C"
    if temp_value < -99 or temp_value > 999:
        return TEMP_FAULT_TEXT
    return str(temp_value) + "C"


def format_trip_text(mm_value):
    if mm_value < 0:
        mm_value = 0
    km10 = mm_value // 100000
    return "TR " + str(km10 // 10) + "." + str(km10 % 10)


def format_odo_text(mm_value):
    if mm_value < 0:
        mm_value = 0
    return str(mm_value // 1000000)


def format_runtime_text(seconds):
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    return "RUN " + str(hours) + ":" + "{:02d}".format(mins) + ":" + "{:02d}".format(secs)


def get_sensor_status_text():
    if demo_mode_enabled:
        return "DEM R+ S+ T+"

    if LEGACY_LOCAL_ENGINE_ENABLE:
        now_us = utime.ticks_us()
        now_ms = utime.ticks_ms()

        rpm_ok = rpm_last_pulse_us and utime.ticks_diff(now_us, rpm_last_pulse_us) < RPM_TIMEOUT_US
        speed_ok = utime.ticks_diff(now_ms, speed_last_pulse_ms) < SENSOR_STATUS_TIMEOUT_MS
        temp_ok = legacy_temp is not None
        return "R" + ("+" if rpm_ok else "-") + " S" + ("+" if speed_ok else "-") + " T" + ("+" if temp_ok else "-")

    link_mark = engine_adapter.get_link_mark()
    sync = get_display_sync_state()
    ign = get_display_ignition_mode()

    if sync < 0:
        sync_txt = "-"
    elif sync == 0:
        sync_txt = "L"
    elif sync == 1:
        sync_txt = "S"
    else:
        sync_txt = "K"

    if ign < 0:
        ign_txt = "-"
    elif ign == 0:
        ign_txt = "I"
    elif ign == 1:
        ign_txt = "S"
    else:
        ign_txt = "P"

    return link_mark + " SY" + sync_txt + " IG" + ign_txt


def update_history_samples():
    global graph_hist_head, graph_hist_count, graph_last_sample_ms

    now = utime.ticks_ms()
    if utime.ticks_diff(now, graph_last_sample_ms) < GRAPH_SAMPLE_MS:
        return
    graph_last_sample_ms = now

    if not LEGACY_LOCAL_ENGINE_ENABLE and engine_adapter.get_link_state() != LINK_OK:
        rpm_hist = -1
        spd_hist = -1
        tmp_hist = -1
    else:
        rpm_hist = get_display_rpm()
        if rpm_hist < 0:
            rpm_hist = -1

        spd_hist = get_display_speed()
        if spd_hist < 0:
            spd_hist = -1

        temp_val = get_display_temp()
        if temp_val is None:
            tmp_hist = -1
        else:
            tmp_hist = int(temp_val + 0.5)

    graph_hist_rpm[graph_hist_head] = rpm_hist
    graph_hist_spd[graph_hist_head] = spd_hist
    graph_hist_tmp[graph_hist_head] = tmp_hist

    graph_hist_head = (graph_hist_head + 1) % GRAPH_HISTORY_LEN
    if graph_hist_count < GRAPH_HISTORY_LEN:
        graph_hist_count += 1


def get_hist_value(channel, idx):
    if channel == 0:
        return graph_hist_rpm[idx]
    if channel == 1:
        return graph_hist_spd[idx]
    return graph_hist_tmp[idx]


def format_graph_axis_value(channel, value):
    if channel == 0:
        return str(value // 1000) + "k"
    return str(value)


def draw_ecu_link_badge():
    # Status square only (no text), middle-left at x=0, y=32. 6x6px.
    if LEGACY_LOCAL_ENGINE_ENABLE:
        oled.fill_rect(0, 32, 6, 6, 1)
        return

    state = engine_adapter.get_link_state()

    if state == LINK_OK:
        oled.fill_rect(0, 32, 6, 6, 1)
    elif state == LINK_STALE:
        oled.rect(0, 32, 6, 6, 1)
    else:
        if (utime.ticks_ms() // 250) % 2 == 0:
            oled.fill_rect(0, 32, 6, 6, 1)
        else:
            oled.rect(0, 32, 6, 6, 1)


def draw_history_graph(channel):
    oled.fill(0)

    if channel == 0:
        title = "GR RPM"
        min_v = 0
        max_v = rpm_bar_max if rpm_bar_max > 0 else 10000
    elif channel == 1:
        title = "GR SPD"
        min_v = 0
        max_v = 120
    else:
        title = "GR TMP"
        min_v = 0
        max_v = 200

    oled.text(title, 0, 0, 1)
    if graph_paused:
        oled.text("PAUSE", 72, 0, 1)
    oled.text("U/D span L/R ch", 0, 56, 1)

    gx = 24
    gy = 12
    gw = 102
    gh = 30
    oled.rect(gx, gy, gw, gh, 1)

    for i in range(1, 4):
        yy = gy + int((i * (gh - 1)) / 4)
        oled.hline(gx + 1, yy, gw - 2, 1)
    for i in range(1, 4):
        xx = gx + int((i * (gw - 1)) / 4)
        oled.vline(xx, gy + 1, gh - 2, 1)

    mid_v = min_v + ((max_v - min_v) // 2)
    oled.text(format_graph_axis_value(channel, max_v), 0, gy - 2, 1)
    oled.text(format_graph_axis_value(channel, mid_v), 0, gy + (gh // 2) - 4, 1)
    oled.text(format_graph_axis_value(channel, min_v), 0, gy + gh - 8, 1)

    visible_count = GRAPH_VIEW_POINTS[graph_view_idx]
    if graph_hist_count < visible_count:
        visible_count = graph_hist_count

    if visible_count < 2:
        oled.text("collecting...", 28, 30, 1)
        return

    start = graph_hist_head - visible_count
    while start < 0:
        start += GRAPH_HISTORY_LEN

    prev_valid = False
    prev_x = 0
    prev_y = 0
    plotted_count = 0

    for i in range(visible_count):
        idx = (start + i) % GRAPH_HISTORY_LEN
        raw_val = get_hist_value(channel, idx)
        x = gx + 1 + int((i * (gw - 3)) / (visible_count - 1))

        if raw_val < 0:
            prev_valid = False
            continue

        val = raw_val
        if val < min_v:
            val = min_v
        if val > max_v:
            val = max_v

        y = gy + gh - 2 - int(((val - min_v) * (gh - 3)) / (max_v - min_v if (max_v - min_v) > 0 else 1))

        if prev_valid:
            oled.line(prev_x, prev_y, x, y, 1)
        prev_x = x
        prev_y = y
        prev_valid = True
        plotted_count += 1

    if plotted_count == 0:
        oled.text("no valid", 40, 30, 1)

    span_s = (visible_count * GRAPH_SAMPLE_MS) // 1000
    oled.text("-" + str(span_s) + "s", gx, 44, 1)
    oled.text("now", gx + gw - 24, 44, 1)

    last_idx = graph_hist_head - 1
    if last_idx < 0:
        last_idx = GRAPH_HISTORY_LEN - 1
    last_val = get_hist_value(channel, last_idx)

    if last_val < 0:
        if channel == 0:
            oled.text("----", 88, 0, 1)
        elif channel == 1:
            oled.text("--k", 88, 0, 1)
        else:
            oled.text("--C", 88, 0, 1)
    elif channel == 0:
        oled.text(str(last_val), 88, 0, 1)
    elif channel == 1:
        oled.text(str(last_val) + "k", 88, 0, 1)
    else:
        oled.text(str(last_val) + "C", 88, 0, 1)


def update_demo_values():
    global demo_last_ms, demo_phase
    global rpm_value, spd_value, legacy_temp
    global rpm_last_pulse_us, speed_last_pulse_ms

    now_ms = utime.ticks_ms()
    dt_ms = utime.ticks_diff(now_ms, demo_last_ms)
    if dt_ms <= 0:
        return
    demo_last_ms = now_ms

    demo_phase = (demo_phase + (dt_ms * 3)) % 2000

    if demo_phase < 1000:
        rpm_value = 1200 + (demo_phase * 9)
    else:
        rpm_value = 1200 + ((1999 - demo_phase) * 9)

    spd_value = rpm_value // 120
    legacy_temp = 70 + ((demo_phase // 50) % 16)

    rpm_last_pulse_us = utime.ticks_us()
    speed_last_pulse_ms = now_ms

    dist_mm = (spd_value * dt_ms * 1000) // 3600
    if dist_mm > 0:
        apply_distance_mm(dist_mm)


def update_runtime():
    global runtime_last_ms, runtime_accum_ms, engine_runtime_s, runtime_dirty

    now = utime.ticks_ms()
    dt = utime.ticks_diff(now, runtime_last_ms)
    runtime_last_ms = now
    if dt <= 0:
        return

    runtime_accum_ms += dt
    if runtime_accum_ms >= 1000:
        inc_s = runtime_accum_ms // 1000
        runtime_accum_ms = runtime_accum_ms % 1000
        engine_runtime_s += inc_s
        if engine_runtime_s > 999999999:
            engine_runtime_s = 999999999
        runtime_dirty = True


def maybe_save_persistent_state():
    global trip_dirty, odo_dirty, runtime_dirty, persistent_last_save_ms

    if not (trip_dirty or odo_dirty or runtime_dirty):
        return

    rpm_now = get_display_rpm()
    if rpm_now >= 0 and rpm_now > SAVE_WHEN_RPM_BELOW:
        return

    now = utime.ticks_ms()
    if utime.ticks_diff(now, persistent_last_save_ms) < TRIP_SAVE_INTERVAL_MS:
        return

    # Avoid blocking writes while UI is actively interactive.
    if menu_active or info_active or graph_active or flog_active:
        return

    # In telemetry mode, skip writes while parser is assembling a frame.
    if not LEGACY_LOCAL_ENGINE_ENABLE:
        parser_state = getattr(telemetry_ingest, "state", 0)
        parser_seek = getattr(telemetry_ingest, "ST_SEEK_0", 0)
        if parser_state != parser_seek:
            return

    if save_settings():
        trip_dirty = False
        odo_dirty = False
        runtime_dirty = False
        persistent_last_save_ms = now


# -----------------------------
# Buttons / menu
# -----------------------------
def button_pressed(pin_obj):
    return pin_obj.value() == 0


def get_button_event():
    global last_btn_ms, ok_press_start_ms, ok_long_fired
    global btn_prev_up, btn_prev_down, btn_prev_left, btn_prev_right, btn_prev_ok
    now = utime.ticks_ms()

    up_now = button_pressed(btn_up)
    down_now = button_pressed(btn_down)
    left_now = button_pressed(btn_left)
    right_now = button_pressed(btn_right)
    ok_now = button_pressed(btn_ok)

    up_edge = up_now and (not btn_prev_up)
    down_edge = down_now and (not btn_prev_down)
    left_edge = left_now and (not btn_prev_left)
    right_edge = right_now and (not btn_prev_right)
    ok_edge = ok_now and (not btn_prev_ok)

    btn_prev_up = up_now
    btn_prev_down = down_now
    btn_prev_left = left_now
    btn_prev_right = right_now
    btn_prev_ok = ok_now

    # OK long-press retains priority once held long enough.
    if ok_now:
        if ok_press_start_ms is None:
            ok_press_start_ms = now
            ok_long_fired = False
        elif (not ok_long_fired) and utime.ticks_diff(now, ok_press_start_ms) >= OK_LONG_PRESS_MS:
            if utime.ticks_diff(now, last_btn_ms) >= BTN_DEBOUNCE_MS:
                last_btn_ms = now
                ok_long_fired = True
                return "OK_LONG"
    else:
        ok_press_start_ms = None
        ok_long_fired = False

    if utime.ticks_diff(now, last_btn_ms) < BTN_DEBOUNCE_MS:
        return None

    # Edge-triggered short events make menu input reliable on bench.
    if ok_edge:
        last_btn_ms = now
        return "OK"
    if up_edge:
        last_btn_ms = now
        return "UP"
    if down_edge:
        last_btn_ms = now
        return "DOWN"
    if left_edge:
        last_btn_ms = now
        return "LEFT"
    if right_edge:
        last_btn_ms = now
        return "RIGHT"
    return None


def settings_count():
    # 0..6 local, 7..13 ECU values (7=ECTH..13=EMTR), 14=TMAP, 15=ECMT,
    # 16=RSET, 17=TRIP (read-only), 18=TCLR. Total 19.
    return 19


def reset_settings_to_defaults():
    global rpm_debounce_us, rpm_pulses_per_rev
    global wheel_size_mm, speed_pulses_per_rev, rpm_bar_max, speed_multiplier
    global debug_overlay_enabled, demo_mode_enabled
    global ecu_teeth_per_rev, ecu_sync_tooth_index, ecu_tooth_min_us, ecu_tooth_max_us
    global ecu_safe_fire_delay_us, ecu_safe_dwell_us, ecu_adv_map_cd
    global ecu_missing_tooth_ratio_x10

    rpm_debounce_us = RPM_DEBOUNCE_US
    rpm_pulses_per_rev = RPM_PULSES_PER_REV
    wheel_size_mm = WHEEL_SIZE_MM
    speed_pulses_per_rev = SPEED_PULSES_PER_REV
    rpm_bar_max = RPM_BAR_MAX
    speed_multiplier = SPEED_MULTIPLIER
    debug_overlay_enabled = DEBUG_OVERLAY_DEFAULT
    demo_mode_enabled = DEMO_MODE_DEFAULT
    ecu_teeth_per_rev = 21
    ecu_sync_tooth_index = 0
    ecu_tooth_min_us = 300
    ecu_tooth_max_us = 8000
    ecu_safe_fire_delay_us = 2500
    ecu_safe_dwell_us = 1700
    ecu_missing_tooth_ratio_x10 = 18
    ecu_adv_map_cd = build_default_adv_map_cd(ecu_adv_map_rpm)


def clear_trip():
    global trip_mm, trip_dirty
    trip_mm = 0
    trip_dirty = True


def adjust_setting(index, delta):
    global settings_dirty, ecu_cfg_dirty
    global rpm_debounce_us, rpm_pulses_per_rev
    global wheel_size_mm, speed_pulses_per_rev, rpm_bar_max, debug_overlay_enabled, demo_mode_enabled
    global ecu_teeth_per_rev, ecu_sync_tooth_index, ecu_tooth_min_us, ecu_tooth_max_us
    global ecu_safe_fire_delay_us, ecu_safe_dwell_us, ecu_missing_tooth_ratio_x10

    before = (
        rpm_debounce_us,
        rpm_pulses_per_rev,
        wheel_size_mm,
        speed_pulses_per_rev,
        rpm_bar_max,
        debug_overlay_enabled,
        demo_mode_enabled,
        ecu_teeth_per_rev,
        ecu_sync_tooth_index,
        ecu_tooth_min_us,
        ecu_tooth_max_us,
        ecu_safe_fire_delay_us,
        ecu_safe_dwell_us,
        ecu_missing_tooth_ratio_x10,
    )

    if index == 0:
        rpm_debounce_us += delta * 100
        rpm_debounce_us = clamp(rpm_debounce_us, 2000, 9000)
    elif index == 1:
        rpm_pulses_per_rev += delta
        rpm_pulses_per_rev = clamp(rpm_pulses_per_rev, 1, 4)
    elif index == 2:
        wheel_size_mm += delta * 10
        wheel_size_mm = clamp(wheel_size_mm, 1000, 3000)
    elif index == 3:
        speed_pulses_per_rev += delta
        speed_pulses_per_rev = clamp(speed_pulses_per_rev, 1, 20)
    elif index == 4:
        rpm_bar_max += delta * 500
        rpm_bar_max = clamp(rpm_bar_max, 4000, 20000)
    elif index == 5:
        if delta != 0:
            debug_overlay_enabled = 0 if debug_overlay_enabled else 1
    elif index == 6:
        if delta != 0:
            demo_mode_enabled = 0 if demo_mode_enabled else 1
    elif index == 7:
        ecu_teeth_per_rev += delta
        ecu_teeth_per_rev = clamp(ecu_teeth_per_rev, 8, 240)
        ecu_sync_tooth_index = clamp(ecu_sync_tooth_index, 0, ecu_teeth_per_rev - 1)
    elif index == 8:
        ecu_sync_tooth_index += delta
        ecu_sync_tooth_index = clamp(ecu_sync_tooth_index, 0, ecu_teeth_per_rev - 1)
    elif index == 9:
        ecu_tooth_min_us += delta * 10
        ecu_tooth_min_us = clamp(ecu_tooth_min_us, 20, 20000)
        if ecu_tooth_max_us <= ecu_tooth_min_us:
            ecu_tooth_max_us = ecu_tooth_min_us + 200
    elif index == 10:
        ecu_tooth_max_us += delta * 100
        ecu_tooth_max_us = clamp(ecu_tooth_max_us, 200, 500000)
        if ecu_tooth_max_us <= ecu_tooth_min_us:
            ecu_tooth_max_us = ecu_tooth_min_us + 200
    elif index == 11:
        ecu_safe_fire_delay_us += delta * 100
        ecu_safe_fire_delay_us = clamp(ecu_safe_fire_delay_us, 500, 25000)
    elif index == 12:
        ecu_safe_dwell_us += delta * 50
        ecu_safe_dwell_us = clamp(ecu_safe_dwell_us, 800, 4000)
    elif index == 13:
        # EMTR step is 0.1 -> integer 1 in the *10 representation.
        ecu_missing_tooth_ratio_x10 += delta
        ecu_missing_tooth_ratio_x10 = clamp(ecu_missing_tooth_ratio_x10, 12, 30)

    after = (
        rpm_debounce_us,
        rpm_pulses_per_rev,
        wheel_size_mm,
        speed_pulses_per_rev,
        rpm_bar_max,
        debug_overlay_enabled,
        demo_mode_enabled,
        ecu_teeth_per_rev,
        ecu_sync_tooth_index,
        ecu_tooth_min_us,
        ecu_tooth_max_us,
        ecu_safe_fire_delay_us,
        ecu_safe_dwell_us,
        ecu_missing_tooth_ratio_x10,
    )
    if after != before:
        settings_dirty = True
        if index >= 7 and index <= 13:
            ecu_cfg_dirty = True


def handle_buttons():
    global menu_active, info_active, graph_active, map_editor_active
    global flog_active, flog_index
    global graph_channel, graph_view_idx, graph_paused, map_point_index, menu_index
    global settings_dirty, ecu_cfg_dirty, reset_confirm_armed, trip_clear_confirm_armed, ecu_commit_confirm_armed
    global trip_dirty, odo_dirty, runtime_dirty
    global ecu_cfg_last_status

    graph_paused = graph_active and button_pressed(btn_up) and button_pressed(btn_down)

    event = get_button_event()
    if event is None:
        return

    if map_editor_active:
        if event == "OK" or event == "OK_LONG":
            map_editor_active = False
        elif event == "UP":
            map_point_index -= 1
            if map_point_index < 0:
                map_point_index = 0
        elif event == "DOWN":
            map_point_index += 1
            if map_point_index >= len(ecu_adv_map_cd):
                map_point_index = len(ecu_adv_map_cd) - 1
        elif event == "LEFT":
            old = ecu_adv_map_cd[map_point_index]
            new_val = clamp(old - TIMING_MAP_ADV_STEP_CD, TIMING_MAP_ADV_MIN_CD, TIMING_MAP_ADV_MAX_CD)
            if new_val != old:
                ecu_adv_map_cd[map_point_index] = new_val
                settings_dirty = True
                ecu_cfg_dirty = True
        elif event == "RIGHT":
            old = ecu_adv_map_cd[map_point_index]
            new_val = clamp(old + TIMING_MAP_ADV_STEP_CD, TIMING_MAP_ADV_MIN_CD, TIMING_MAP_ADV_MAX_CD)
            if new_val != old:
                ecu_adv_map_cd[map_point_index] = new_val
                settings_dirty = True
                ecu_cfg_dirty = True
        return

    if not menu_active and not info_active and not graph_active and not flog_active:
        if event == "OK":
            menu_active = True
            reset_confirm_armed = False
            trip_clear_confirm_armed = False
            ecu_commit_confirm_armed = False
        elif event == "OK_LONG":
            info_active = True
        return

    if graph_active:
        if graph_paused:
            return
        if event == "OK" or event == "OK_LONG":
            graph_active = False
        elif event == "LEFT":
            graph_channel = (graph_channel - 1) % 3
        elif event == "RIGHT":
            graph_channel = (graph_channel + 1) % 3
        elif event == "UP":
            if graph_view_idx < (len(GRAPH_VIEW_POINTS) - 1):
                graph_view_idx += 1
        elif event == "DOWN":
            if graph_view_idx > 0:
                graph_view_idx -= 1
        return

    if flog_active:
        # Navigation chain: info -> flog -> graph. LEFT past first entry
        # backs up to info; RIGHT past last entry advances to graph. If the
        # log is empty, RIGHT goes straight to graph.
        entries, _ = engine_adapter.get_fault_log()
        total = len(entries)
        if event == "OK" or event == "OK_LONG":
            flog_active = False
        elif event == "RIGHT":
            if total == 0 or flog_index >= total - 1:
                flog_active = False
                graph_active = True
            else:
                flog_index += 1
        elif event == "LEFT":
            if flog_index > 0:
                flog_index -= 1
            else:
                flog_active = False
                info_active = True
        return

    if info_active:
        if event == "OK" or event == "OK_LONG":
            info_active = False
        elif event == "RIGHT":
            info_active = False
            flog_active = True
            flog_index = 0
        return

    if event == "OK" and menu_index == 14:
        map_editor_active = True
        return

    if event == "OK" and menu_index == 15:
        if not ecu_commit_confirm_armed:
            ecu_commit_confirm_armed = True
            ecu_cfg_last_status = "CFG arm commit"
        else:
            if send_ecu_config(CFG_MODE_COMMIT):
                ecu_cfg_dirty = False
            ecu_commit_confirm_armed = False
        return

    if event == "OK" and menu_index == 16:
        if not reset_confirm_armed:
            reset_confirm_armed = True
        else:
            reset_settings_to_defaults()
            ecu_cfg_dirty = True
            if save_settings():
                settings_dirty = False
                trip_dirty = False
                odo_dirty = False
                runtime_dirty = False
            reset_confirm_armed = False
        return

    if event == "OK" and menu_index == 18:
        if not trip_clear_confirm_armed:
            trip_clear_confirm_armed = True
        else:
            clear_trip()
            if save_settings():
                trip_dirty = False
                odo_dirty = False
                runtime_dirty = False
            trip_clear_confirm_armed = False
        return

    if event == "OK":
        if settings_dirty:
            if save_settings():
                settings_dirty = False
                trip_dirty = False
                odo_dirty = False
                runtime_dirty = False
        if ecu_cfg_dirty:
            send_ecu_config(CFG_MODE_APPLY)
        reset_confirm_armed = False
        trip_clear_confirm_armed = False
        ecu_commit_confirm_armed = False
        menu_active = False
    elif event == "UP":
        reset_confirm_armed = False
        trip_clear_confirm_armed = False
        ecu_commit_confirm_armed = False
        menu_index = (menu_index - 1) % settings_count()
    elif event == "DOWN":
        reset_confirm_armed = False
        trip_clear_confirm_armed = False
        ecu_commit_confirm_armed = False
        menu_index = (menu_index + 1) % settings_count()
    elif event == "LEFT":
        if menu_index < 14:
            adjust_setting(menu_index, -1)
        else:
            reset_confirm_armed = False
            trip_clear_confirm_armed = False
            ecu_commit_confirm_armed = False
    elif event == "RIGHT":
        if menu_index < 14:
            adjust_setting(menu_index, 1)
        else:
            reset_confirm_armed = False
            trip_clear_confirm_armed = False
            ecu_commit_confirm_armed = False


def draw_settings_menu():
    global menu_scroll_x, menu_scroll_last_ms

    oled.fill(0)
    oled.text("SETTINGS", 28, 0, 1)

    first = menu_index - 1
    if first < 0:
        first = 0
    if first > settings_count() - 3:
        first = settings_count() - 3
    if first < 0:
        first = 0

    y_rows = (14, 26, 38)
    for row in range(3):
        idx = first + row
        y = y_rows[row]
        if idx >= settings_count():
            continue

        if idx == 0:
            label = "DBNC " + str(rpm_debounce_us)
        elif idx == 1:
            label = "RPPR " + str(rpm_pulses_per_rev)
        elif idx == 2:
            label = "WHL  " + str(wheel_size_mm) + "mm"
        elif idx == 3:
            label = "SPPR " + str(speed_pulses_per_rev)
        elif idx == 4:
            label = "RBAR " + str(rpm_bar_max)
        elif idx == 5:
            label = "DBG  " + ("ON" if debug_overlay_enabled else "OFF")
        elif idx == 6:
            label = "DEMO " + ("ON" if demo_mode_enabled else "OFF")
        elif idx == 7:
            label = "ECTH " + str(ecu_teeth_per_rev)
        elif idx == 8:
            label = "ESYN " + str(ecu_sync_tooth_index)
        elif idx == 9:
            label = "EMIN " + str(ecu_tooth_min_us)
        elif idx == 10:
            label = "EMAX " + str(ecu_tooth_max_us)
        elif idx == 11:
            label = "ESFD " + str(ecu_safe_fire_delay_us)
        elif idx == 12:
            label = "ESDW " + str(ecu_safe_dwell_us)
        elif idx == 13:
            label = "EMTR " + str(ecu_missing_tooth_ratio_x10 // 10) + "." + str(ecu_missing_tooth_ratio_x10 % 10)
        elif idx == 14:
            if ecu_cfg_dirty:
                label = "TMAP edited"
            else:
                label = "TMAP clean"
        elif idx == 15:
            if ecu_commit_confirm_armed:
                label = "ECMT confirm?"
            else:
                label = "ECMT " + ecu_cfg_last_status[-11:]
        elif idx == 16:
            if reset_confirm_armed:
                label = "RSET confirm?"
            else:
                label = "RSET defaults"
        elif idx == 17:
            label = "TRIP " + str(trip_mm // 1000000) + "." + str((trip_mm // 100000) % 10) + "km"
        else:
            if trip_clear_confirm_armed:
                label = "TCLR confirm?"
            else:
                label = "TCLR clear trip"

        mark = ">" if idx == menu_index else " "
        oled.text(mark + label, 0, y, 1)

    now = utime.ticks_ms()
    help_text = MENU_HELP_TEXT
    if menu_index == 14:
        help_text = "TMAP: OK open  U/D point  L/R adv"
    elif menu_index == 15:
        if ecu_commit_confirm_armed:
            help_text = "ECMT: OK confirm  U/D cancel"
        else:
            help_text = "ECU cfg: OK arm commit"
    elif menu_index == 16:
        if reset_confirm_armed:
            help_text = MENU_HELP_RESET_CONFIRM
        else:
            help_text = MENU_HELP_RESET_ARM
    elif menu_index == 18:
        if trip_clear_confirm_armed:
            help_text = MENU_HELP_TCLR_CONFIRM
        else:
            help_text = MENU_HELP_TCLR_ARM

    if utime.ticks_diff(now, menu_scroll_last_ms) >= MENU_SCROLL_STEP_MS:
        menu_scroll_last_ms = now
        menu_scroll_x -= 1
        text_px = len(help_text) * 8
        if menu_scroll_x < -text_px:
            menu_scroll_x = 128
    oled.text(help_text, menu_scroll_x, 56, 1)


def draw_info_screen():
    oled.fill(0)
    oled.text("INFO " + get_sensor_status_text(), 0, 0, 1)
    oled.text("ODO " + format_odo_text(odo_mm), 0, 14, 1)
    oled.text(format_trip_text(trip_mm) + " KM", 0, 26, 1)

    ign_mode = get_display_ignition_mode()
    sync_state = get_display_sync_state()
    faults = get_display_faults()

    if ign_mode < 0:
        ign_txt = "--"
    elif ign_mode == 0:
        ign_txt = "INH"
    elif ign_mode == 1:
        ign_txt = "SAFE"
    else:
        ign_txt = "PREC"

    if sync_state < 0:
        sync_txt = "--"
    elif sync_state == 0:
        sync_txt = "LOST"
    elif sync_state == 1:
        sync_txt = "SYNC"
    else:
        sync_txt = "LOCK"

    oled.text("IG " + ign_txt + " " + sync_txt, 0, 38, 1)
    oled.text("FLT " + hex(faults & 0xFFFF), 0, 50, 1)


def draw_fault_log_screen():
    global flog_index

    oled.fill(0)
    entries, ecu_time_ms = engine_adapter.get_fault_log()
    total = len(entries)

    if total == 0:
        oled.text("FLOG CLEAR", 24, 28, 1)
        oled.text("L info  R graph", 0, 56, 1)
        return

    # Clamp index into range whenever the log shrinks (e.g. after an ECU
    # reboot drops entries).
    if flog_index >= total:
        flog_index = total - 1
    if flog_index < 0:
        flog_index = 0

    bit, rpm_at, tooth_at, _avg_at, ts_at, count = entries[flog_index]

    oled.text("FLOG " + str(flog_index + 1) + "/" + str(total), 0, 0, 1)
    oled.text(fault_short_name(bit), 0, 12, 1)
    oled.text(fault_long_name(bit), 0, 22, 1)
    oled.text("R" + str(rpm_at) + " TP" + str(tooth_at), 0, 34, 1)

    age_ms = utime.ticks_diff(ecu_time_ms & 0xFFFFFFFF, ts_at & 0xFFFFFFFF)
    if age_ms < 0:
        age_ms = 0
    age_s = age_ms // 1000
    if age_s > 99999:
        age_s = 99999
    oled.text("N" + str(count) + " T-" + str(age_s) + "s", 0, 44, 1)
    oled.text("L<-  R->  OK exit", 0, 56, 1)


def draw_timing_map_editor():
    oled.fill(0)
    count = len(ecu_adv_map_cd)
    idx = map_point_index
    rpm = ecu_adv_map_rpm[idx]
    adv_cd = ecu_adv_map_cd[idx]

    oled.text("TMAP " + str(idx + 1) + "/" + str(count), 0, 0, 1)
    oled.text("RPM " + str(rpm), 0, 10, 1)
    oled.text("ADV " + format_cd_text(adv_cd) + "d", 0, 20, 1)

    gx = 0
    gy = 33
    gw = 128
    gh = 22
    min_cd = TIMING_MAP_ADV_MIN_CD
    max_cd = TIMING_MAP_ADV_MAX_CD
    span_cd = max_cd - min_cd
    if span_cd <= 0:
        span_cd = 1

    prev_valid = False
    prev_x = 0
    prev_y = 0
    for i in range(count):
        x = gx + ((i * (gw - 1)) // (count - 1))
        v = ecu_adv_map_cd[i]
        y = gy + gh - 1 - (((v - min_cd) * (gh - 1)) // span_cd)
        if y < gy:
            y = gy
        elif y > gy + gh - 1:
            y = gy + gh - 1
        if prev_valid:
            oled.line(prev_x, prev_y, x, y, 1)
        prev_x = x
        prev_y = y
        prev_valid = True

    sx = gx + ((idx * (gw - 1)) // (count - 1))
    sy = gy + gh - 1 - (((adv_cd - min_cd) * (gh - 1)) // span_cd)
    if sy < gy:
        sy = gy
    elif sy > gy + gh - 1:
        sy = gy + gh - 1
    oled.fill_rect(sx - 1, sy - 1, 3, 3, 1)

    oled.text("U/D pt L/R adv OK", 0, 56, 1)


# -----------------------------
# UI helpers
# -----------------------------
def draw_big_digit(oled_obj, digit, x, y):
    width = BIG_DIGIT_W
    height = BIG_DIGIT_H
    thick = BIG_DIGIT_THICK
    gap = BIG_DIGIT_GAP
    half = height // 2

    segments = {
        0: (1, 1, 1, 1, 1, 1, 0),
        1: (0, 1, 1, 0, 0, 0, 0),
        2: (1, 1, 0, 1, 1, 0, 1),
        3: (1, 1, 1, 1, 0, 0, 1),
        4: (0, 1, 1, 0, 0, 1, 1),
        5: (1, 0, 1, 1, 0, 1, 1),
        6: (1, 0, 1, 1, 1, 1, 1),
        7: (1, 1, 1, 0, 0, 0, 0),
        8: (1, 1, 1, 1, 1, 1, 1),
        9: (1, 1, 1, 1, 0, 1, 1),
    }

    a, b, c, d, e, f, g = segments.get(digit, (0, 0, 0, 0, 0, 0, 0))

    if a:
        oled_obj.fill_rect(x + gap, y, width - (gap * 2), thick, 1)
    if b:
        oled_obj.fill_rect(x + width - thick, y + gap, thick, half - gap - 1, 1)
    if c:
        oled_obj.fill_rect(x + width - thick, y + half + 1, thick, half - gap - 1, 1)
    if d:
        oled_obj.fill_rect(x + gap, y + height - thick, width - (gap * 2), thick, 1)
    if e:
        oled_obj.fill_rect(x, y + half + 1, thick, half - gap - 1, 1)
    if f:
        oled_obj.fill_rect(x, y + gap, thick, half - gap - 1, 1)
    if g:
        oled_obj.fill_rect(x + gap, y + half - (thick // 2), width - (gap * 2), thick, 1)


def draw_speed_big(oled_obj, speed_value):
    y = SPEED_TEXT_Y

    if speed_value < 0:
        text = "---"
        x = (128 - (len(text) * 8)) // 2
        oled_obj.text(text, x, y + 8, 1)
        return x, len(text) * 8, y

    text = str(speed_value)
    if len(text) > 3:
        text = text[-3:]

    digit_spacing = BIG_DIGIT_SPACING
    digit_width = BIG_DIGIT_W
    total_w = (len(text) * digit_width) + ((len(text) - 1) * digit_spacing)
    x = (128 - total_w) // 2

    for ch in text:
        draw_big_digit(oled_obj, ord(ch) - 48, x, y)
        x += digit_width + digit_spacing

    return (128 - total_w) // 2, total_w, y


def _pulse_oled_reset_pin():
    if OLED_RESET_PIN < 0:
        return False
    try:
        rst = Pin(OLED_RESET_PIN, Pin.OUT)
        rst.value(1)
        utime.sleep_ms(1)
        rst.value(0)
        utime.sleep_ms(12)
        rst.value(1)
        utime.sleep_ms(20)
        return True
    except Exception:
        return False


def _recover_i2c_lines():
    try:
        scl = Pin(I2C_SCL, Pin.OUT)
        sda = Pin(I2C_SDA, Pin.OUT)
        sda.value(1)
        scl.value(1)
        utime.sleep_us(10)
        for _ in range(18):
            scl.value(0)
            utime.sleep_us(10)
            scl.value(1)
            utime.sleep_us(10)
        sda.value(0)
        utime.sleep_us(10)
        scl.value(1)
        utime.sleep_us(10)
        sda.value(1)
        utime.sleep_us(10)
        return True
    except Exception:
        return False


def reset_oled(bus_recovery=True):
    global i2c, oled

    if "i2c" in globals():
        try:
            deinit_fn = getattr(i2c, "deinit", None)
            if deinit_fn is not None:
                deinit_fn()
        except Exception:
            pass

    if bus_recovery:
        _recover_i2c_lines()

    _pulse_oled_reset_pin()

    try:
        i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=I2C_FREQ)
        oled = SSD1306(128, 64, i2c, OLED_ADDR, OLED_DRIVER)
        oled.fill(0)
        return oled.show()
    except Exception:
        return False


def recover_oled():
    global display_last_recover_ms
    now = utime.ticks_ms()
    if utime.ticks_diff(now, display_last_recover_ms) < 150:
        return False

    display_last_recover_ms = now
    return reset_oled(True)


def build_ecu_config_payload():
    return {
        # Compact keys keep config JSON under single-TLV 255-byte limit.
        "tpr": ecu_teeth_per_rev,
        "sti": ecu_sync_tooth_index,
        "tmin": ecu_tooth_min_us,
        "tmax": ecu_tooth_max_us,
        "sfd": ecu_safe_fire_delay_us,
        "sdw": ecu_safe_dwell_us,
        # mtr is sent as a float; ECU sanitize_profile clamps to 1.2..3.0.
        "mtr": ecu_missing_tooth_ratio_x10 / 10.0,
        "amc": ecu_adv_map_cd,
    }


def flush_pending_config_tx():
    global config_tx_pending, config_tx_offset, config_tx_seq
    global config_tx_started_ms, config_tx_last_progress_ms, config_tx_next_try_ms
    global ecu_cfg_last_status

    if config_tx_pending is None:
        return True
    now = utime.ticks_ms()

    if utime.ticks_diff(now, config_tx_next_try_ms) < 0:
        return False

    if utime.ticks_diff(now, config_tx_last_progress_ms) > CFG_TX_STALL_MS:
        config_tx_pending = None
        config_tx_offset = 0
        config_tx_started_ms = 0
        config_tx_last_progress_ms = 0
        config_tx_next_try_ms = 0
        ecu_cfg_last_status = "CFG timeout"
        return False

    if telemetry_uart is None:
        return False

    remaining = len(config_tx_pending) - config_tx_offset
    send_len = CFG_TX_CHUNK_MAX
    if remaining < send_len:
        send_len = remaining

    try:
        n = telemetry_uart.write(memoryview(config_tx_pending)[config_tx_offset:config_tx_offset + send_len])
    except Exception:
        n = 0
    if n is None:
        n = 0
    if n <= 0:
        config_tx_next_try_ms = utime.ticks_add(now, CFG_TX_RETRY_MS)
        return False

    config_tx_last_progress_ms = now
    config_tx_next_try_ms = utime.ticks_add(now, CFG_TX_RETRY_MS)
    config_tx_offset += n
    if config_tx_offset < len(config_tx_pending):
        return False

    config_tx_pending = None
    config_tx_offset = 0
    config_tx_started_ms = 0
    config_tx_last_progress_ms = 0
    config_tx_next_try_ms = 0
    config_tx_seq = (config_tx_seq + 1) & 0xFFFF
    ecu_cfg_last_status = "CFG sent"
    return True


def send_ecu_config(mode):
    global config_tx_pending, config_tx_offset, ecu_cfg_last_status
    global config_tx_started_ms, config_tx_last_progress_ms, config_tx_next_try_ms

    if telemetry_uart is None:
        ecu_cfg_last_status = "CFG no UART"
        return False

    if config_tx_pending is not None:
        ecu_cfg_last_status = "CFG busy"
        return False

    cfg_json = ujson.dumps(build_ecu_config_payload(), separators=(",", ":"))
    if len(cfg_json) > 255:
        ecu_cfg_last_status = "CFG too big"
        return False
    payload = bytearray()
    tlv_u8(payload, TLV_CFG_MODE_U8, mode)
    tlv_bytes(payload, TLV_CFG_JSON, cfg_json.encode("utf-8"))

    header = bytearray()
    header.append(PROTO_MAJOR)
    header.append(PROTO_MINOR)
    header.append(MSG_TYPE_CONFIG_SET)
    put_u16_le(header, config_tx_seq)
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

    config_tx_pending = frame
    config_tx_offset = 0
    now = utime.ticks_ms()
    config_tx_started_ms = now
    config_tx_last_progress_ms = now
    config_tx_next_try_ms = now
    if flush_pending_config_tx():
        ecu_cfg_last_status = "CFG sent"
    else:
        ecu_cfg_last_status = "CFG queued"
    return True


def show_oled_safe():
    global oled_consecutive_fails
    try:
        ok = oled.show()
        if ok:
            oled_consecutive_fails = 0
            return True
        oled_consecutive_fails += 1
    except Exception:
        oled_consecutive_fails += 1
    if oled_consecutive_fails >= OLED_FAIL_RECOVER_THRESHOLD:
        oled_consecutive_fails = 0
        recover_oled()
    return False


def update_display():
    if graph_active:
        draw_history_graph(graph_channel)
        show_oled_safe()
        return

    if map_editor_active:
        draw_timing_map_editor()
        show_oled_safe()
        return

    if flog_active:
        draw_fault_log_screen()
        show_oled_safe()
        return

    if info_active:
        draw_info_screen()
        show_oled_safe()
        return

    if menu_active:
        draw_settings_menu()
        show_oled_safe()
        return

    rpm_now = get_display_rpm()
    speed_now = get_display_speed()
    temp_now = get_display_temp()

    oled.fill(0)

    # Top: RPM bar
    bar_x = RPM_BAR_X
    bar_y = RPM_BAR_Y
    bar_w = RPM_BAR_W
    bar_h = RPM_BAR_H

    if rpm_now < 0:
        fill_w = 0
    else:
        fill_w = int((rpm_now * (bar_w - 2)) / rpm_bar_max)
        if fill_w < 0:
            fill_w = 0
        elif fill_w > (bar_w - 2):
            fill_w = bar_w - 2

    oled.rect(bar_x, bar_y, bar_w, bar_h, 1)
    oled.fill_rect(bar_x + 1, bar_y + 1, fill_w, bar_h - 2, 1)

    # RPM bar tick marks
    tick_y = bar_y + RPM_TICK_Y_OFFSET
    for i in range(RPM_TICK_COUNT + 1):
        tick_x = bar_x + int((i * (bar_w - 1)) / RPM_TICK_COUNT)
        oled.vline(tick_x, tick_y, RPM_TICK_H, 1)

        tick_value = (i * rpm_bar_max) // RPM_TICK_COUNT
        tick_label = str(tick_value // 1000)
        label_x = tick_x - (len(tick_label) * 4)
        if label_x < 0:
            label_x = 0
        max_x = 128 - (len(tick_label) * 8)
        if label_x > max_x:
            label_x = max_x
        oled.text(tick_label, label_x, RPM_SCALE_LABEL_Y, 1)

    # RPM number centered, label on right
    if rpm_now < 0:
        rpm_num = "----"
    else:
        rpm_num = "{:04d}".format(rpm_now)

    rpm_num_x = (128 - (len(rpm_num) * 8)) // 2 + RPM_NUMBER_OFFSET
    oled.text(rpm_num, rpm_num_x, RPM_TEXT_Y, 1)

    rpm_label_x = rpm_num_x + (len(rpm_num) * 8) + RPM_LABEL_GAP + RPM_LABEL_OFFSET
    if rpm_label_x > 128 - 24:
        rpm_label_x = 128 - 24
    oled.text("RPM", rpm_label_x, RPM_TEXT_Y, 1)

    # Center: big speed digits
    speed_x, speed_w, speed_y = draw_speed_big(oled, speed_now)
    kmh_x = speed_x + speed_w + KMH_GAP_X
    kmh_y = speed_y + KMH_Y_OFFSET
    if kmh_x > 128 - (len(KMH_TEXT) * 8):
        kmh_x = 128 - (len(KMH_TEXT) * 8)
    oled.text(KMH_TEXT, kmh_x, kmh_y, 1)

    # Bottom-left: live commanded ignition advance. The dash recomputes the
    # ECU's commanded advance locally by interpolating the cached advance
    # map at the current RPM (no extra TLV on the wire). Odometer is still
    # persisted (trip_mm/odo_mm) and shown on the info screen; it has just
    # been moved off the main screen.
    ign_mode = get_display_ignition_mode()
    if ign_mode == IGN_MODE_INHIBIT:
        adv_text = "INH*"
    elif ign_mode == IGN_MODE_SAFE:
        adv_text = "SAF*"
    else:
        rpm_for_adv = get_display_rpm()
        if rpm_for_adv < 0:
            adv_text = "--.-*"
        else:
            adv_cd = _interp_map(rpm_for_adv, ecu_adv_map_rpm, ecu_adv_map_cd)
            adv_text = format_cd_text(adv_cd) + "*"
    oled.text(adv_text, 0, TEMP_TEXT_Y, 1)

    # Bottom-right: temp from adapter
    temp_text = format_temp_text(temp_now)
    temp_x = 128 - (len(temp_text) * 8)
    if temp_x < 0:
        temp_x = 0
    oled.text(temp_text, temp_x, TEMP_TEXT_Y, 1)

    # ECU live indicator / link status badge
    draw_ecu_link_badge()

    if debug_overlay_enabled:
        dbg_text = "D" + str(debug_loop_ms)
        dbg_x = 128 - (len(dbg_text) * 8)
        if dbg_x < 0:
            dbg_x = 0
        oled.text(dbg_text, dbg_x, 8, 1)

    show_oled_safe()


# -----------------------------
# Legacy sensor update (optional)
# -----------------------------
def update_sensors_legacy():
    global legacy_temp, legacy_temp_diag, temp_last_read_ms

    if demo_mode_enabled:
        return

    now = utime.ticks_ms()
    if utime.ticks_diff(now, temp_last_read_ms) < TEMP_READ_INTERVAL_MS:
        return

    temp_last_read_ms = now
    try:
        legacy_temp, legacy_temp_diag = thermocouple.read_temp_with_diag()
    except Exception:
        legacy_temp = None
        legacy_temp_diag = "RAW EXC"


# -----------------------------
# Hardware init
# -----------------------------
def init_hardware():
    global i2c, oled, spi, thermocouple

    i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=I2C_FREQ)
    oled = SSD1306(128, 64, i2c, OLED_ADDR, OLED_DRIVER)

    spi = SPI(
        SPI_ID,
        baudrate=4000000,
        polarity=0,
        phase=0,
        sck=Pin(SPI_SCK),
        mosi=Pin(SPI_MOSI),
        miso=Pin(SPI_MISO),
    )
    thermocouple = MAX6675(spi, SPI_CS)


def init_buttons_and_inputs():
    global btn_up, btn_down, btn_left, btn_right, btn_ok
    global rpm_pin, spd_pin

    btn_up = Pin(BTN_UP_PIN, Pin.IN, Pin.PULL_UP)
    btn_down = Pin(BTN_DOWN_PIN, Pin.IN, Pin.PULL_UP)
    btn_left = Pin(BTN_LEFT_PIN, Pin.IN, Pin.PULL_UP)
    btn_right = Pin(BTN_RIGHT_PIN, Pin.IN, Pin.PULL_UP)
    btn_ok = Pin(BTN_OK_PIN, Pin.IN, Pin.PULL_UP)

    load_settings()

    spd_pin = Pin(SPD_PIN, Pin.IN, Pin.PULL_DOWN)
    spd_pin.irq(trigger=Pin.IRQ_RISING, handler=spd_interrupt)

    if LEGACY_LOCAL_ENGINE_ENABLE:
        rpm_pin = Pin(RPM_PIN, Pin.IN, Pin.PULL_DOWN)
        try:
            rpm_pin.irq(trigger=Pin.IRQ_RISING, handler=rpm_interrupt, hard=True)
        except TypeError:
            rpm_pin.irq(trigger=Pin.IRQ_RISING, handler=rpm_interrupt)


def init_telemetry_ingest():
    global telemetry_uart, telemetry_ingest, engine_adapter

    try:
        telemetry_uart = UART(UART_ID, baudrate=UART_BAUD, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN), txbuf=128, rxbuf=512, timeout=0, timeout_char=0)
    except TypeError:
        telemetry_uart = UART(UART_ID, baudrate=UART_BAUD, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))
    telemetry_ingest = TelemetryIngest(telemetry_uart)
    engine_adapter = EngineSnapshotAdapter(telemetry_ingest)


def _new_timer(preferred_id):
    candidates = (preferred_id, 0, -1, 1, 2, 3)
    last_err = None
    for tid in candidates:
        try:
            return Timer(tid)
        except (TypeError, ValueError) as err:
            last_err = err
    if last_err is not None:
        raise last_err
    raise RuntimeError("No timer available")


def init_timers():
    global rpm_timer

    if LEGACY_LOCAL_ENGINE_ENABLE:
        rpm_timer = _new_timer(0)
        rpm_timer.init(freq=RPM_UPDATE_HZ, callback=update_rpm_legacy)


# -----------------------------
# Main loop
# -----------------------------
def run_dashboard_loop():
    global debug_loop_ms, display_last_draw_ms, gc_last_ms

    while True:
        loop_start_us = utime.ticks_us()
        now_ms = utime.ticks_ms()

        flush_pending_config_tx()

        if not LEGACY_LOCAL_ENGINE_ENABLE:
            if not demo_mode_enabled:
                telemetry_ingest.poll()
            engine_adapter.update_link_state()

        handle_buttons()
        update_runtime()

        if demo_mode_enabled:
            update_demo_values()

        # Speed sensor: process pulses every loop iteration so accumulated ticks
        # never spike after the user sits in the menu. Internal elapsed-time
        # guard makes fast successive calls cheap.
        if not demo_mode_enabled:
            update_speed_legacy()

        display_ready = utime.ticks_diff(now_ms, display_last_draw_ms) >= DISPLAY_PERIOD_MS
        if display_ready:
            display_last_draw_ms = now_ms

            if demo_mode_enabled and (not info_active) and (not menu_active):
                update_distance_from_telemetry_speed()

            update_display()

            if not (graph_active and graph_paused):
                update_history_samples()

        if not demo_mode_enabled:
            update_sensors_legacy()

        maybe_save_persistent_state()

        # Deterministic GC: run once per second at a safe moment (just after draw,
        # with no pending config TX and no save churn). Keeps pauses predictable.
        if (utime.ticks_diff(now_ms, gc_last_ms) >= GC_INTERVAL_MS
                and config_tx_pending is None
                and not settings_dirty):
            gc_last_ms = now_ms
            gc.collect()

        debug_loop_ms = utime.ticks_diff(utime.ticks_us(), loop_start_us) // 1000
        utime.sleep_ms(MAIN_LOOP_SLEEP_MS)


def stop_dashboard():
    try:
        if LEGACY_LOCAL_ENGINE_ENABLE:
            rpm_timer.deinit()
    except Exception:
        pass

    try:
        oled.fill(0)
        show_oled_safe()
    except Exception:
        pass


def start_dashboard():
    init_hardware()
    init_buttons_and_inputs()
    init_telemetry_ingest()
    init_timers()
    print("Dash started (ECU telemetry mode)")

    try:
        run_dashboard_loop()
    except KeyboardInterrupt:
        stop_dashboard()
        print("Dash stopped")


start_dashboard()
