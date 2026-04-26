# Pi Pico Bike Dashboard PCB Specification

## Board
- Size: 80mm x 60mm
- Layers: 2
- Mounting: 4x M3 holes (corner positions)
- Build preference: Through-hole friendly

## Major Components
- Pico: 2x20 through-hole headers, centered
- D1: 1N5406 through-hole (battery reverse diode)
- SW1: SPST through-hole (battery inline switch)
- C1: 1000uF electrolytic TH (VSYS bulk)
- C2: 100nF ceramic TH (decoupling near Pico)
- RPM front-end:
  - R1: 100k (base series)
  - R2: 10k (base pull-down)
  - Q1: 2N2222 NPN
  - R3: 10k (collector pull-up)
  - Z1: 3.3V zener (base clamp)
- Speed input:
  - R4: 100 ohm series
  - R5: 10k pull-down
  - C3: 100nF optional filter to GND
- MAX6675 connector (TH) to SPI pins
- OLED connector (TH, I2C)
- Buttons connector (6-pin TH: GND + 5 GPIO)
- Battery divider:
  - R6: 100k top
  - R7: 33k bottom
  - Optional 4.7uF TH capacitor for ADC smoothing
- Test pads: GP2, GP3, GP16, GP17, GP18, 3.3V, VSYS, GND

## Connectivity Summary
- Battery + -> D1 -> SW1 -> VSYS
- VSYS -> Pico VSYS + C1 + C2
- GND -> common ground everywhere
- Battery divider: BAT+ -> R6 -> GP26 -> R7 -> GND
- RPM stage:
  - Spark wire -> R1 -> Q1 base
  - Q1 emitter -> GND
  - Q1 collector -> GP2
  - R3: GP2/Q1 collector node -> 3.3V pull-up
  - Z1: base clamp (cathode at base, anode at GND)
- Speed stage:
  - Hall output -> R4 -> GP3
  - R5: GP3 -> GND
  - C3 optional: GP3 -> GND
- MAX6675:
  - VCC->3.3V, GND->GND, SCK->GP18, CS->GP17, SO->GP16, MOSI->GP19 (not used by MAX6675 but wired)
- OLED:
  - VCC->3.3V, GND->GND, SDA->GP0, SCL->GP1
- Buttons module:
  - GND common, individual lines to GP6..GP10, active-low

## Layout Guidance
- Pico centered
- Top-left: power stage
- Right-top: OLED connector
- Right-bottom: MAX6675 connector
- Bottom: buttons connector
- Bottom-left: RPM transistor stage
- Left-middle: speed input stage
- Keep RPM/noisy traces away from I2C/SPI
- Ground plane on bottom layer
