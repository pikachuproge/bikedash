# Motorcycle Dashboard - Raspberry Pi Pico

A minimal MicroPython motorcycle telemetry dashboard for the Raspberry Pi Pico (RP2040) with an SSD1306 OLED display.

## Overview

**Version:** 0.1 (Phase 1)

Displays three real-time values on a 128x64 OLED screen:
- **RPM** - Engine revolutions per minute
- **SPD** - Vehicle speed in km/h
- **TMP** - Engine temperature in °C

Display format:
```
RPM: 0000
SPD: 00
TMP: 000C
```

## Hardware Requirements

### Microcontroller
- Raspberry Pi Pico (RP2040)

### Display
- SSD1306 128x64 OLED (0.96" diagonal)
- Connection: I2C interface
- Default I2C address: `0x3C`

### Sensors
- **RPM Sensor** - GPIO interrupt (rising edge pulses)
- **Speed Sensor** - GPIO interrupt (rising edge pulses)
- **Temperature Sensor** - MAX6675 K-type thermocouple reader
- Connection: SPI interface

## Pinout

| Component | Pin | GPIO |
|-----------|-----|------|
| OLED SDA | SDA | GP0 |
| OLED SCL | SCL | GP1 |
| MAX6675 SCK | CLK | GP18 |
| MAX6675 MOSI | DIN | GP19 |
| MAX6675 MISO | DO | GP16 |
| MAX6675 CS | CS | GP17 |
| RPM Sensor | - | GP2 |
| Speed Sensor | - | GP3 |

**Note:** Adjust these pins in the code if using different GPIO assignments.

## Code Structure

### Classes

#### `SSD1306`
Minimal SSD1306 OLED driver for text rendering.

**Methods:**
- `__init__(i2c, addr)` - Initialize display
- `clear()` - Clear framebuffer
- `text(s, x, y, color)` - Render text at position (x, y)
- `show()` - Update display with framebuffer contents
- `_char(c, x, y, color)` - Internal character rendering
- `_init_display()` - Send initialization sequence to display

**Features:**
- 5x7 font built-in
- Supports characters 32-126 (space through tilde)
- Framebuffer-based rendering

#### `MAX6675`
K-type thermocouple temperature reader over SPI.

**Methods:**
- `__init__(spi, cs_pin)` - Initialize SPI and chip select
- `read_temp()` - Read temperature in °C

**Conversion:**
- Raw 16-bit value read over SPI
- Upper 13 bits contain temperature data
- Each LSB = 0.25°C

### Global Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `rpm_ticks` | int | Pulse count for RPM calculation |
| `rpm_last_time` | int | Millisecond timestamp of last RPM update |
| `rpm_value` | int | Calculated RPM (display value) |
| `spd_ticks` | int | Pulse count for speed calculation |
| `spd_value` | int | Calculated speed (display value) |
| `temp` | float | Current temperature reading |

### Interrupt Handlers

#### `rpm_interrupt(pin)`
Called on rising edge of RPM sensor signal. Increments pulse counter.

#### `spd_interrupt(pin)`
Called on rising edge of speed sensor signal. Increments pulse counter.

### Callback Functions

#### `update_rpm(timer)`
**Frequency:** 2 Hz (every 500ms)

Calculates RPM from pulse count and elapsed time:
```
RPM = (pulse_count * 60000) / elapsed_ms
```

Resets counters after calculation.

#### `update_display(timer)`
**Frequency:** 10 Hz (every 100ms)

- Updates speed value: `speed = pulse_count * 10` (adjustable multiplier)
- Clears OLED framebuffer
- Renders three lines of text
- Updates display

## How It Works

1. **Hardware Initialization**
   - I2C bus (400 kHz) for OLED
   - SPI (4 MHz) for MAX6675
   - GPIO interrupts on RPM and speed pins (rising edge)
   - Two timers: one for RPM calculation, one for display update

2. **Main Loop**
   - Continuously reads thermocouple temperature (~0.1s interval)
   - Updates global `temp` variable

3. **Real-Time Updates**
   - RPM sensor pulses → `rpm_ticks` incremented
   - Speed sensor pulses → `spd_ticks` incremented
   - Every 500ms: RPM calculated from pulse count and elapsed time
   - Every 100ms: Display updated with latest values
   - Every ~100ms: Temperature read and updated

4. **Display Refresh**
   - 10 FPS update rate keeps display responsive
   - Minimal flickering due to framebuffer architecture

## Setup & Installation

### 1. Flash MicroPython
Download and flash latest MicroPython for Raspberry Pi Pico:
```bash
# Using thonny or mpremote
mpremote cp main.py :main.py
```

### 2. Upload Code
Save `blink.py` as `main.py` on the Pico.

### 3. Hardware Connections
Connect sensors and display according to the pinout table above.

### 4. Run
The dashboard starts automatically on power-up. Press Ctrl+C in REPL to stop.

## Customization

### Adjust Speed Multiplier
In `update_display()` function:
```python
spd_value = spd_ticks * 10  # Change 10 to your sensor ratio
```

**Calculation:**
- If your speed sensor gives 1 pulse per km traveled, use multiplier 10 (for 10 Hz refresh, that's 0.1 km per pulse)
- Adjust based on wheel circumference and pulses per rotation

### Adjust I2C Address
If your OLED is at a different address:
```python
OLED_ADDR = 0x3D  # or 0x3C (default)
```

### Adjust GPIO Pins
Modify constants at top of file:
```python
I2C_SDA = 0
I2C_SCL = 1
RPM_PIN = 2
SPD_PIN = 3
# etc.
```

### Adjust Display Update Rate
RPM calculation frequency (currently 2 Hz):
```python
rpm_timer.init(freq=2, callback=update_rpm)  # 2 Hz = 500ms window
```

Display refresh rate (currently 10 Hz):
```python
display_timer.init(freq=10, callback=update_display)  # 10 Hz
```

### Adjust SPI Speed
For MAX6675:
```python
spi = SPI(SPI_ID, baudrate=4000000, ...)  # 4 MHz (safe default)
```

## Constraints & Limitations

- **Single file:** All code in one `main.py` file (no modules)
- **Memory:** Minimal allocation for Pico (264 KB RAM total)
- **Font:** 5x7 ASCII only (characters 32-126)
- **RPM timing:** Resolution depends on pulse frequency (lower RPM = less accurate)
- **Temperature:** Reads continuously in main loop (not interrupt-driven)
- **Display:** 128x64 pixels only
- **No persistence:** Values reset on power cycle

## Troubleshooting

### Display Not Showing
- Check I2C address (default 0x3C)
- Verify SDA/SCL pins and pull-ups
- Check I2C communication: `i2c.scan()` in REPL

### RPM Always Zero
- Check RPM sensor connection to GP2
- Verify sensor produces rising-edge pulses
- Monitor with oscilloscope or logic analyzer

### Speed Not Updating
- Check speed sensor on GP3
- Verify multiplier value in code
- Check pulse count in REPL (add debug print)

### Temperature Always Zero
- Check MAX6675 SPI connections (SCK, MOSI, MISO, CS)
- Verify thermocouple leads connected correctly
- Check SPI communication errors

### Memory Issues
- Monitor free RAM: `import gc; print(gc.mem_free())`
- Reduce display refresh rate if needed
- Clear unused buffers

## Performance Notes

- **CPU Usage:** Minimal (interrupt-driven, timer-based)
- **Refresh Rate:** 10 FPS sufficient for dashboard
- **Latency:** <100ms typical response to sensor input
- **Power Draw:** ~150 mA typical (Pico + OLED + sensors)

## Future Enhancements (Phase 2+)

- Configurable units (RPM, speed, temperature)
- Settings menu
- Data logging
- Low RPM cutoff
- Max values tracking
- Gear detection
- Multiple display modes
- Peak hold indicators

## License

MIT License - Free to modify and distribute.

## Support

For issues or questions:
1. Check pinout configuration
2. Verify all connections
3. Test with simple debug scripts
4. Use REPL for live debugging

---

**Version:** 0.1 (Stable)  
**Last Updated:** March 1, 2026  
**Target:** Raspberry Pi Pico (RP2040)  
**Language:** MicroPython
