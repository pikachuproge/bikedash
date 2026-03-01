# bikedash

Minimal MicroPython dashboard for a motorized bike using Raspberry Pi Pico (RP2040).

## Current Status

- Stable single-file implementation in `main.py`
- RPM via interrupt + median period filtering
- Speed via interrupt pulse counting + wheel-based km/h calculation
- MAX6675 temperature reading (currently placeholder display `0C`)
- SSD1306 128x64 OLED UI with:
	- Top RPM bar (with tick marks + labels)
	- Center big speed digits + `km/h`
	- RPM number with `RPM` label
	- On-device 5-button settings menu

## Hardware

- Raspberry Pi Pico (RP2040)
- SSD1306 128x64 OLED (I2C)
- Inductive RPM pickup interface (NPN + diode + resistor)
- Speed pulse sensor (GPIO interrupt)
- MAX6675 thermocouple module (SPI)

## Pin Defaults

- OLED: `SDA=GP0`, `SCL=GP1`
- MAX6675: `SCK=GP18`, `MOSI=GP19`, `MISO=GP16`, `CS=GP17`
- RPM sensor: `GP2`
- Speed sensor: `GP3`

## Button Defaults (Menu)

- `UP`: `GP6`
- `DOWN`: `GP7`
- `LEFT`: `GP8`
- `RIGHT`: `GP9`
- `OK`: `GP10`
- Wiring: each button from GPIO to `GND` (internal pull-up)

## Settings Menu

- `OK`: open/close settings
- `UP` / `DOWN`: select setting
- `LEFT` / `RIGHT`: decrease/increase value
- Bottom help line scrolls as one line

Current menu items:
- `DBNC` (RPM debounce, us)
- `RPPR` (RPM pulses per rev)
- `WHL` (wheel size, mm)
- `SPPR` (speed pulses per wheel rev)
- `RBAR` (RPM bar max)

## Wheel Size Presets

Quick starting values for `WHL` / `WHEEL_SIZE_MM`:

| Wheel/Tire | mm |
|---|---:|
| 26 x 2.125 | 2070 |
| 27.5 x 2.1 | 2185 |
| 700x38C | 2180 |
| 29 x 2.1 | 2285 |

## Notes

- All tunable constants are grouped in the **USER SETTINGS** block at the top of `main.py`.
- Designed to stay simple and finishable (v0.1).
- See `DASHBOARD.md` for full details.
