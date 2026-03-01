from machine import Pin, I2C, SPI, Timer
from micropython import const
import utime

# Display setup
I2C_ID = 0
I2C_SDA = 0
I2C_SCL = 1
I2C_FREQ = 400000

# SPI setup for MAX6675
SPI_ID = 0
SPI_SCK = 18
SPI_MOSI = 19
SPI_MISO = 16
SPI_CS = 17

# Sensor pins
RPM_PIN = 2
SPD_PIN = 3

# Display address
OLED_ADDR = 0x3C

# Simple SSD1306 driver
class SSD1306:
    def __init__(self, i2c, addr=0x3C):
        self.i2c = i2c
        self.addr = addr
        self.width = 128
        self.height = 64
        self.pages = 8
        self.buffer = bytearray(self.width * self.pages)
        self._init_display()
    
    def _init_display(self):
        cmds = [
            0xAE,  # display off
            0xD5, 0x80,  # set clock div
            0xA8, 0x3F,  # set height
            0xD3, 0x00,  # set offset
            0x40,  # set start line
            0x8D, 0x14,  # charge pump
            0x20, 0x00,  # memory mode
            0xA1,  # seg remap
            0xC8,  # com scan direction
            0xDA, 0x12,  # com pins
            0x81, 0xCF,  # contrast
            0xD9, 0xF1,  # precharge
            0xDB, 0x40,  # vcomh
            0xA4,  # normal display
            0xA6,  # not inverted
            0xAF   # display on
        ]
        for cmd in cmds:
            self.i2c.writeto(self.addr, bytes([0x00, cmd]))
    
    def clear(self):
        self.buffer[:] = bytearray(len(self.buffer))
    
    def text(self, s, x, y, color=1):
        for i, c in enumerate(s):
            self._char(c, x + i * 8, y, color)
    
    def _char(self, c, x, y, color):
        if x + 8 > self.width or y + 8 > self.height:
            return
        
        char_index = ord(c) - 32
        if char_index < 0 or char_index >= 95:
            return
        
        char_data = _FONT[char_index]
        page = y // 8
        offset = y % 8
        
        for i in range(8):
            byte_val = char_data[i]
            
            if offset == 0:
                self.buffer[page * self.width + x + i] = byte_val
            else:
                idx = page * self.width + x + i
                if idx < len(self.buffer):
                    self.buffer[idx] |= byte_val << offset
                if page + 1 < self.pages:
                    self.buffer[(page + 1) * self.width + x + i] |= byte_val >> (8 - offset)
    
    def show(self):
        for page in range(self.pages):
            self.i2c.writeto(self.addr, bytes([0x00, 0xB0 | page, 0x00, 0x10]))
            self.i2c.writeto(self.addr, bytes([0x40]) + self.buffer[page * self.width:(page + 1) * self.width])

# Minimal 5x7 font for numbers and text
_FONT = [
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # space
    b'\xf8\x04\xf4\x04\xf8\x00\x00\x00',  # !
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # "
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # #
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # $
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # %
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # &
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # '
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # (
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # )
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # *
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # +
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # ,
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # -
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # .
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # /
    b'\x3e\x41\x41\x41\x41\x41\x41\x3e',  # 0
    b'\x00\x42\x7f\x40\x00\x00\x00\x00',  # 1
    b'\x62\x51\x49\x49\x49\x49\x49\x46',  # 2
    b'\x22\x41\x49\x49\x49\x49\x49\x36',  # 3
    b'\x18\x14\x12\x11\x7f\x10\x10\x00',  # 4
    b'\x27\x45\x45\x45\x45\x45\x45\x39',  # 5
    b'\x3c\x4a\x49\x49\x49\x49\x49\x32',  # 6
    b'\x01\x71\x09\x09\x09\x09\x09\x06',  # 7
    b'\x36\x49\x49\x49\x49\x49\x49\x36',  # 8
    b'\x26\x49\x49\x49\x49\x49\x49\x3e',  # 9
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # :
    b'\x00\x00\x00\x00\x00\x00\x00\x00',  # ;
    b'\x08\x14\x22\x41\x00\x00\x00\x00',  # <
    b'\x14\x14\x14\x14\x14\x14\x14\x00',  # =
    b'\x41\x22\x14\x08\x00\x00\x00\x00',  # >
    b'\x02\x01\x59\x09\x09\x09\x09\x06',  # ?
    b'\x3e\x41\x4d\x55\x55\x55\x41\x3e',  # @
    b'\x7e\x11\x11\x11\x11\x11\x11\x7e',  # A
    b'\x7f\x49\x49\x49\x49\x49\x49\x36',  # B
    b'\x3e\x41\x41\x41\x41\x41\x41\x22',  # C
    b'\x7f\x41\x41\x41\x41\x41\x41\x3e',  # D
    b'\x7f\x49\x49\x49\x49\x49\x49\x49',  # E
    b'\x7f\x09\x09\x09\x09\x09\x09\x01',  # F
    b'\x3e\x41\x41\x49\x49\x49\x49\x32',  # G
    b'\x7f\x08\x08\x08\x08\x08\x08\x7f',  # H
    b'\x00\x41\x7f\x41\x00\x00\x00\x00',  # I
    b'\x20\x40\x41\x41\x41\x41\x3f\x01',  # J
    b'\x7f\x08\x14\x22\x41\x00\x00\x00',  # K
    b'\x7f\x40\x40\x40\x40\x40\x40\x40',  # L
    b'\x7f\x02\x04\x08\x04\x02\x7f\x00',  # M
    b'\x7f\x04\x08\x10\x20\x40\x7f\x00',  # N
    b'\x3e\x41\x41\x41\x41\x41\x41\x3e',  # O
    b'\x7f\x09\x09\x09\x09\x09\x09\x06',  # P
    b'\x3e\x41\x41\x41\x51\x21\x41\x5e',  # Q
    b'\x7f\x09\x09\x09\x19\x29\x49\x46',  # R
    b'\x26\x49\x49\x49\x49\x49\x49\x32',  # S
    b'\x01\x01\x01\x7f\x01\x01\x01\x00',  # T
    b'\x3f\x40\x40\x40\x40\x40\x40\x3f',  # U
    b'\x1f\x20\x40\x40\x40\x40\x20\x1f',  # V
    b'\x3f\x40\x20\x10\x20\x40\x3f\x00',  # W
    b'\x63\x14\x08\x08\x08\x14\x63\x00',  # X
    b'\x07\x08\x08\x70\x08\x08\x07\x00',  # Y
    b'\x71\x49\x49\x49\x49\x49\x49\x47',  # Z
    b'\x00\x7f\x41\x41\x00\x00\x00\x00',  # [
    b'\x02\x04\x08\x10\x20\x40\x00\x00',  # \
    b'\x00\x41\x41\x7f\x00\x00\x00\x00',  # ]
    b'\x04\x02\x01\x02\x04\x00\x00\x00',  # ^
    b'\x40\x40\x40\x40\x40\x40\x40\x40',  # _
]

# MAX6675 thermocouple reader
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
        
        value = (raw[0] << 8) | raw[1]
        temp = (value >> 3) & 0x1FFF
        return temp * 0.25

# Sensor state
rpm_ticks = 0
rpm_last_time = utime.ticks_ms()
rpm_value = 0
spd_ticks = 0
spd_value = 0
temp = 0

def rpm_interrupt(pin):
    global rpm_ticks, rpm_last_time
    rpm_ticks += 1

def spd_interrupt(pin):
    global spd_ticks
    spd_ticks += 1

def update_rpm(timer):
    global rpm_value, rpm_ticks, rpm_last_time
    
    current_time = utime.ticks_ms()
    elapsed = utime.ticks_diff(current_time, rpm_last_time)
    
    if elapsed > 0:
        # Calculate RPM: ticks per minute
        # Assuming 1 tick per combustion cycle (1 pulse per rotation for single-cyl)
        rpm_value = int((rpm_ticks * 60000) / elapsed)
    
    rpm_ticks = 0
    rpm_last_time = current_time

def update_display(timer):
    global spd_value, spd_ticks, temp
    
    # Speed: simple calculation based on pulses
    # Adjust multiplier based on your sensor setup
    spd_value = spd_ticks * 10
    spd_ticks = 0
    
    # Update display
    oled.clear()
    
    rpm_str = f"RPM: {rpm_value:04d}"
    spd_str = f"SPD: {spd_value:02d}"
    tmp_str = f"TMP: {int(temp):03d}C"
    
    oled.text(rpm_str, 0, 0)
    oled.text(spd_str, 0, 16)
    oled.text(tmp_str, 0, 32)
    
    oled.show()

# Initialize I2C and display
i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=I2C_FREQ)
oled = SSD1306(i2c, OLED_ADDR)
oled.clear()
oled.show()

# Initialize SPI and thermocouple
spi = SPI(SPI_ID, baudrate=4000000, polarity=0, phase=0, 
          sck=Pin(SPI_SCK), mosi=Pin(SPI_MOSI), miso=Pin(SPI_MISO))
thermocouple = MAX6675(spi, SPI_CS)

# Setup sensor interrupts
rpm_pin = Pin(RPM_PIN, Pin.IN, Pin.PULL_DOWN)
rpm_pin.irq(trigger=Pin.IRQ_RISING, handler=rpm_interrupt)

spd_pin = Pin(SPD_PIN, Pin.IN, Pin.PULL_DOWN)
spd_pin.irq(trigger=Pin.IRQ_RISING, handler=spd_interrupt)

# Timers
rpm_timer = Timer()
rpm_timer.init(freq=2, callback=update_rpm)  # Update RPM calc every 500ms

display_timer = Timer()
display_timer.init(freq=10, callback=update_display)  # 10 FPS display

print("Motorcycle dashboard started")

# Main loop
try:
    while True:
        temp = thermocouple.read_temp()
        utime.sleep(0.1)
except KeyboardInterrupt:
    rpm_timer.deinit()
    display_timer.deinit()
    oled.clear()
    oled.show()
    print("Dashboard stopped")
