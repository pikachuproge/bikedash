# Motorcycle Dashboard (RP2040 + SSD1306)

Current project documentation for the active `main.py` implementation.

## Scope

- Single-file MicroPython dashboard (`main.py`)
- Raspberry Pi Pico (RP2040)
- SSD1306 128x64 OLED over I2C
- RPM input via GPIO interrupt (inductive pickup front-end)
- Speed input via GPIO interrupt
- MAX6675 over SPI (live temperature display with fault fallback)
- 5-button runtime settings menu + long-press info screen (saved to onboard filesystem)

## Current UI

- **Top:** RPM horizontal bar with fill, tick marks, and numeric tick labels
- **Top/Mid:** RPM number + `RPM` label
- **Center/Bottom:** Large speed digits with `km/h` text to the right
- **Bottom-left:** odometer (`x.x KM`, then whole `KM` at higher values)
- **Bottom-right:** live temperature (`xxC`) or `TC ERR` on sensor fault

## Info Screen (Long Press)

- From main screen, hold `OK` to open the info screen.
- Press `OK` again to exit back to main.
- Info screen shows:
	- Odometer
	- Trip distance
	- Engine runtime
	- Current temperature / fault text
	- Sensor status flags (`R/S/T`, `+`=recent signal, `-`=stale/fault)

## Default Pinout

| Signal | GPIO |
|---|---|
| OLED SDA | GP0 |
| OLED SCL | GP1 |
| MAX6675 SCK | GP18 |
| MAX6675 MOSI | GP19 |
| MAX6675 MISO | GP16 |
| MAX6675 CS | GP17 |
| RPM input | GP2 |
| Speed input | GP3 |

## Button Pinout

| Button | GPIO |
|---|---|
| UP | GP6 |
| DOWN | GP7 |
| LEFT | GP8 |
| RIGHT | GP9 |
| OK | GP10 |

Button wiring is active-low with internal pull-up:
- One side of each button to GPIO
- Other side to GND

## RPM Logic (Current)

- IRQ on rising edge collects pulse periods
- Debounce with `RPM_DEBOUNCE_US`
- Periods stored in ring buffer (`RPM_PERIOD_RING_SIZE`)
- `update_rpm()` uses median period for robust RPM estimate
- Stall timeout handled by `RPM_TIMEOUT_US`

## Speed Logic (Current)

- Speed pulses are counted by interrupt
- Speed is computed from:
	- `WHEEL_SIZE_MM`
	- `SPEED_PULSES_PER_REV`
	- elapsed update time
- Fallback multiplier exists (`SPEED_MULTIPLIER`) if wheel/pulse settings are invalid

## Settings Menu

Controls:
- `OK`: open/close menu
- Hold `OK`: open/close info screen
- `UP` / `DOWN`: select item
- `LEFT` / `RIGHT`: adjust selected value

Menu entries:
- `DBNC`: RPM debounce (`rpm_debounce_us`)
- `RPPR`: RPM pulses per rev (`rpm_pulses_per_rev`)
- `WHL`: wheel size in mm (`wheel_size_mm`)
- `SPPR`: speed pulses per wheel rev (`speed_pulses_per_rev`)
- `RBAR`: RPM bar max (`rpm_bar_max`)
- `RSET`: restore defaults and save (press `OK` to arm, `OK` again to confirm)
- `TRIP`: read-only trip distance
- `TCLR`: clear trip and save (press `OK` to arm, `OK` again to confirm)

Menu footer uses a single scrolling help line for button hints.

## Timers / Loop

- `rpm_timer`: updates RPM estimator at `RPM_UPDATE_HZ`
- `display_timer`: sets display-due flag at `DISPLAY_UPDATE_HZ`
- Main loop renders display and reads MAX6675
- Odometer, trip, and runtime auto-save periodically

## Tuning Guide (One Place)

All changeable values are in the **USER SETTINGS** block at the top of `main.py`.

Main groups:
- Hardware pins/buses
- RPM tuning (`RPM_PULSES_PER_REV`, `RPM_DEBOUNCE_US`, `RPM_TIMEOUT_US`, `RPM_PERIOD_RING_SIZE`, `RPM_BAR_MAX`)
- Speed tuning (`WHEEL_SIZE_MM`, `SPEED_PULSES_PER_REV`, `SPEED_MULTIPLIER`)
- Button config (`BTN_*`)
- Timing (`RPM_UPDATE_HZ`, `DISPLAY_UPDATE_HZ`, `MAIN_LOOP_SLEEP_MS`)
- UI layout (bar position, tick count/labels, RPM text offsets, speed digit geometry, `km/h` position)

## Run

1. Flash MicroPython to Pico
2. Copy `main.py` to board
3. Reset board

Example with `mpremote`:

```bash
mpremote cp main.py :main.py
mpremote reset
```

## Notes

- Keep edits minimal and test on real hardware after each change.
- If RPM gets noisy, tune `RPM_DEBOUNCE_US` first.
- If scale needs adjustment, change `RPM_PULSES_PER_REV` and `RPM_BAR_MAX`.

## Field Validation Checklist

1. Verify short `OK` opens settings and long `OK` opens info screen.
2. Compare speed to GPS and tune `WHEEL_SIZE_MM` / `SPEED_PULSES_PER_REV`.
3. Confirm RPM stability at idle, mid, and high range.
4. Reboot and verify settings, odometer, trip, and runtime persist.
5. Check fault handling: thermocouple disconnect shows `TC ERR`; info status flags change to `-` when stale.

## Quick Tune Cheatsheet

Use these as practical defaults for a 2-stroke single-cylinder pickup:

- `RPM_PULSES_PER_REV = 1`
- `RPM_DEBOUNCE_US = 4000`
- `RPM_PERIOD_RING_SIZE = 7`
- `RPM_TIMEOUT_US = 2000000`
- `RPM_BAR_MAX = 10000`
- `WHEEL_SIZE_MM = 2100`
- `SPEED_PULSES_PER_REV = 1`

### Wheel Size Presets (starting points)

Set `WHEEL_SIZE_MM` to one of these common values, then fine-tune with GPS:

| Wheel/Tire | `WHEEL_SIZE_MM` |
|---|---:|
| 20 x 1.75 | 1590 |
| 24 x 1.95 | 1915 |
| 26 x 1.95 | 2055 |
| 26 x 2.125 | 2070 |
| 26 x 2.2 | 2090 |
| 27.5 x 2.1 | 2185 |
| 700x35C | 2168 |
| 700x38C | 2180 |
| 700x40C | 2200 |
| 29 x 2.1 | 2285 |

Quick calibration:
1. Pick nearest preset.
2. Ride at steady speed and compare to GPS.
3. Increase `WHEEL_SIZE_MM` if dashboard speed is low; decrease it if speed is high.

If behavior is not ideal:

- **RPM spikes high** → increase `RPM_DEBOUNCE_US` by `+300` to `+700`
- **RPM reads too low / misses pulses** → decrease `RPM_DEBOUNCE_US` by `-300` to `-700`
- **Display too jumpy** → increase `RPM_PERIOD_RING_SIZE` (`7` → `9`)
- **Display too sluggish** → decrease `RPM_PERIOD_RING_SIZE` (`7` → `5`)
- **RPM drops to zero too quickly** → increase `RPM_TIMEOUT_US`
- **RPM hangs above zero too long after stop** → decrease `RPM_TIMEOUT_US`
- **Speed reads high/low at all ranges** → tune `WHEEL_SIZE_MM`
- **Speed jumps in steps** → verify/tune `SPEED_PULSES_PER_REV`

Safe tuning workflow:

1. Change only one setting at a time.
2. Test at idle, mid, and high RPM.
3. Keep the change only if it improves all three ranges.

---

**Updated:** March 1, 2026  
**Target:** Raspberry Pi Pico (RP2040)  
**Language:** MicroPython
