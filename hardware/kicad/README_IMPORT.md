# Pi Pico Bike Dashboard — KiCad Build Pack

This folder contains a structured CAD build pack derived from your specification.

## Included files

- `bike_dashboard_spec.md` — full design spec and constraints
- `bike_dashboard_nets.csv` — net-level connectivity map
- `bike_dashboard_bom.csv` — through-hole BOM with value/package notes
- `bike_dashboard_placement.csv` — placement guidance and board zones

## KiCad workflow

1. Create a new KiCad project in this folder (same name you want for production).
2. In schematic editor:
   - Place symbols from `bike_dashboard_bom.csv`.
   - Wire using `bike_dashboard_nets.csv`.
   - Apply notes from `bike_dashboard_spec.md`.
3. Assign through-hole footprints.
4. Annotate + run ERC.
5. Open PCB editor, import netlist from schematic.
6. Set board outline to 80mm x 60mm.
7. Place components per `bike_dashboard_placement.csv`.
8. Route with constraints:
   - Power traces >= 1.0mm
   - Signal traces 0.25–0.30mm
   - Bottom-layer GND zone
9. Add 4x M3 mounting holes and tie to GND net where desired.
10. Run DRC and generate Gerbers.

## Firmware pin mapping basis

This pack matches your current `main.py` mapping:
- OLED SDA/SCL: GP0/GP1
- RPM input: GP2
- Speed input: GP3
- Buttons: GP6..GP10
- MAX6675: GP16/GP17/GP18/GP19
- Battery monitor divider: GP26
