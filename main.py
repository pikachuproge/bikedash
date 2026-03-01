from machine import Pin, I2C, SPI, Timer, disable_irq, enable_irq
from micropython import const
import framebuf
import utime
import ujson

# -----------------------------
# USER SETTINGS (edit here)
# -----------------------------

# Hardware pins and buses
I2C_ID = const(0)
I2C_SDA = const(0)
I2C_SCL = const(1)
I2C_FREQ = const(400000)
OLED_ADDR = const(0x3C)

SPI_ID = const(0)
SPI_SCK = const(18)
SPI_MOSI = const(19)
SPI_MISO = const(16)
SPI_CS = const(17)

RPM_PIN = const(2)
SPD_PIN = const(3)

# RPM tuning
RPM_PULSES_PER_REV = const(1)
RPM_DEBOUNCE_US = const(4000)
RPM_TIMEOUT_US = const(2000000)
RPM_PERIOD_RING_SIZE = const(7)
RPM_BAR_MAX = const(10000)

# Speed tuning
SPEED_MULTIPLIER = const(10)
WHEEL_SIZE_MM = const(2100)
SPEED_PULSES_PER_REV = const(1)

# Buttons (5 total)
BTN_UP_PIN = const(6)
BTN_DOWN_PIN = const(7)
BTN_LEFT_PIN = const(8)
BTN_RIGHT_PIN = const(9)
BTN_OK_PIN = const(10)
BTN_DEBOUNCE_MS = const(140)
OK_LONG_PRESS_MS = const(800)
MENU_SCROLL_STEP_MS = const(50)

# Display refresh and loop timing
RPM_UPDATE_HZ = const(20)
DISPLAY_UPDATE_HZ = const(10)
MAIN_LOOP_SLEEP_MS = const(20)
TRIP_SAVE_INTERVAL_MS = const(3000)

# UI layout
RPM_BAR_X = const(4)
RPM_BAR_Y = const(2)
RPM_BAR_W = const(120)
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
KMH_Y_OFFSET = const(8)
TEMP_FAULT_TEXT = "TC ERR"
TEMP_TEXT_X = const(104)
TEMP_TEXT_Y = const(56)


# -----------------------------
# SSD1306 (I2C)
# -----------------------------
class SSD1306(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        self._init_display()

    def _write_cmd(self, cmd):
        self.i2c.writeto(self.addr, bytes((0x00, cmd)))

    def _init_display(self):
        for cmd in (
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
        ):
            self._write_cmd(cmd)
        self.fill(0)
        self.show()

    def show(self):
        for page in range(self.pages):
            self._write_cmd(0xB0 | page)
            self._write_cmd(0x00)
            self._write_cmd(0x10)
            start = self.width * page
            end = start + self.width
            self.i2c.writeto(self.addr, b"\x40" + self.buffer[start:end])


# -----------------------------
# MAX6675
# -----------------------------
class MAX6675:
    def __init__(self, spi, cs_pin):
        self.spi = spi
        self.cs = Pin(cs_pin, Pin.OUT)
        self.cs.on()

    def read_temp(self):
        self.cs.off()
        utime.sleep_us(1)
        raw = self.spi.read(2)
        self.cs.on()

        if not raw or len(raw) != 2:
            return None

        value = (raw[0] << 8) | raw[1]
        if value & 0x0004:
            return None
        return ((value >> 3) & 0x0FFF) * 0.25


# -----------------------------
# Runtime state
# -----------------------------
rpm_last_pulse_us = 0
rpm_value = 0
rpm_period_us = [0] * RPM_PERIOD_RING_SIZE
rpm_period_head = 0
rpm_period_count = 0

spd_ticks = 0
spd_value = 0

temp = None
display_due = False

# Runtime-tunable values (editable from menu)
rpm_debounce_us = RPM_DEBOUNCE_US
rpm_pulses_per_rev = RPM_PULSES_PER_REV
wheel_size_mm = WHEEL_SIZE_MM
speed_pulses_per_rev = SPEED_PULSES_PER_REV
rpm_bar_max = RPM_BAR_MAX
speed_multiplier = SPEED_MULTIPLIER
speed_last_update_ms = utime.ticks_ms()

# Menu state
menu_active = False
info_active = False
menu_index = 0
last_btn_ms = 0
ok_press_start_ms = None
ok_long_fired = False
menu_scroll_x = 128
menu_scroll_last_ms = 0
MENU_HELP_TEXT = "U/D select  L/R adjust  OK exit"
MENU_HELP_RESET_ARM = "RSET: OK arm  U/D cancel"
MENU_HELP_RESET_CONFIRM = "RSET: OK confirm  U/D cancel"
MENU_HELP_TCLR_ARM = "TCLR: OK arm  U/D cancel"
MENU_HELP_TCLR_CONFIRM = "TCLR: OK confirm  U/D cancel"
SETTINGS_FILE = "dashboard_settings.json"
settings_dirty = False
reset_confirm_armed = False
trip_clear_confirm_armed = False
trip_mm = 0
odo_mm = 0
engine_runtime_s = 0
trip_dirty = False
odo_dirty = False
runtime_dirty = False
runtime_accum_ms = 0
runtime_last_ms = utime.ticks_ms()
persistent_last_save_ms = utime.ticks_ms()


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def load_settings():
    global rpm_debounce_us, rpm_pulses_per_rev
    global wheel_size_mm, speed_pulses_per_rev, rpm_bar_max, speed_multiplier
    global trip_mm, odo_mm, engine_runtime_s
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
    }
    try:
        with open(SETTINGS_FILE, "w") as f:
            ujson.dump(data, f)
        return True
    except Exception:
        return False


# -----------------------------
# Interrupt handlers
# -----------------------------
def rpm_interrupt(pin):
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
    global spd_ticks
    spd_ticks += 1


def display_tick(timer):
    global display_due
    display_due = True


# -----------------------------
# Calculations
# -----------------------------
def update_rpm(timer):
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


def get_rpm():
    if not rpm_last_pulse_us:
        return 0
    if utime.ticks_diff(utime.ticks_us(), rpm_last_pulse_us) >= RPM_TIMEOUT_US:
        return 0
    return rpm_value


def update_speed():
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
        dist_mm = (ticks * circ_mm) / speed_pulses_per_rev
        spd_value = int((dist_mm * 3.6) / elapsed_ms)

        dist_int = int(dist_mm + 0.5)
        if dist_int > 0:
            trip_mm += dist_int
            odo_mm += dist_int
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
    else:
        spd_value = ticks * speed_multiplier


def format_temp_text(temp_value):
    if temp_value is None:
        return TEMP_FAULT_TEXT
    if temp_value < -99 or temp_value > 999:
        return TEMP_FAULT_TEXT
    return str(int(temp_value + 0.5)) + "C"


def format_trip_text(mm_value):
    if mm_value < 0:
        mm_value = 0
    km10 = mm_value // 100000
    return "TR " + str(km10 // 10) + "." + str(km10 % 10)


def format_odo_text(mm_value):
    if mm_value < 0:
        mm_value = 0
    km = mm_value // 1000000
    if km >= 100:
        return str(km) + " KM"

    km10 = mm_value // 100000
    return str(km10 // 10) + "." + str(km10 % 10) + " KM"


def format_runtime_text(seconds):
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    return "RUN " + str(hours) + ":" + "{:02d}".format(mins) + ":" + "{:02d}".format(secs)


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

    now = utime.ticks_ms()
    if utime.ticks_diff(now, persistent_last_save_ms) < TRIP_SAVE_INTERVAL_MS:
        return

    if save_settings():
        trip_dirty = False
        odo_dirty = False
        runtime_dirty = False
        persistent_last_save_ms = now


def button_pressed(pin_obj):
    return pin_obj.value() == 0


def get_button_event():
    global last_btn_ms, ok_press_start_ms, ok_long_fired
    now = utime.ticks_ms()

    if button_pressed(btn_ok):
        if ok_press_start_ms is None:
            ok_press_start_ms = now
            ok_long_fired = False
        elif (not ok_long_fired) and utime.ticks_diff(now, ok_press_start_ms) >= OK_LONG_PRESS_MS:
            if utime.ticks_diff(now, last_btn_ms) >= BTN_DEBOUNCE_MS:
                last_btn_ms = now
                ok_long_fired = True
                return "OK_LONG"
    else:
        if ok_press_start_ms is not None:
            held_ms = utime.ticks_diff(now, ok_press_start_ms)
            was_long = ok_long_fired
            ok_press_start_ms = None
            ok_long_fired = False
            if (not was_long) and held_ms < OK_LONG_PRESS_MS and utime.ticks_diff(now, last_btn_ms) >= BTN_DEBOUNCE_MS:
                last_btn_ms = now
                return "OK"

    if utime.ticks_diff(now, last_btn_ms) < BTN_DEBOUNCE_MS:
        return None

    if button_pressed(btn_up):
        last_btn_ms = now
        return "UP"
    if button_pressed(btn_down):
        last_btn_ms = now
        return "DOWN"
    if button_pressed(btn_left):
        last_btn_ms = now
        return "LEFT"
    if button_pressed(btn_right):
        last_btn_ms = now
        return "RIGHT"
    return None


def settings_count():
    return 8


def reset_settings_to_defaults():
    global rpm_debounce_us, rpm_pulses_per_rev
    global wheel_size_mm, speed_pulses_per_rev, rpm_bar_max, speed_multiplier

    rpm_debounce_us = RPM_DEBOUNCE_US
    rpm_pulses_per_rev = RPM_PULSES_PER_REV
    wheel_size_mm = WHEEL_SIZE_MM
    speed_pulses_per_rev = SPEED_PULSES_PER_REV
    rpm_bar_max = RPM_BAR_MAX
    speed_multiplier = SPEED_MULTIPLIER


def clear_trip():
    global trip_mm, trip_dirty
    trip_mm = 0
    trip_dirty = True


def adjust_setting(index, delta):
    global settings_dirty
    global rpm_debounce_us, rpm_pulses_per_rev
    global wheel_size_mm, speed_pulses_per_rev, rpm_bar_max

    before = (rpm_debounce_us, rpm_pulses_per_rev, wheel_size_mm, speed_pulses_per_rev, rpm_bar_max)

    if index == 0:
        rpm_debounce_us += delta * 100
        if rpm_debounce_us < 2000:
            rpm_debounce_us = 2000
        elif rpm_debounce_us > 9000:
            rpm_debounce_us = 9000
    elif index == 1:
        rpm_pulses_per_rev += delta
        if rpm_pulses_per_rev < 1:
            rpm_pulses_per_rev = 1
        elif rpm_pulses_per_rev > 4:
            rpm_pulses_per_rev = 4
    elif index == 2:
        wheel_size_mm += delta * 10
        if wheel_size_mm < 1000:
            wheel_size_mm = 1000
        elif wheel_size_mm > 3000:
            wheel_size_mm = 3000
    elif index == 3:
        speed_pulses_per_rev += delta
        if speed_pulses_per_rev < 1:
            speed_pulses_per_rev = 1
        elif speed_pulses_per_rev > 20:
            speed_pulses_per_rev = 20
    elif index == 4:
        rpm_bar_max += delta * 500
        if rpm_bar_max < 4000:
            rpm_bar_max = 4000
        elif rpm_bar_max > 20000:
            rpm_bar_max = 20000

    after = (rpm_debounce_us, rpm_pulses_per_rev, wheel_size_mm, speed_pulses_per_rev, rpm_bar_max)
    if after != before:
        settings_dirty = True


def handle_buttons():
    global menu_active, info_active, menu_index
    global settings_dirty, reset_confirm_armed, trip_clear_confirm_armed
    global trip_dirty, odo_dirty, runtime_dirty
    event = get_button_event()
    if event is None:
        return

    if not menu_active and not info_active:
        if event == "OK":
            menu_active = True
            reset_confirm_armed = False
            trip_clear_confirm_armed = False
        elif event == "OK_LONG":
            info_active = True
        return

    if info_active:
        if event == "OK" or event == "OK_LONG":
            info_active = False
        return

    if event == "OK" and menu_index == 5:
        if not reset_confirm_armed:
            reset_confirm_armed = True
        else:
            reset_settings_to_defaults()
            if save_settings():
                settings_dirty = False
                trip_dirty = False
                odo_dirty = False
                runtime_dirty = False
            reset_confirm_armed = False
        return

    if event == "OK" and menu_index == 7:
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
        reset_confirm_armed = False
        trip_clear_confirm_armed = False
        menu_active = False
    elif event == "UP":
        reset_confirm_armed = False
        trip_clear_confirm_armed = False
        menu_index = (menu_index - 1) % settings_count()
    elif event == "DOWN":
        reset_confirm_armed = False
        trip_clear_confirm_armed = False
        menu_index = (menu_index + 1) % settings_count()
    elif event == "LEFT":
        if menu_index < 5:
            adjust_setting(menu_index, -1)
        else:
            reset_confirm_armed = False
            trip_clear_confirm_armed = False
    elif event == "RIGHT":
        if menu_index < 5:
            adjust_setting(menu_index, 1)
        else:
            reset_confirm_armed = False
            trip_clear_confirm_armed = False


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
            if reset_confirm_armed:
                label = "RSET confirm?"
            else:
                label = "RSET defaults"
        elif idx == 6:
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
    if menu_index == 5:
        if reset_confirm_armed:
            help_text = MENU_HELP_RESET_CONFIRM
        else:
            help_text = MENU_HELP_RESET_ARM
    elif menu_index == 7:
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
    oled.text("INFO", 48, 0, 1)
    oled.text("ODO " + format_odo_text(odo_mm), 0, 14, 1)
    oled.text(format_trip_text(trip_mm) + " KM", 0, 26, 1)
    oled.text(format_runtime_text(engine_runtime_s), 0, 38, 1)
    oled.text("TMP " + format_temp_text(temp), 0, 50, 1)


# -----------------------------
# UI helpers
# -----------------------------
def draw_big_digit(oled, digit, x, y):
    # 7-segment digit (cleaner proportions)
    width = BIG_DIGIT_W
    height = BIG_DIGIT_H
    thick = BIG_DIGIT_THICK
    gap = BIG_DIGIT_GAP
    half = height // 2

    # a, b, c, d, e, f, g
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
        oled.fill_rect(x + gap, y, width - (gap * 2), thick, 1)
    if b:
        oled.fill_rect(x + width - thick, y + gap, thick, half - gap - 1, 1)
    if c:
        oled.fill_rect(x + width - thick, y + half + 1, thick, half - gap - 1, 1)
    if d:
        oled.fill_rect(x + gap, y + height - thick, width - (gap * 2), thick, 1)
    if e:
        oled.fill_rect(x, y + half + 1, thick, half - gap - 1, 1)
    if f:
        oled.fill_rect(x, y + gap, thick, half - gap - 1, 1)
    if g:
        oled.fill_rect(x + gap, y + half - (thick // 2), width - (gap * 2), thick, 1)


def draw_speed_big(oled, speed_value):
    text = str(speed_value)
    if len(text) > 3:
        text = text[-3:]

    digit_spacing = BIG_DIGIT_SPACING
    digit_width = BIG_DIGIT_W
    total_w = (len(text) * digit_width) + ((len(text) - 1) * digit_spacing)
    x = (128 - total_w) // 2
    y = SPEED_TEXT_Y

    for ch in text:
        draw_big_digit(oled, ord(ch) - 48, x, y)
        x += digit_width + digit_spacing

    return (128 - total_w) // 2, total_w, y


def update_display():
    if info_active:
        draw_info_screen()
        oled.show()
        return

    if menu_active:
        draw_settings_menu()
        oled.show()
        return

    update_speed()
    rpm_now = get_rpm()

    oled.fill(0)

    # Top: RPM bar
    bar_x = RPM_BAR_X
    bar_y = RPM_BAR_Y
    bar_w = RPM_BAR_W
    bar_h = RPM_BAR_H
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

        # Tick labels in kRPM (0, 2, 4, ...)
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
    rpm_num = "{:04d}".format(rpm_now)
    rpm_num_x = (128 - (len(rpm_num) * 8)) // 2 + RPM_NUMBER_OFFSET
    oled.text(rpm_num, rpm_num_x, RPM_TEXT_Y, 1)

    rpm_label_x = rpm_num_x + (len(rpm_num) * 8) + RPM_LABEL_GAP + RPM_LABEL_OFFSET
    if rpm_label_x > 128 - 24:
        rpm_label_x = 128 - 24
    oled.text("RPM", rpm_label_x, RPM_TEXT_Y, 1)

    # Center: big speed digits
    speed_x, speed_w, speed_y = draw_speed_big(oled, spd_value)
    kmh_x = speed_x + speed_w + KMH_GAP_X
    kmh_y = speed_y + KMH_Y_OFFSET
    if kmh_x > 128 - (len(KMH_TEXT) * 8):
        kmh_x = 128 - (len(KMH_TEXT) * 8)
    oled.text(KMH_TEXT, kmh_x, kmh_y, 1)

    # Bottom-left: odometer
    oled.text(format_odo_text(odo_mm), 0, TEMP_TEXT_Y, 1)

    # Bottom-right: live temp (fault-safe)
    temp_text = format_temp_text(temp)
    temp_x = 128 - (len(temp_text) * 8)
    if temp_x < 0:
        temp_x = 0
    oled.text(temp_text, temp_x, TEMP_TEXT_Y, 1)

    oled.show()


# -----------------------------
# Hardware init
# -----------------------------
def init_hardware():
    global i2c, oled, spi, thermocouple

    i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=I2C_FREQ)
    oled = SSD1306(128, 64, i2c, OLED_ADDR)

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

    rpm_pin = Pin(RPM_PIN, Pin.IN, Pin.PULL_DOWN)
    rpm_pin.irq(trigger=Pin.IRQ_RISING, handler=rpm_interrupt)

    spd_pin = Pin(SPD_PIN, Pin.IN, Pin.PULL_DOWN)
    spd_pin.irq(trigger=Pin.IRQ_RISING, handler=spd_interrupt)


def init_timers():
    global rpm_timer, display_timer

    rpm_timer = Timer()
    rpm_timer.init(freq=RPM_UPDATE_HZ, callback=update_rpm)

    display_timer = Timer()
    display_timer.init(freq=DISPLAY_UPDATE_HZ, callback=display_tick)


def update_sensors():
    global temp
    try:
        temp = thermocouple.read_temp()
    except Exception:
        temp = None


def run_dashboard_loop():
    global display_due

    while True:
        handle_buttons()
        update_runtime()

        if display_due:
            display_due = False
            update_display()

        update_sensors()
        maybe_save_persistent_state()
        utime.sleep_ms(MAIN_LOOP_SLEEP_MS)


def stop_dashboard():
    rpm_timer.deinit()
    display_timer.deinit()
    oled.fill(0)
    oled.show()


def start_dashboard():
    init_hardware()
    init_buttons_and_inputs()
    init_timers()
    print("Motorcycle dashboard started")

    try:
        run_dashboard_loop()
    except KeyboardInterrupt:
        stop_dashboard()
        print("Dashboard stopped")


start_dashboard()
