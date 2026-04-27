# Bike2 Project Manual (Living Document)

Last updated: 2026-04-27

This is the single-source reference for the current Bike2 project.

It covers:
- Full feature set (ECU + Dash)
- Wiring and pin maps
- UART protocol and config payloads
- Programming/flashing workflow
- Runtime configuration and persistence
- Bench test + troubleshooting procedures

## Living Document Contract

This file is intended to be continuously maintained.

Whenever any of these change, this file must be updated in the same work session:
- dash/main.py
- ecu/main.py
- ecu/config_layer.py
- hardware/kicad/*

Update checklist per change:
- Architecture impact
- Pinout or wiring impact
- Protocol/TLV impact
- Config/persistence impact
- Flash/run instructions impact
- Troubleshooting impact

## Repository Layout

- dash/main.py
  Dash firmware (OLED UI, buttons, telemetry ingest, config sender, demo mode, persistence)
- ecu/main.py
  ECU firmware (crank decode, ignition scheduling, safety, telemetry source, config ingest)
- ecu/config_layer.py
  ECU profile schema, sanitize/clamp rules, CRC, atomic save + recovery
- main.py
  Legacy single-Pico dashboard implementation (kept for compatibility)
- hardware/kicad/
  PCB build pack (spec, nets, BOM, placement)

## System Architectures

### Current Primary Architecture (Dual Pico)

- ECU Pico
  Owns ignition execution and crank timing.
  Sends engine telemetry to Dash.
  Accepts config proposals from Dash.
- Dash Pico
  Owns UI, menu, display, and config editing.
  Never drives ignition directly.

### Legacy Compatibility Architecture (Single Pico)

- Uses root main.py and direct local sensors.
- Hardware docs under hardware/kicad are based on this mapping.

## Feature Set

## ECU Features (ecu/main.py)

- Gear-tooth crank position model
  CRANK_GEAR_LAYER with sync acquisition and timeout handling.
- Ignition modes
  IGN_MODE_INHIBIT, IGN_MODE_SAFE, IGN_MODE_PRECISION.
- Safety paths
  Safety inhibit input, stale-event guards, unschedulable guards, ISR overrun faulting.
- Deterministic scheduling
  IRQ edge capture + timer tick execution for coil ON/OFF event slots.
- Telemetry transmission
  Framed binary protocol with CRC16 and TLV payload.
- Config ingestion
  Framed config packets from Dash (preview/apply/commit).
- Safe runtime apply
  Applies pending config only in safe window (not in precision, no armed events, coil off).
- Geometry-change gating
  Geometry-related changes are marked reboot-required.
- Persistent profile load
  Loads ECU profile on boot with backup recovery.

## Dash Features (dash/main.py)

- OLED UI
  Main screen, settings screen, info screen, history graph screen.
- Robust input handling
  Edge-based button event detection, short/long OK actions.
- Telemetry parser
  Frame state machine with CRC validation and TLV decode.
- Link-state adapter
  LINK_OK/LINK_STALE/LINK_LOST handling for display gating.
- ECU config sender
  Sends TLV+JSON config packets (PREVIEW/APPLY/COMMIT).
- Config response ingest
  Parses ECU config status/flags/text responses.
- Persistent settings
  Writes dashboard_settings.json atomically via tmp file swap.
- Demo mode
  Synthetic RPM/speed/temp/trip/odo updates for bench testing.
- OLED recovery
  reset_oled() and recover_oled() support bus recovery and optional hardware reset pin pulse.
- Main-screen ECU badge
  Shows ECU telemetry freshness with an `ECU` label and a status square at the top-right of the Dash display.

## ECU Wiring and Pin Map

ECU pin assignments (ecu/main.py):

| Signal | GPIO | Direction | Notes |
|---|---|---|---|
| Crank pulse input | GP2 | IN | Digital tooth pulse input from external conditioner |
| Coil drive output | GP15 | OUT | Ignition coil driver control |
| Safety inhibit | GP14 | IN | Active-low inhibit input |
| UART0 TX | GP0 | OUT | ECU -> Dash telemetry |
| UART0 RX | GP1 | IN | Dash -> ECU config |
| Debug LED | GP25 | OUT | Onboard indicator for sync/fault/config activity |

## Dash Wiring and Pin Map

Dash pin assignments (dash/main.py):

| Signal | GPIO | Direction | Notes |
|---|---|---|---|
| OLED SDA | GP0 | I2C | Display data |
| OLED SCL | GP1 | I2C | Display clock |
| UART1 TX | GP4 | OUT | Dash -> ECU config |
| UART1 RX | GP5 | IN | ECU -> Dash telemetry |
| BTN UP | GP6 | IN | Active-low button to GND |
| BTN DOWN | GP7 | IN | Active-low button to GND |
| BTN LEFT | GP8 | IN | Active-low button to GND |
| BTN RIGHT | GP9 | IN | Active-low button to GND |
| BTN OK | GP10 | IN | Active-low button to GND |
| MAX6675 MISO | GP16 | SPI | Legacy local sensor path |
| MAX6675 CS | GP17 | SPI | Legacy local sensor path |
| MAX6675 SCK | GP18 | SPI | Legacy local sensor path |
| MAX6675 MOSI | GP19 | SPI | Routed but not required by MAX6675 |
| RPM input (legacy) | GP2 | IN | Legacy single-board path |
| Speed input (legacy) | GP3 | IN | Legacy single-board path |

Optional display reset:
- OLED_RESET_PIN in dash/main.py
- Set to GPIO number if OLED RES is wired.
- Default is -1 (not wired).

## ECU <-> Dash Interconnect (Dual Pico)

Required connections:

| From | To |
|---|---|
| ECU GP0 (UART0 TX) | Dash GP5 (UART1 RX) |
| ECU GP1 (UART0 RX) | Dash GP4 (UART1 TX) |
| ECU GND | Dash GND |

Both sides use 3.3 V TTL UART at 230400 baud.

UART direction reminder:
- ECU GP0 is TX, so it must go to Dash RX.
- ECU GP1 is RX, so it must go to Dash TX.
- If the link is dead, swap only the TX/RX pair first, not the grounds.

## Legacy PCB Hardware Pack

For full legacy board details, see:
- hardware/kicad/bike_dashboard_spec.md
- hardware/kicad/bike_dashboard_nets.csv
- hardware/kicad/bike_dashboard_bom.csv
- hardware/kicad/bike_dashboard_placement.csv

Highlights:
- Board: 80 mm x 60 mm, 2-layer, through-hole friendly
- Power: battery -> reverse-protect diode -> switch -> VSYS
- RPM front-end: NPN + zener clamp + pull-up
- Speed conditioning: series resistor + pull-down + optional RC filter

## Dual-Pico Hardware Design (Prototype)

This section is the build reference for a perfboard / hand-wired automotive-style harness prototype. Battery is a single-cell Li-ion (3.7 V nominal, 7000 mAh). Ignition coil is fed by the magneto; ECU controls the primary switch via opto-isolation. There is no PCB design here on purpose — everything below is sized for through-hole modules and crimped harness wiring.

### System Architecture (Three Domains)

The system is partitioned into three electrical domains that share one ground reference and nothing else:

```
                    DOMAIN A: IGNITION (magneto-driven, high voltage)
                    ┌────────────────────────────────────────────┐
                    │  Magneto stator ── Coil primary ── IGBT C  │
                    │                                       │    │
                    │  Coil primary (-) ──────────── IGBT E ┘    │
                    │                                            │
                    │   IGBT emitter ──[OWN dedicated wire]──┐   │
                    └────────────────────────────────────────┼───┘
                                                             │
                    DOMAIN B: LOGIC (Li-ion powered)         │
                    ┌────────────────────────────────────────┼───┐
                    │  Li-ion 1S ─ BMS ─ fuse ─ P-FET ─ TVS ─┤   │
                    │      │                       │            │
                    │      │       buck-boost 5V ──┼── Pico VSYS│
                    │      │                       │     (each) │
                    │      └─── star ground ───────┴────────────┤
                    │                                            │
                    │  Pico GP15 ── opto-LED ─── (cross domain)  │
                    │                                  │         │
                    │                  opto-output ── gate drv ──┼──> IGBT gate (Domain A)
                    └────────────────────────────────────────┼───┘
                                                             │
                    DOMAIN C: SENSORS (mixed)                │
                    ┌────────────────────────────────────────┼───┐
                    │  Crank sensor ── conditioner ── ECU GP2     │
                    │  Speed sensor ── frontend ── Dash GP3       │
                    │  Thermocouple ── MAX6675 ── Dash SPI        │
                    │  All sensor returns → logic GND (Domain B)  │
                    └─────────────────────────────────────────────┘
                                                             │
                                                  ┌──────────┴─┐
                                                  │ Battery -  │
                                                  │ STAR POINT │
                                                  └────────────┘
```

Validation rules:
- Domain A current never returns through Domain B copper. The IGBT emitter wire is its own conductor straight to the battery negative star point.
- Domain B (logic ground) is the only domain that touches Pico GND pins.
- Domain C sensors return via Domain B (sensor returns are quiet, low-current).
- Magneto stator iron is bolted to the engine block; that is its ground reference. No deliberate wire from the magneto frame to the battery negative.
- The opto-isolator is the only physical link between Domain A driver output and Domain B GP15. Light bridges the gap; no copper does.

ECU is mounted close to the engine (short coil and crank wires). Dash is on the handlebars. Between them runs ONE 4-wire harness: V_BAT, LOGIC_GND, UART_A, UART_B.

### 1. Power System (Li-ion, Critical)

Battery: 1S Li-ion, 3.7 V nominal, range 3.0 V (empty) to 4.2 V (full charge), 7000 mAh.

Battery management (NON-NEGOTIABLE):
- Use a protected cell (built-in BMS) OR add a discrete BMS. Discrete option: DW01A protection IC + dual-FET 8205A. Or buy a "1S Li-ion BMS module" off the shelf — they're $1-2 each.
- The BMS must provide: overvoltage cutoff (~4.25 V), undervoltage cutoff (~2.7 V), overcurrent, short-circuit protection.
- This protects the cell. Do not skip it. A shorted cell on a motorcycle is a fire.
- If you want on-bike charging from a USB port or DC source: TP4056 module with built-in protection (the "TP4056 + DW01" red board). This is the simplest option.

Pico powering strategy:
- Pico's onboard regulator on VSYS accepts 1.8-5.5 V and produces the 3.3 V rail internally. Do NOT drive 3V3_OUT externally.
- Li-ion swings 3.0-4.2 V over its discharge curve — entirely within VSYS spec — but the rail will drift with battery state if fed direct.
- For a stable rail and headroom for any peripheral that wants 5 V (gate driver, certain optos, future expansion), regulate the Li-ion UP to a clean 5 V via a synchronous boost (or buck-boost) module. Each Pico gets its own regulator; do not share regulated 5 V across the long handlebar harness.

Recommended boost module per Pico:
- Pololu U3V12F5 (1 A, 5 V, ~95 % efficient, robust) — best option, $5-7.
- Or a generic MT3608-based "Mini 5V Boost" module if budget rules — works but is noisier; add a 100 µF + 100 nF on its output.

Per-Pico power chain (input from harness V_BAT pin):
1. Inline 3 A polyfuse (or 3 A blade fuse + holder) on V_BAT entry.
2. Reverse-polarity P-FET in series: DMG2305UX or AO3401 (low-Vgs, Vgs(th) ~1 V so it conducts cleanly at 3 V Li-ion). Source = harness V_BAT, drain = downstream rail, gate = GND through 10 kΩ.
3. TVS diode V_BAT-to-GND: SMBJ5.0CA (5 V standoff, 9.2 V clamping, bidirectional). Catches anything that gets past the BMS.
4. LC filter: 22 µH inductor (Bourns RLB-series, 1 A rated) + 47 µF / 16 V electrolytic + 100 nF X7R ceramic to GND.
5. Boost module input: feed from filtered V_BAT.
6. Boost module output (5 V): 22 µF + 100 nF directly at the module output, then run to Pico VSYS.
7. At Pico VSYS pin: another 10 µF + 100 nF X7R right next to the pin.
8. Ferrite bead (BLM18AG601 or similar 600 Ω @ 100 MHz) on the 5 V trace between boost output and Pico VSYS.

Total per-Pico power-stage component count: ~10 small parts plus the boost module. Fits on a 50 × 70 mm perfboard segment with room to spare.

Ignition-noise rejection:
- The boost converter's inherent input filter handles most ignition radiated noise.
- The TVS catches conducted spikes.
- Magneto coil flyback can radiate into the harness — keep V_BAT and GND wires twisted together (one twist per inch) on the long run from battery to ECU and to dash.
- If you observe Pico resets when the engine fires, add a second 100 µF electrolytic right at the V_BAT entry of each Pico's power stage.

### 2. Ignition + Magneto Interface

Default topology assumed: magneto-TCI (the magneto's primary winding is switched by an electronic transistor ECU-side; opening the transistor collapses the field and drives the secondary HT). If the bike is CDI (capacitor-discharge), see the SCR variant at the end of this section.

Driver chain (TCI):

```
Pico GP15 ──[220 Ω]──┐
                     │ A      K
                     +───>|───+
                     │  6N137 │
                     │  LED   │
       Logic GND ────┴────────┘
                     ─ ─ ─ ─ optical isolation barrier ─ ─ ─ ─
                              (no copper crosses here)
                              ─────────────────────────────
                                                 │
                              5V_DRIVER ──[4.7kΩ]┤
                                                 │
                                            6N137 OUT ──┐
                                                        │
                                              TC4427 IN ┘
                                              TC4427 OUT ──[10 Ω gate]── IGBT G
                                                                          │
                                              IGBT C ── Coil primary ── magneto
                                              IGBT E ── (own wire) ── BAT NEG STAR
                                                  │
                              Snubber: 470 nF/1 kV + 100 Ω across C-E
                              Clamp: TVS BiDir 400 V across C-E (optional, if no internal diode)
```

Key part picks:
- Opto: 6N137 (10 Mbps logic-output opto). Drive LED through 220 Ω from GP15 (3.3 V drive: 1.4 V Vf, ~9 mA — fine). Output side needs 5 V via the driver-side rail.
- The driver side needs its OWN small power supply: a second tiny boost (or a dedicated winding off the main boost) generating 5 V for the gate-driver subsystem. Tying this to the main 5 V rail is acceptable IF the IGBT emitter return wire is short and goes directly to the battery negative star (which it must anyway).
- Gate driver: TC4427 (1.5 A push-pull). Skipping this and driving the IGBT gate with the opto output directly causes slow turn-off, excess heat, and gate ringing. Don't.
- Switching device:
  - First choice: FGA25N120ANTD IGBT (1200 V, 25 A, has internal flyback diode) — bulletproof, automotive-grade, the gold standard.
  - Cheaper alternative: BU941ZP Darlington — classic motorcycle ignition switch, runs forever, easier to source.
- Snubber across C-E: 470 nF / 1 kV polypropylene film cap in series with 100 Ω / 1 W resistor. Suppresses the high-frequency ringing on collector when the field collapses.
- TVS clamp from C to E: bidirectional 400 V TVS (e.g. 1.5KE400CA) — only needed if your IGBT does not have an internal flyback diode.

Why isolation is non-negotiable: the coil primary swings 200-400 V every fire event. Even a tiny ground bounce (millivolts) will couple into Pico GND if the driver shares a copper path. Optical isolation breaks this completely. Skip it and you will lose a Pico — typically the ECU first, sometimes the Dash too.

CDI variant (if magneto charges a cap that ECU triggers via SCR):
- Replace IGBT + gate driver with an SCR (BT151-600, 600 V).
- The opto drives the SCR gate through a small current-limiting resistor (~470 Ω) and a pulse transformer if you want stricter isolation.
- Add a fast HV diode (MUR460) on the magneto-to-cap charging path.

### 3. Crank Signal Conditioning (ECU GP2)

Two sensor types covered. Use a small daughterboard so swapping is non-destructive.

VR (variable reluctance, two-wire AC):
- Output swing: ~100 mV at crank, can hit 200 V+ at high RPM.
- Direct connection to the Pico is forbidden — even one over-voltage event destroys GP2.
- Recommended conditioner: MAX9926UAUB+ (single-chip, programmable adaptive hysteresis, immune to common-mode noise). Outputs a clean 3.3 V digital pulse straight to GP2.
- Alternative if MAX9926 is unavailable: LM393 dual comparator, AC-coupled input through 100 nF, hysteresis set with a 47 kΩ resistor between output and (+) input, pulled up to 3.3 V at output. Works but is more sensitive to layout and grounding.

Input protection (BEFORE the conditioner chip):
- 4.7 kΩ / 1/4 W series resistors on each VR lead (limits current into the clamp).
- Back-to-back 18 V zener pair (or a 33 V bidirectional TVS) clamping each lead to GND.
- 1 nF cap from each lead to GND (filters out radiated HF from the magneto).

Cable: shielded twisted pair from the VR sensor to the ECU enclosure. Shield grounded ONLY at the ECU end.

Hall sensor (three-wire, open-collector):
- Power the sensor from the Pico's 3V3 rail (most modern automotive Halls work fine at 3.3 V; check the datasheet — some need 5 V, in which case feed from the local 5 V rail).
- Sensor signal → 1 kΩ series → GP2.
- 4.7 kΩ pull-up from GP2 to 3.3 V.
- 100 nF GP2-to-GND for HF noise.
- 1N4148 from GP2 to 3V3 (cathode to 3V3) for over-voltage clamp.

### 4. Speed Sensor (Dash GP3)

Most motorcycle wheel-speed sensors are 3-wire Hall (V+, GND, signal). Reed switches are common on older bikes.

Hall sensor wiring:
- Sensor V+ from the Pico 3V3 rail (3.3 V Halls), or from the local 5 V rail (5 V Halls). Match what the sensor specifies.
- Signal → 1 kΩ / 1/4 W series → GP3.
- 10 kΩ pull-up GP3 to 3.3 V (NEVER to 5 V — Pico is not 5 V tolerant).
- 100 nF GP3-to-GND for low-pass filtering.
- 1N4148 from GP3 to 3V3 (cathode to 3V3) — overshoot clamp.
- 1N4148 from GND to GP3 (cathode to GP3) — undershoot clamp.

Reed switch wiring (simpler):
- Reed connects GP3 directly to GND when triggered.
- Internal Pico pull-up handles the high state.
- 100 nF GP3-to-GND for contact bounce filtering.
- SPEED_PULSES_PER_REV = number of magnets on the wheel.

Long wire run from wheel to dash (~1 m typical):
- Twisted pair (signal + return ground), inside a sleeve.
- 100 Ω inline resistor near the wheel-end + 100 nF cap to GND at the dash-end forms an RC low-pass with cutoff ~1.5 kHz — perfectly comfortable for a wheel sensor.
- ESD: a TVS like SMBJ3.3CA from the GP3-side of the harness to GND eats nearby lightning-induced spikes.

### 5. Temperature Sensor (MAX6675 + Type-K Thermocouple)

Module placement:
- MAX6675 breakout INSIDE the dash enclosure, near where the thermocouple wires enter. The MAX6675 IC is the cold-junction reference, so its temperature defines the reading offset.
- Type-K thermocouple probe at the cylinder head (M6 ring lug, clamped under a head bolt). Avoid direct spark plug body contact — the temperature swing there exceeds the MAX6675 range.

Thermocouple wire — the most common installation mistake:
- The wire from the thermocouple bead to the MAX6675 input MUST be type-K extension wire (yellow/red colour code in US convention, green/white in IEC).
- Do NOT splice copper hookup wire in. A copper-K junction creates a parasitic thermocouple at the splice that adds offset proportional to the splice temperature. In an engine bay this offset can be 20-50 °C of error.
- If the probe pigtail is too short to reach the dash, use type-K extension wire with a proper screw terminal junction OR a type-K connector pair. Do not fudge it.

Wiring on the SPI side (inside dash enclosure):
- Power MAX6675 from the Pico 3V3 rail. The chip works on 3.0-5.5 V; 3.3 V keeps it logic-level-compatible with the Pico without level shifters.
- Keep SPI traces short (under 100 mm).
- 1 kΩ series resistor on MISO (GP16) near the Pico for ESD protection.
- 100 nF X7R decoupling cap directly at MAX6675 VCC.

Noise mitigation:
- Twist the thermocouple extension pair tightly (~1 turn per inch) all the way from probe to MAX6675 terminal block.
- Do NOT route the TC pair near the coil primary or the HT plug lead. 100 mm clearance minimum.
- If TEMP_FAULT shows intermittently when the engine fires, switch to shielded TC cable — shield grounded at the MAX6675 end only.

### 6. ECU ↔ Dash UART Harness

230 400 baud over a 1 m harness has plenty of margin, but motorcycles are exceptionally noisy electrically. Design the harness to survive, not just to function.

Recommended baseline:
- Cable: 4-conductor with two twisted pairs, overall foil shield. Belden 9501 or generic equivalent.
- Pair 1: ECU GP0 (TX) ←→ Dash GP5 (RX), twisted with one GND conductor.
- Pair 2: Dash GP4 (TX) ←→ ECU GP1 (RX), twisted with one GND conductor.
- Both GND conductors connect to logic GND at both ends.
- Shield grounded ONLY at the ECU end.
- 220 Ω / 1/4 W series resistor at each TX pin (in-line on the PCB, not in the cable). Limits short-circuit fault current and helps line-end matching.
- 100 pF X7R cap from each RX pin to GND (HF filter, 230 400 baud sees this as a flat short).
- Clip-on ferrite (Würth 74271132 or generic) over the harness near each board.

This is more than enough for a 1 m harness through the steering tube. Hardening upgrade exists if needed: replace the level-translation with MAX485 / SP3485 differential transceivers each side (RS-485). Differential signalling is immune to almost all motorcycle electrical noise. ~$2 per side, one IC. Don't pre-emptively switch — only do this if frame errors persist on the basic harness.

Cross-over wiring reminder: ECU TX → Dash RX, Dash TX → ECU RX. If the link is dead, swap only the TX/RX pair first, never the grounds.

### 7. Grounding Architecture (Star Topology)

Single-point ground at the battery negative terminal is law:

```
                         BAT NEG TERMINAL (the star point)
                              │
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        │                     │                     │
     ECU GND wire        DASH GND wire     IGBT EMITTER wire
     (one dedicated)    (one dedicated)    (own dedicated wire)
        │                     │                     │
     ECU board GND        Dash board GND      Coil primary -
```

Rules:
1. ECU GND ➜ battery negative directly (own wire, not shared).
2. Dash GND ➜ battery negative directly (own wire, not shared).
3. Coil low-side return ➜ battery negative directly (own wire, not shared).
4. Magneto stator iron ➜ engine block (its native ground). Do NOT add a wire to the battery star.
5. Sensor cable shields ➜ logic GND at ONE end only (whichever board owns that sensor), never both.
6. Battery negative ➜ chassis is OK as a secondary equipotential bond — but logic ground does NOT route through the chassis.

The single most important rule: Domain A (ignition return) current must never flow on Domain B (logic) copper. If you find yourself running ANY ignition return current through a Pico GND pin, stop and rewire.

### 8. Wiring and Connectors

Wire gauge by subsystem:
- Battery main feed (V_BAT, LOGIC_GND): 16 AWG silicone-jacketed.
- Boost-output to Pico VSYS, sensor power: 22 AWG.
- Signal lines (UART, sensor signal pairs): 24 AWG twisted pair.
- Coil primary drive (magneto-to-coil and coil-to-IGBT): 18 AWG minimum, automotive-grade insulation.
- IGBT emitter return to battery negative: 18 AWG minimum.

Insulation:
- Engine bay (anything within 200 mm of the cylinder head or exhaust): silicone-jacketed wire rated ≥ 150 °C.
- Inside dash enclosure: PVC hookup wire is acceptable.

Connectors:
- Engine-bay / weather-exposed connections: Deutsch DT series.
  - 3-pin sensors (Hall): DT04-3P / DT06-3S pair.
  - 4-pin inter-board harness: DT04-4P / DT06-4S pair.
  - These are weatherproof (IP67) and vibration-rated.
- Inside enclosures (board-to-board sub-assemblies): JST-XH 2.54 mm pitch.
- Coil primary drive: spade terminals (faston 6.3 mm) — match what the coil already has.
- Battery: XT60 (60 A rated, polarity-keyed, simple to make, ubiquitous).

Cable routing rules:
- HT plug lead and any wire driving the coil primary stay 100 mm minimum from sensor cables and the UART harness.
- No wire crosses the exhaust pipe or runs alongside it.
- Strain relief at every connector and every enclosure entry. Vibration kills connectors faster than electrical issues do.
- One main bundle from the dash down the steering tube secured every 200 mm with cable clips. Inside this bundle: V_BAT, LOGIC_GND, UART pair × 2.

### 9. Physical Installation

ECU:
- Rubber-isolated bracket near the engine.
- Sealed enclosure (IP54 minimum). A Hammond 1554-series polycarbonate box with M3 standoffs inside is a perfect prototype enclosure. Add a Gore-Tex vent membrane to relieve pressure cycling without letting water in.
- Coil driver and ECU main board on the SAME perfboard if at all possible — keeps the high-current loop small and the opto-isolated signal short.
- Crank sensor cable enters via a strain-relieved cable gland, terminates at the conditioner header.

Dash:
- Handlebar mount on rubber bushings. Vibration isolation matters more than people think — Pico flash chips have been known to corrupt under sustained 1 kHz+ vibration coupled directly into the board.
- Polycarbonate or anti-glare acrylic window over the OLED.
- MAX6675 module mounted on standoffs inside, near the cable entry.
- Thermocouple terminal block at the MAX6675 input.
- Speed sensor cable + UART cable both enter via strain-relieved glands at the bottom of the enclosure.

Battery:
- Mount under the seat or in the conventional battery tray.
- BMS module right at the cell, NOT downstream — protection only works if it's between the cell and everything else.
- Cell wrapped in fish-paper or similar insulator before going into a hard case.
- Battery pack should be shock-mounted (foam or rubber) — Li-ion does not enjoy harmonic vibration.

### 10. Component List (BOM-Style)

Battery and management:
- 1S Li-ion cell, 3.7 V nominal, 7000 mAh (e.g. 21700 high-capacity cell, or 18650 pack equivalent) -- 1
- 1S Li-ion BMS module (DW01A + 8205A based, 3-5 A rated) -- 1
- TP4056 charge module (if on-bike charging desired) -- 1 (optional)
- XT60 connector pair -- 1

Per-board power stage (BUILD TWO IDENTICAL: one for ECU, one for Dash):
- Pololu U3V12F5 boost regulator (or MT3608 module + 100 µF output cap) -- 1
- DMG2305UX or AO3401 P-FET (reverse polarity) -- 1
- 10 kΩ / 1/4 W (P-FET gate pull-down) -- 1
- 3 A polyfuse or blade fuse + holder -- 1
- SMBJ5.0CA TVS diode -- 1
- 22 µH / 1 A inductor (Bourns RLB-series or similar) -- 1
- 47 µF / 16 V electrolytic -- 1
- 22 µF / 16 V ceramic or electrolytic (boost output) -- 1
- 10 µF / 16 V X7R ceramic (Pico VSYS local) -- 1
- 100 nF / 50 V X7R ceramic -- 4
- BLM18AG601 ferrite bead (or equivalent 600 Ω @ 100 MHz) -- 1

Ignition driver (ECU side ONLY):
- 6N137 opto-isolator (DIP-8) -- 1
- TC4427 dual MOSFET driver (DIP-8 or SOIC-8) -- 1
- FGA25N120ANTD IGBT (TO-247) — first choice -- 1
- BU941ZP Darlington (TO-218) — alternate -- 1
- 470 nF / 1 kV polypropylene film cap (snubber) -- 1
- 100 Ω / 1 W metal-film resistor (snubber) -- 1
- 220 Ω / 1/4 W (opto LED current) -- 1
- 4.7 kΩ / 1/4 W (opto output pull-up) -- 1
- 10 Ω / 1/4 W (gate resistor) -- 1
- 1.5KE400CA bidirectional TVS (collector clamp, only if no internal diode) -- 1

Crank conditioner (ECU side, VR option):
- MAX9926UAUB+ -- 1
- 4.7 kΩ / 1/4 W (input series, x2) -- 2
- 18 V zener back-to-back pair (or 1.5KE33CA bidirectional TVS) -- 1
- 1 nF X7R ceramic (input HF filter, x2) -- 2
- 100 nF X7R caps per MAX9926 datasheet -- 3
- DT04-2P / DT06-2S Deutsch pair (sensor connector) -- 1

Speed sensor frontend (Dash side, Hall option):
- 1 kΩ / 1/4 W (signal series) -- 1
- 10 kΩ / 1/4 W (pull-up) -- 1
- 100 nF X7R (HF filter) -- 1
- 1N4148 (clamp diodes) -- 2
- SMBJ3.3CA TVS (ESD) -- 1
- DT04-3P / DT06-3S Deutsch pair (sensor connector) -- 1

Temperature (Dash side):
- MAX6675 breakout module (Adafruit or generic) -- 1
- Type-K thermocouple, M6 ring lug, 1 m pigtail -- 1
- Type-K extension wire, 0.5 m -- 1
- 1 kΩ / 1/4 W (MISO ESD series) -- 1

UART harness:
- 4-conductor cable, two twisted pairs, foil shield, 1.0-1.5 m -- 1
- 220 Ω / 1/4 W (TX series, 4 pcs total — both ends, both directions) -- 4
- 100 pF X7R (RX filter, 4 pcs total) -- 4
- DT04-4P / DT06-4S Deutsch pair -- 1
- Clip-on ferrite, snap-shut style -- 2

General wiring and consumables:
- Silicone-jacketed hookup wire 18 AWG (red, black) — automotive grade, ≥ 150 °C
- Silicone-jacketed hookup wire 22 AWG (red, black, plus 2 colors for signal pairs)
- 24 AWG twisted-pair signal wire (assorted colors)
- Heat shrink, 3:1 adhesive-lined, assorted diameters
- Cable glands (M12 thread) for enclosure entries
- Hammond 1554 polycarbonate enclosure (ECU and Dash) — pick sizes to fit
- M3 nylon standoffs and screws

### 11. Safety Notes

Before any power-up:
- Disconnect the battery before working on the ignition driver. The coil primary can hold residual charge for several seconds after running.
- Verify the IGBT gate is at LOGIC LOW (coil disabled) at boot — write a quick standalone test that holds GP15 low and measures the gate. A stuck-on driver dumps continuous current into the coil and burns it within a minute.
- Verify reverse-polarity protection works BEFORE feeding it to a Pico. Reverse the battery briefly through the protection alone; the fuse blows or the P-FET blocks. If neither happens, fix it before continuing.

Electrical hazards:
- Never bench-test the ignition output with a real coil unless the coil is mechanically restrained. The HT secondary can jump 20 mm to anything grounded.
- Always wear eye protection during ignition bench tests. The HT spark contains UV.
- Li-ion cells release flammable gas under abuse. Do all initial tests with a properly vented charger and a fire-safe location. Do not charge without supervision until the BMS has been verified to actually cut at 4.25 V.

System fail-safe behavior:
- If Dash UART link goes dead while engine running, ECU continues firing the coil safely from its committed profile. Dash loss = non-critical.
- If ECU goes dead, Dash blanks engine readouts (link state goes LOST). Dash loss does not affect ignition (ECU owns ignition independently).
- Safety inhibit input (ECU GP14) MUST be wired to a real switch — typically the kill-switch line on the handlebars. When pulled low, the ECU will not fire the coil regardless of crank state. Test this WORKS before first engine start.

### 12. Bring-Up Procedure (Staged Power-On)

Order of bring-up minimizes blast radius if anything is wrong:

Stage 0 — Battery + BMS isolation test:
1. Charge cell to 100 %. Verify BMS overvoltage cutoff actually trips at ~4.25 V.
2. Discharge through a known load. Verify undervoltage cutoff at ~2.7-3.0 V.
3. Short the output briefly through a 1 A fuse. Verify short-circuit cutoff.
4. Only after all three tests pass: trust the BMS.

Stage 1 — Power stage (per board, no Pico yet):
5. Build per-board power stage. Connect to battery via fuse.
6. Measure boost output: must be 5.0 V ± 0.1 V at no load.
7. Apply a 10 Ω, 0.5 A load resistor across the boost output. Output stays at 5.0 V, no oscillation visible on a scope.
8. Cycle V_BAT input from 3.0 V to 4.2 V (use a bench supply): output must stay flat at 5.0 V.

Stage 2 — Pico boot:
9. Connect Pico VSYS to the verified 5 V rail.
10. Power up. Verify Pico boots, REPL works, no resets under load.
11. Repeat for second Pico.

Stage 3 — UART harness:
12. Build and connect the UART harness.
13. With ECU and Dash both running, verify the link comes up: Dash shows L+, RPM/Sync states display correctly (engine off, so RPM = 0, Sync = LOST).
14. Power-cycle ECU only. Within ~2 seconds, Dash should re-sync (this validates the perma-lost recovery fix).

Stage 4 — Sensors:
15. Crank conditioner: feed a 50 Hz square-wave from a signal generator into the conditioner input. Verify ECU sees pulses on GP2 and reports plausible RPM.
16. Speed sensor: pass a magnet across the Hall sensor by hand. Verify Dash speed counts ticks; trip distance increments correctly.
17. Temperature: verify Dash reads ambient °C in steady state. Touch the probe; reading should rise visibly within 1 second.

Stage 5 — Ignition driver (DUMMY LOAD ONLY):
18. Build the ignition driver.
19. CRITICAL — connect a 10 Ω / 50 W resistor in place of the coil. Do NOT connect a real coil yet.
20. Set ECU to a fixed-RPM test profile via the Dash menu.
21. Verify clean square waves at the IGBT collector with a scope. Verify the timing matches the commanded advance from Dash.
22. Verify gate stays LOW when ECU is reset, when safety inhibit (GP14) is asserted, and when the Pico is unplugged from VSYS.

Stage 6 — Real coil (bench):
23. Replace the load resistor with the actual coil and a spark plug bolted to a grounded heatsink.
24. Power up with the kill-switch active (GP14 asserted low). Verify no spark.
25. Release the kill-switch with the engine NOT cranked. Verify still no spark (no crank signal = no fire).
26. Inject simulated crank pulses. Confirm spark on schedule.

Stage 7 — Install on bike:
27. Install all enclosures, route harness, secure with cable clips.
28. First start with kill-switch held active, then release. The bike fires.

Document every stage's measurements (output voltages, scope captures, timings) in a build log. If something later goes wrong on the road, the build log is the fastest path to diagnosis.

## 2-Stroke Application Manual (Avenger 85 Class — Full ECU Replacement)

This section is the application-specific implementation manual for an 85 cc 2-stroke motorized-bicycle kit engine (Avenger / BT85 / Yingang class) with a **complete replacement** of the stock ignition system. The OEM CDI is removed and not used. The magneto remains physically installed but is repurposed: it powers the ignition coil's primary supply only. ECU-driven ignition timing comes from a NEW Hall effect sensor mounted **inside the dry clutch cover**, reading the outer ring gear teeth directly. One tooth is filed off as the missing-tooth sync feature — there is no separate magnet target.

The generic Hardware Design section above gives the rules; this section tells you what to actually build for THIS engine. If anything in the generic section conflicts with this section, this section wins for 2-stroke installations.

### Scope and System Truth

The hard architectural facts for this build:

- **Stock CDI is removed entirely.** No OEM ignition behavior is preserved or assumed.
- **Magneto remains physically installed.** It is repurposed as the ignition coil's primary supply, AC → bridge rectifier → smoothing → coil primary +. The magneto has zero role in ignition timing.
- **Crank/gear sensor is the ONLY timing source.** A Hall effect sensor (Allegro A3144 with back-bias magnet, or equivalent back-biased Hall) is mounted on the **back face of the clutch assembly** (sensor body inside the assembly, cable exits via a rubber grommet, sensor tip faces the ring gear teeth from the inner side). It reads the outer ring gear teeth as they pass. **One tooth is filed off** to provide the missing-tooth sync feature. The ring gear is a **REDUCTION gear** driven from the crank — it does NOT rotate at crank speed. The effective teeth per crank revolution is `teeth_per_rev = ring_gear_physical_teeth / reduction_ratio`. Worked-example placeholder used throughout this manual: **84 physical teeth with 4:1 reduction → `teeth_per_rev = 21`**. Both the physical tooth count AND the reduction ratio must be confirmed by direct measurement when the engine is opened.
- **Ignition is TCI** (transistor-coil-ignition): IGBT switches the coil primary low-side, controlled by ECU GP15 through optical isolation. The existing ECU firmware is built natively for TCI semantics (dwell + fire events).
- **Pico ECU is powered by Li-ion**, not by the magneto. The magneto only supplies the ignition coil. The ECU starts up before the engine cranks (battery-buffered).

Before wiring on the actual bike, the builder must measure these parameters on the engine. The numbers below are typical-class values, NOT verified for any specific manufacturer.

| Parameter | Typical | How to measure | Used by |
|---|---|---|---|
| Ring gear physical tooth count (UN-filed) | 60-100 | Visual count after clutch cover removal | Numerator of `teeth_per_rev` calc (placeholder: 84) |
| Crank-to-ring-gear reduction ratio | 3:1 to 5:1 | **Mark crank + ring gear, rotate crank by hand, count crank revolutions per ONE full ring gear revolution.** Ring gear is a reduction; it rotates slower than the crank. | Denominator of `teeth_per_rev` calc (placeholder: 4) |
| Effective teeth per crank rev | 15-30 | physical_teeth / reduction_ratio | Sets `teeth_per_rev` directly (placeholder: 21 = 84 / 4) |
| Filed-tooth angular position | aligned with TDC ± 1 tooth | Set with degree wheel before filing | Anchors `sync_tooth_index` to TDC |
| TDC position on flywheel | n/a | Piston-stop tool + degree wheel | Mechanical reference for filing the sync tooth |
| Magneto AC peak at 3000 RPM | 8-15 V | Isolated scope across magneto wires | Sizes rectifier and TVS |
| Magneto AC peak at redline | 15-30 V | Isolated scope at high RPM | Sets TVS clamp voltage |
| Idle RPM | 1500-2200 | Tachometer or Dash readout | Tuning baseline |
| Peak RPM | 7000-9000 | Engine spec / observed | Sets `tooth_min_us` headroom |

#### Reduction-Ratio Measurement Procedure (Engine Arrival)

Do this BEFORE editing `teeth_per_rev` in the active profile.

1. Remove the dry clutch cover. The ring gear and the crank-side drive gear are now both visible.
2. Apply a paint mark on the crank-side gear at any tooth, and a paint mark on the ring gear at any tooth — does not matter which.
3. Slowly rotate the crank by hand (kickstart, or a wrench on the crank nut). Count how many **full crank revolutions** are required for the ring gear to complete **exactly one full revolution** back to its starting orientation.
4. Record this integer (or simple ratio — e.g., 3, 4, 4:1, 5:1). This is your `reduction_ratio`.
5. Visually count the ring gear teeth (`physical_teeth`).
6. Compute `teeth_per_rev = physical_teeth // reduction_ratio` and update the active ECU profile (Dash menu → ECTH or via the runtime config protocol). The old (un-filed) tooth count goes in — `teeth_per_rev` is the count seen by the sensor PER CRANK REVOLUTION, before the file modification.
7. The default values shipped in `ecu/config_layer.py` (`teeth_per_rev=21`, `tooth_min_us=300`, `tooth_max_us=8000`) assume the worked example (84 teeth, 4:1). Adjust all three together if your measured ratio differs — see the "Sync Strategy" section below for the formulas.

### Architecture Delta vs Generic Hardware Section

This 2-stroke build differs from the generic Hardware Design section in five concrete ways:

1. **Crank sensor is mounted on the back face of the clutch assembly**, with the sensor body sitting inside the assembly and the tip facing the ring gear teeth from the inner side. The sensor does NOT protrude externally; the cable exits through a rubber grommet. One tooth on the (reduction) ring gear is filed off to create the missing-tooth sync feature. The sensor is independent of the magneto and is the sole timing source. There is no magnet target on the gear or clutch face. Because the ring gear is a reduction (slower than the crank), the firmware's `teeth_per_rev` is `physical_teeth / reduction_ratio`, not the raw physical tooth count.
2. **The magneto powers the ignition coil only.** Magneto AC → bridge rectifier → smoothing cap → TVS clamp → coil primary +. No copper from the magneto reaches the Pico.
3. **Ignition driver is TCI** (IGBT, dwell-then-fire), not CDI. This matches the existing ECU firmware natively.
4. **Pico is powered by Li-ion 1S** as in the generic design. The magneto is not a logic-power source.
5. Kill-switch is **dual-path**: software (GP14 → INHIBIT mode) AND hardware (shorts opto LED cathode → IGBT gate forced low). Hardware path works even if the Pico is dead.

### Magneto: Power-Only Path (Coil Primary Supply)

The magneto's only job is to supply the ignition coil's primary side with DC. No timing, no Pico connection.

```
Magneto AC line 1 ─┐
                   ├─[Bridge rectifier 4×UF4007]─┬─[Bulk cap 220µF/50V]─┬─ Coil primary +
Magneto AC line 2 ─┘                             │                      │
                                          [TVS SMBJ33CA to GND]    [100nF X7R to GND]

Bridge DC− ── BAT NEG STAR (own dedicated wire)
```

Component selection:
- Bridge: 4× UF4007 ultrafast 1 A 1000 V diodes. Each diode handles half of the magneto cycle.
- Bulk cap: 220 µF / 50 V electrolytic, low-ESR type (Panasonic FR or Nichicon UPM series). Plus 100 nF X7R ceramic right next to it for HF.
- TVS: SMBJ33CA (33 V standoff, ~50 V clamp, bidirectional). Catches the high-RPM voltage spike.

Magneto output range you should expect (typical Avenger-class lighting coil):
- Hand-cranking: 4-8 V AC peak
- Idle: ~6-10 V DC after rectifier
- 5000 RPM: ~12-18 V DC after rectifier
- 9000 RPM: ~20-30 V DC after rectifier

Coil compatibility: most aftermarket motorcycle coils are happy with 6-30 V on the primary (they're current-limited by the IGBT switching and dwell time, not voltage-clamped). The dwell map already in the ECU firmware compensates for primary supply variations — at low magneto voltage, longer dwell builds adequate flux.

### Crank Sensor (Internal, Reading Ring Gear Teeth)

A Hall effect sensor mounted on the **back face of the clutch assembly**, with its tip facing the inner side of the outer ring gear, is the ONLY timing reference. The sensor body sits inside the clutch assembly so nothing protrudes externally; the cable exits the engine case through a rubber grommet. Wiring goes directly to ECU GP2 via a simple conditioner.

Note on geometry: the ring gear is a **reduction** gear, driven from the crank at a 3:1 to 5:1 reduction (typical kit-engine range). It does not rotate at crank speed. The firmware reads ALL of its teeth as they pass, but the configured `teeth_per_rev` must be `physical_teeth / reduction_ratio` because that is the number of edges per crank revolution. With one tooth filed, `teeth_per_rev - 1` actual edges occur per crank rev plus the long missing-tooth gap.

Sensor selection: **Allegro A3144** (with a small back-bias magnet bonded behind the package), or **Honeywell 1GT101DC** (back-biased Hall with the magnet built into the body). The A3144 is a unipolar Hall switch and on its own cannot detect a passing iron tooth — a back-bias magnet behind the IC creates a steady flux that each ferrous tooth modulates as it passes, switching the output. The 1GT101DC has the back-bias built-in and is mechanically simpler if you can source it. Both are 3-wire (V+, GND, signal), open-collector / push-pull at 3.3 V, and work at 0.5-2.0 mm air gap. Insensitive to oil mist.

Conditioner (between Hall signal and Pico GP2):

```
Hall V+   ── ECU 3V3 (or 5V if sensor demands it)
Hall GND  ── ECU LOGIC GND
Hall OUT  ──[1kΩ series]──┬── ECU GP2
                          │
                       [4.7kΩ pull-up to 3V3]
                          │
                       [100nF to GND] (HF filter)
                          │
                       [1N4148 cathode to 3V3] (overshoot clamp)
                       [1N4148 anode to GND]   (undershoot clamp)
                       [SMBJ3.3CA to GND]      (ESD)
```

Cable: 3-conductor shielded twisted pair, 1-2 m, foil + drain wire. Shield grounded at ECU end ONLY.
Connector: Deutsch DT04-3P (sensor) / DT06-3S (harness).

ECU configuration depends on the sync strategy you pick (see "Sync Strategy" below).

### TCI Driver Chain (Replaces the Old CDI Chain)

```
ECU GP15 ──[220Ω]──► 6N137 LED-A
                     6N137 LED-K ── ECU LOGIC GND
                     ─ ─ ─ ─ optical isolation ─ ─ ─ ─
                     6N137 OUT ── 4.7kΩ pull-up to 5V (driver-side rail)
                     6N137 GND ── DRIVER GND (= BAT NEG STAR)
                     6N137 OUT ── TC4427 IN_A
                     TC4427 OUT_A ── 10Ω ── IGBT gate
                     TC4427 V+ ── driver-side 5V, V− ── DRIVER GND
                     IGBT collector ── coil primary −
                     IGBT emitter ── DRIVER GND (own dedicated wire)
                     IGBT gate ── 10kΩ pull-down to emitter (gate fail-safe)
                     bidirectional 400V TVS across collector-emitter (if no internal diode)
```

Behavior: the ECU GP15 goes HIGH to start the dwell phase (current builds through coil primary) and LOW to fire (collapsing field generates HT spark on the secondary). The opto and gate driver propagate this with ~10 µs total latency, well under the firmware's `LEAD_GUARD_FIRE_US = 200` threshold.

Recommended IGBT: **FGA25N120ANTD** (1200 V, 25 A, internal flyback diode, automotive grade). Cheaper alternative: BU941ZP Darlington. Mount with a thermal pad to a small heatsink — at 50 fires/sec under sustained dwell, dissipation is modest but still nonzero.

### Sync Strategy (Strategy B: Missing-Tooth Reduction Ring Gear)

The chosen and only strategy for this build is **Strategy B — missing tooth on the dry-clutch reduction ring gear**. The Hall sensor mounted on the back face of the clutch assembly reads each iron tooth as it passes; one tooth is filed off so the firmware can detect the long gap and anchor crank position to it. There is no magnet on the gear and no separate trigger wheel.

How it works:
- The ring gear has `physical_teeth` teeth originally and is driven from the crank through a `reduction_ratio` (typical 3:1 to 5:1 for kit engines). The effective edges per CRANK revolution is `teeth_per_rev = physical_teeth / reduction_ratio`. Worked example: 84 physical teeth × 4:1 reduction → `teeth_per_rev = 21`.
- After modification, `teeth_per_rev - 1` edges occur per crank rev, with one ~`missing_tooth_ratio`× longer interval where the filed gap passes the sensor.
- The missing tooth is filed at an angular position that puts its leading edge at (or close to) crank TDC, so that the FIRST edge after the gap is the sync reference.
- The ECU firmware now detects the long-gap interval directly. In `CRANK_GEAR_LAYER.on_edge`, AFTER the debounce check and BEFORE the range check, it tests `dt_us > tooth_period_us × missing_tooth_ratio`. If that condition is true and a stable `tooth_period_us` has been established, the firmware resets `tooth_index = sync_tooth_index`, updates the EMA period, and returns `GEAR_EDGE_REFERENCE`. This makes the reference edge pin directly to the gap on every revolution rather than walking around the gear modulo N.

ECU config (place these via Dash settings or the runtime config protocol):
- `teeth_per_rev = physical_teeth / reduction_ratio` — the EFFECTIVE per-crank-rev tooth count, with the un-filed physical count in the numerator. Default placeholder: 21.
- `sync_tooth_index = 0` — the index assigned to the first edge after the gap. (You can choose any index 0..teeth_per_rev-1; 0 keeps the math obvious.)
- `sync_edges_to_lock = 8` — wait this many consistent edges before declaring SYNCED.
- `tooth_min_us = 300` — must be < normal tooth period at redline. At 21 teeth/crank-rev and 9500 RPM the normal period is `60_000_000 / (9500 × 21) ≈ 301 µs`, so 300 leaves a hair of margin (re-tune to ~250 if measurement jitter approaches 300).
- `tooth_max_us = 8000` — bounds NORMAL teeth only. The missing-tooth gap is captured by the new `missing_tooth_ratio` path BEFORE the range check, so this no longer needs to cover the gap. 8000 µs at 21 teeth corresponds to a normal tooth at ~340 RPM crank — generous enough for vigorous pedal cranking.
- `missing_tooth_ratio = 1.8` — multiplier applied to the running EMA tooth period. The first edge whose `dt_us` exceeds `tooth_period_us × 1.8` is taken as the post-gap reference. Range 1.2..3.0; clamp the lower end if your gear is uniform enough that 1.5 still resolves cleanly, raise it if normal teeth occasionally jitter. Adjustable from the Dash menu under EMTR.
- `debounce_us = 40` — rejects sub-edge ringing without losing real teeth.

Sanity formulas (check these whenever you change `teeth_per_rev`):
```
tooth_min_us  <  60_000_000 / (peak_RPM × teeth_per_rev)
tooth_max_us  >  60_000_000 / (min_normal_cranking_RPM × teeth_per_rev)
missing_tooth_ratio  >  1.2          (else normal tooth jitter trips it)
missing_tooth_ratio  <  2.0          (else a real gap might not exceed it)
```

Pros (vs. the alternatives below): high angular resolution (~17° per tooth at `teeth_per_rev = 21` — coarser than the original 90-tooth assumption but still sufficient for 2-stroke timing), full programmable advance, no magnet hardware, sensor is fully enclosed inside the clutch assembly and protected from the engine bay.

Cons: irreversible gear modification, requires a degree wheel for filing alignment.

#### Firmware Status — Missing-Tooth Detection

The earlier limitation note ("gear layer cannot anchor `sync_tooth_index` to the gap") is **resolved**. `CRANK_GEAR_LAYER.on_edge` now performs explicit gap detection using `missing_tooth_ratio` before the range check. Bench-validate sync behaviour with a multi-tooth target (or a signal generator simulating the gap) before connecting any coil load — the procedure is unchanged, but the ECU should now reach SYNCED instead of flickering.

#### Footnotes — Alternative Strategies (NOT used in this build)

These are recorded only as reference for future builds. They are not the chosen path.

- **Strategy A (single magnet, 1 pulse/rev).** Glue one neodymium magnet to the clutch face. Hall sees one pulse per revolution. ECU config: `teeth_per_rev = 1`, `tooth_min_us = 1500`, `tooth_max_us = 60000`, `missing_tooth_ratio = 3.0` (effectively disables gap detection). Lower resolution; useful for first-light bring-up but not chosen here.
- **Strategy C (separate 36-1 trigger wheel).** Bolt a fabricated 36-1 wheel to the flywheel and read it with an external Hall. Equivalent firmware setup to Strategy B but adds a flywheel modification and external sensor mount. Not chosen because the existing dry-clutch reduction ring gear is already accessible inside the clutch cover.

### Mechanical Mounting (Back Face of the Clutch Assembly)

The crank/gear sensor is a back-biased Hall effect sensor mounted on the **back face of the clutch assembly**, NOT through the outer clutch cover. The sensor body sits inside the assembly so it does not protrude externally; only the cable exits, via a rubber grommet through the case wall. The sensor tip faces the inner side of the outer ring gear and reads the gear teeth as they pass. The OEM CDI is removed entirely; the magneto leads are repurposed for coil power supply only.

**Clutch assembly modification procedure:**

1. Remove the clutch cover and access the clutch assembly's back face. Note original gasket condition and order a replacement cover gasket.
2. Measure the crank-to-ring-gear reduction ratio per the procedure in the "Reduction-Ratio Measurement Procedure" section above. Mark crank + ring gear, rotate the crank by hand, count crank revolutions per one full ring gear revolution. Record both `physical_teeth` (count of ring gear teeth) and `reduction_ratio` in the build log. Update `teeth_per_rev = physical_teeth / reduction_ratio` in the ECU config.
3. Pick a sensor mounting location on the back face of the clutch assembly (inner side):
   - Sensor tip faces the inner OD of the ring gear with 0.5-1.5 mm air gap when the assembly is fully installed.
   - Mounting bracket and sensor body sit ENTIRELY inside the assembly — nothing protrudes externally. Cable runs along the inside, exits the engine case through a rubber grommet (M8 or M10 cable gland with rubber bushing).
   - Mounting boss is in the upper half of the assembly where it stays clear of the oil pool (the dry clutch is unlubricated, but residual oil fog accumulates at the bottom).
   - Sensor body and cable do not foul any rotating part — verify clearance with the assembly off but the clutch fully assembled by rotating slowly.
4. Drill and tap the back face of the clutch assembly for the chosen sensor body. For the A3144 (TO-92 epoxy package, no native mount):
   - Build a small aluminium L-bracket; bond the A3144 plus its back-bias magnet to one face with thermally-conductive epoxy (the magnet sits BEHIND the IC body, not on the gear side).
   - Bolt the bracket to the back face of the assembly with two M3 screws and thread-locker.
   - For 1GT101DC (M5/M8 threaded body), drill a stepped hole and lock with two M-nuts for fine air-gap adjustment.
5. Sensor cable runs along the inside of the assembly, exits the engine case through a rubber grommet in the case wall, flexible loop to the harness, then a Deutsch DT04-3P connector to the ECU enclosure. The grommet is the strain relief.

**Filing the sync tooth (the missing tooth):**

This is the irreversible step. Do it carefully and align with TDC.

1. Find TDC mechanically. Remove the spark plug, insert a piston-stop tool. Rotate the kickstart slowly until the piston is at the top. Mark this exact crank position on the flywheel and on the clutch (transfer the mark across to the gear face).
2. With the cover off, identify the tooth on the ring gear that aligns with the sensor at TDC. Mark it with paint.
3. Decide on alignment: align the LEADING edge of the missing-tooth gap so that the FIRST edge after the gap (the "next" tooth) passes the sensor exactly at TDC. This makes `sync_tooth_index = 0` correspond to TDC, which makes the firmware's `advance_cd` directly meaningful as ° BTDC.
4. File or grind down the marked tooth flush with the root of the surrounding teeth. Use a fine file, take small passes, and check air-gap clearance frequently. The goal is a clean ~2× tooth-width gap, NOT a partial tooth that could produce a weak/marginal edge.
5. Deburr and clean the gear thoroughly. Steel filings on a Hall sensor are a permanent failure mode.
6. Reassemble. Confirm the sensor still has 0.5-1.5 mm air gap at the unfiled teeth.

**Air gap calibration:**

1. Bolt the cover up with the modified gear and sensor in place.
2. Pull recoil slowly or roll the bike in gear so the gear turns by hand.
3. Scope the sensor output at the ECU end — should be clean rectangular 0/3.3 V transitions on each tooth, with one wider LOW (or HIGH, depending on sensor polarity) interval where the missing tooth sits. No chatter.
4. If amplitude is weak: reduce air gap toward 0.5 mm.
5. If chatter or false triggers: increase gap toward 1.5 mm or check shielding.
6. Final gap is whatever produces clean signal across the full RPM range; verify under fast hand-spinning if possible, or with a drill on the kickstart shaft.

**Verifying sync alignment with a strobe (recommended before first start):**

1. Wire a timing strobe to the spark plug lead.
2. Start the engine on a known-conservative advance map (e.g., 5° BTDC fixed across the RPM range).
3. Aim the strobe at the flywheel TDC mark.
4. The mark should appear ~5° before the case-side timing mark. If it appears at TDC or after, your filed-tooth alignment is off by one tooth — you must either re-zero `sync_tooth_index` (one tooth = 360°/teeth_per_rev ≈ 17° at `teeth_per_rev = 21`, software-correctable) or re-mark and re-file (irreversible). Note: with the lower angular resolution of a reduction-gear setup, a one-tooth offset is more visible on the strobe than it was for the previous 90-tooth assumption — but the correction step is the same.

Magneto wiring (power only): the existing 2 magneto leads emerge from the engine case. Both go to the ECU enclosure as a silicone-jacketed twisted pair (no shielding strictly needed since they only carry rectifier input, not signal). At the ECU enclosure they enter the bridge rectifier inputs. The OEM CDI is binned.

**Vibration management:**
- Magneto wires emerge into a hot, vibrating zone. Use silicone-jacketed wire rated ≥ 150 °C.
- Strain-relief at both ends. A loose wire flapping at 50-150 Hz fundamental will work-harden and crack within hours.
- Sensor cable: shielded twisted pair, shield grounded at ECU end only.
- Sensor body: thread-locker on every fastener. Vibration on these engines reaches the kHz range.

### Power Architecture for Motorized Bicycle

The Pico ECU and Dash are powered ONLY by the Li-ion 1S 7000 mAh pack (per the generic Hardware Design section). The magneto powers the ignition coil's primary supply and nothing else.

Why this split:
- The Pico must boot BEFORE the engine cranks. At rest, the magneto produces zero power. Battery-only boot is mandatory.
- Once running, the magneto can sustain the coil indefinitely. The Pico continues to run from battery.
- Battery never directly powers the coil — that would require a buck-boost from 3.7 V to ~12 V at 5 W peak, which is unnecessary complexity when the magneto already provides 6-30 V naturally.

Charging the Li-ion (pick ONE):

**Option A — Off-bike USB charging (recommended for prototype).**
- TP4056 module (single-cell Li-ion charger, USB-C input).
- Mount a USB-C bulkhead connector on the bike (waterproof type if outdoor).
- Plug in to charge between rides.
- 7000 mAh ÷ ~150 mA average system draw = ~46 hours runtime per charge. Plenty for a prototype.

**Option B — On-bike charging from a separate magneto winding.**
- ONLY if the magneto has a separate lighting winding (independent of the coil-supply winding).
- The user has confirmed this magneto has NO separate lighting coil — Option B is not available on this engine.
- Stick with Option A.

The Li-ion supply chain after the BMS is identical to the generic Hardware Design section — boost to 5 V per Pico, etc.

### Kill-Switch Topology (Mandatory Dual Path)

Two independent paths, both must work:

**Hardware kill (works with Pico dead):**

```
Handlebar kill switch (DPST, normally CLOSED = run, OPEN = kill)
   Pole 1: in series with the opto LED cathode
   Pole 2: in series with the GP14 → ECU input
```

When kill is pressed (poles open):
- Pole 1 breaks the opto LED current path. The opto receiver loses light, IGBT gate is forced LOW by the gate driver's pull-down. Coil cannot fire even if the Pico is firing pulses. This works with the Pico dead, runaway, or stuck-on.
- Pole 2 floats GP14, which is pulled UP internally → ECU enters INHIBIT mode within microseconds.

**Software kill (ECU enforced):**

The GP14 line is filtered with a 10 kΩ + 100 nF RC (debounces and rejects HF). When GP14 is high (pulled up internally) the ECU code refuses to schedule any fire events. This is the fastest path (sub-microsecond inhibit) but is not trustworthy on its own.

The hardware path is your real safety. The software path is for clean shutdown, fault-flag reporting, and Dash visibility.

Wire the switch as a 4-wire harness:
- Pole 1 input (common): logic GND
- Pole 1 output: opto LED cathode (in series)
- Pole 2 input (common): logic GND
- Pole 2 output: GP14 input

### Timing and Control Model (2-Stroke Specific)

The ECU firmware already implements the timing path. With Strategy B (multi-tooth reduction ring gear, one tooth filed off), the gear layer counts every tooth edge to maintain crank position. It emits one `GEAR_EDGE_REFERENCE` per crankshaft revolution — either when the explicit gap-detection path fires (long-period interval after the missing tooth), or when the modulo edge counter rolls over to `sync_tooth_index`. That one reference per rev anchors the fire-delay calculation:

```
fire_delay_us = rev_period_us - (rev_period_us × advance_cd / 36000)
```

where `rev_period_us` is the measured full crankshaft period (`tooth_period_us × teeth_per_rev`), and `advance_cd` is the desired advance in centidegrees from the lookup map. This is the formula in `arm_precision_from_edge` ([ecu/main.py](ecu/main.py)).

For TCI, the firmware also schedules the **dwell** event ahead of the fire:

```
on_time  = fire_time - dwell_us
```

`dwell_us` is interpolated from `dwell_map_rpm` / `dwell_map_us`. At low RPM (long period) the firmware caps dwell to avoid coil overheating; at high RPM it ensures enough flux builds before the fire event.

Note on the formula's TDC anchor: with `sync_tooth_index` aligned so the reference edge fires AT TDC, `advance_cd` is the actual ° BTDC at which the spark fires. The formula computes "fire `advance` degrees before the NEXT reference edge", which is the same as "fire `advance` degrees BTDC of the next TDC". If the reference edge is offset from TDC (e.g., one tooth early due to filing alignment error), the offset propagates as a constant additive bias to all advance numbers — correctable by adjusting `sync_tooth_index` by ±1 (one tooth ≈ 17° at `teeth_per_rev = 21`).

Worked example (Strategy B, `teeth_per_rev = 21` from 84 physical teeth × 4:1 reduction, sync tooth aligned to TDC, target advance 15° BTDC, 6000 RPM):

```
rev_period_us   = 60_000_000 / 6000             = 10_000 µs (one full crank rev)
tooth_period_us = rev_period_us / 21            ≈ 476 µs (per-tooth interval)
advance_cd      = 15° × 100                     = 1500
fire_delay_us   = 10_000 - (10_000 × 1500 / 36000)
                = 10_000 - 416                  = 9_584 µs
```

So at the reference edge (TDC), the firmware schedules fire 9 584 µs later — i.e., 416 µs before the NEXT reference edge — which is exactly 15° before the next TDC, i.e., 15° BTDC. The dwell event is scheduled `dwell_us` earlier than the fire.

At 9500 RPM with the same advance and `teeth_per_rev = 21`:
```
rev_period_us   = 60_000_000 / 9500             ≈ 6_316 µs
tooth_period_us ≈ 301 µs
fire_delay_us   = 6_316 - (6_316 × 1500 / 36000)
                ≈ 6_316 - 263                   ≈ 6_053 µs
```

Per-tooth ISR throughput at 9500 RPM × 21 = 3 325 edges/sec, one edge every ~301 µs — much lower than the previous 90-tooth assumption (~74 µs/edge), so the per-tooth ISR has comfortable headroom under `ISR_OVERRUN_LIMIT_US = 100`. The advance-map size is no longer ISR-throughput-limited at this geometry; the same defaults are kept for compatibility.

Critical rule for 2-stroke timing:
- Advance angle MUST decrease (retard) past peak power RPM. Over-advance at high RPM detonates the 2-stroke and destroys it. A typical curve for a kit 85cc:
  - 1500 RPM: 8° BTDC
  - 3000 RPM: 18° BTDC
  - 5000 RPM: 28° BTDC (peak)
  - 7000 RPM: 25° BTDC
  - 8500 RPM: 22° BTDC
  - 9000 RPM: 18° BTDC

These are class-typical numbers. Tune on YOUR engine using spark-plug colour and a knock listener.

Missed-pulse handling (already in ECU code):
- Sustained sync timeout (no edges within `SYNC_TIMEOUT_US = 250 ms`) → drop to SYNC_LOST → INHIBIT.
- Period plausibility violations stack into FAULT_EDGE_PLAUSIBILITY; degrade to SAFE mode after `MAX_UNSCHED_STREAK_PRECISION = 4` consecutive failures.
- After `sync_edges_to_lock` consecutive consistent edges → return to SYNCED → PRECISION mode.

Over-rev protection: set a hard rev limit in the ECU config. When measured RPM exceeds the limit, ECU enters INHIBIT and skips fire events. Recommended for Avenger 85 class: 9500 RPM.

### Engine Safety Constraints

Specific to 2-stroke kit engines with TCI ignition:

| Constraint | Value | Source |
|---|---|---|
| Max safe RPM | 9000-9500 | Bottom-end bearing fatigue limit |
| Max advance at any RPM | 35° BTDC | Detonation onset (typical) |
| Min advance allowed | 0° (TDC) | Below this → kickback risk on starting |
| Coil dwell range | 1.2-2.6 ms | Set in ECU `DWELL_MIN_US` / `DWELL_MAX_US` |
| Coil primary supply (from magneto rectifier) | 6-30 V DC | Below 6 V the dwell isn't enough; above 30 V the TVS clamps |
| Nominal supply at idle | ~8 V | Magneto output at 1500 RPM cranking |
| Trigger-to-fire latency budget | < 200 µs | LEAD_GUARD_FIRE_US, hard-coded in firmware |

### Step-by-Step Build Procedure (TCI, Crank-Sensor Driven)

Follow stages in order. Do not skip ahead.

**Stage 1 — Power and Pico bring-up.** Per the generic Hardware Design bring-up. Both Picos boot from Li-ion → boost → VSYS. REPL works. No resets under load.

**Stage 2 — UART link.** Build the harness, verify Dash shows L+ and engine values display (RPM = 0, sync = LOST since no crank pulses yet).

**Stage 3 — Crank sensor bench validation (off engine).**
- Mount the Hall sensor (with back-bias magnet for the A3144) and conditioner on a benchtop fixture.
- Power the sensor from ECU 3V3.
- Wave a small steel screwdriver across the sensor tip — output should pulse cleanly. Scope the conditioner output: rectangular 0/3.3 V transitions, no chatter.
- Connect to ECU GP2.
- Strategy B exercise (recommended bench step before the engine arrives): build a small turntable or use a stepper-driven shaft with a fabricated multi-tooth target plate (e.g., a 3D-printed disc with 21 ferrous inserts and one missing — match whatever `teeth_per_rev` you intend to ship). Spin it at a known RPM. Set `teeth_per_rev` to match, `sync_tooth_index = 0`, `missing_tooth_ratio = 1.8`. Confirm Dash shows the expected RPM and sync advances LOST → SYNCING → SYNCED. Confirm the Dash main screen "ADV XX.XXd" tracks the configured advance map at the spinning RPM.
- Quick smoke test if no multi-tooth fixture is available: temporarily set `teeth_per_rev = 1`, `missing_tooth_ratio = 3.0` (effectively disable gap detection), and pulse one steel target past the sensor by hand at ~1 Hz; Dash should show ~60 RPM. **Revert `teeth_per_rev` and `missing_tooth_ratio` back to the engine values before continuing** — the rest of the build assumes Strategy B.

**Stage 4 — Magneto-rectifier bench substitution.**
- Build the bridge rectifier + bulk cap + TVS.
- Feed bench DC supply (start at 6 V) into the rectifier output. Confirm bulk cap charges.
- Ramp bench DC up to 30 V. TVS should clamp around 50 V; below 33 V it stays off. No thermal issues.
- This validates the magneto power path without needing the engine.

**Stage 5 — TCI driver bench test (no coil).**
- Build the GP15 → opto → gate driver → IGBT chain.
- Substitute coil primary with a 100 Ω / 25 W power resistor.
- Substitute magneto rectifier output with bench DC at 12 V.
- Substitute crank sensor with a signal generator at ~50 Hz (or a button to GP2).
- ECU enters PRECISION mode. Scope the IGBT collector: should show ~12 V → ~0 V transitions matching the configured dwell + advance.
- Verify the gate goes LOW when GP14 (kill switch) is asserted.
- Verify the gate goes LOW when ECU is power-cycled.
- Verify the gate goes LOW when the kill-switch breaks the opto LED current path (hardware kill).

**Stage 6 — Real coil bench test.**
- Replace 100 Ω resistor with the actual ignition coil.
- Spark plug bolted to a grounded heatsink. Plug GROUND ONLY (NOT in cylinder yet).
- Bench DC at 12 V substituting for magneto.
- Inject simulated crank pulses. Confirm spark on the plug.
- Use a timing strobe simultaneously to verify the spark angle relative to a marker on a turning stub shaft (or trust the ECU's commanded delay if you don't have a strobe yet).

**Stage 7 — Mount on engine, magneto power, NO COIL FIRE.**
- Open the clutch cover and **measure the reduction ratio** per the procedure in "Reduction-Ratio Measurement Procedure" — mark the crank, mark a tooth on the ring gear, rotate the crank by hand, count crank revs per one ring gear rev. Record `physical_teeth` and `reduction_ratio` in the build log. Update `teeth_per_rev = physical_teeth / reduction_ratio` in the ECU config.
- File the chosen sync tooth flat as described in "Mechanical Mounting". Deburr and clean thoroughly.
- Install the Hall sensor (A3144 with back-bias, or 1GT101DC) on the **back face of the clutch assembly** (sensor body inside, cable exits via grommet); verify air gap 0.5-1.5 mm at every tooth and at the gap.
- Reassemble the clutch cover with a fresh gasket.
- Connect magneto AC leads to the bridge rectifier input.
- KILL SWITCH ACTIVE (opto LED open).
- Pull recoil or push the bike in gear by hand. Sensor should pulse `teeth_per_rev - 1` times per crank revolution with one wider gap. **Watch the ECU onboard LED** (GP25): slow blink = SYNC_LOST, fast blink = SYNC_SYNCING, solid = SYNC_SYNCED. Dash also shows RPM advancing LOST → SYNCING → SYNCED.
  - If sync never reaches SYNCED or flickers, open the FLOG screen on the Dash (OK_LONG → RIGHT). The structured fault log gives the specific bit (e.g. `EDGE BAD`, `SYNC UNSTABLE`), the RPM and tooth period at the moment the fault was raised, and an occurrence counter — much more diagnostic than the old hex bitmap.
- Verify rectifier output rises with cranking speed (scope or DMM).
- Confirm NO spark on the plug despite the trigger pulses (kill switch isolates).

**Stage 8 — First spark on engine (NO FUEL).**

This is **pedal-start** territory: the rider pedals the bike (or pulls recoil) for several crank revolutions before the clutch dumps and the engine actually fires. SYNC_SYNCING and IGN_MODE_SAFE firing during the initial acquisition window is **expected and normal** — the firmware needs `sync_edges_to_lock` consistent edges before it will declare SYNC_SYNCED. The rider's job is to watch the **ECU onboard LED** (GP25, visible through a small light pipe / clear epoxy window in the ECU enclosure) during pedal-up and wait for solid-on before dumping the clutch:

| LED state | Sync state | What to do |
|---|---|---|
| Slow blink (~600 ms period) | SYNC_LOST | Keep pedaling; sensor not yet seeing teeth |
| Fast blink (~220 ms period) | SYNC_SYNCING | Sensor is seeing teeth but firmware has not locked yet — keep pedaling |
| Solid on | SYNC_SYNCED | Lock acquired — dump the clutch now for best first-start behaviour |

The engine WILL also catch in IGN_MODE_SAFE if the clutch is dumped during SYNCING (the ECU runs a fixed `safe_fire_delay_us` from each reference edge until precision lock is reached). Waiting for SYNCED gives a cleaner first ignition because precision-mode timing is map-driven instead of fixed.

The ECU LED is the **primary** sync status indicator during pedal-up — the rider does not need to look at the Dash to know when to dump the clutch. The Dash mirrors the same state in its top-left "SY" badge but the LED is faster to glance at and works even if the OLED is off.

Procedure:

- Plug installed in cylinder, spark plug wire connected. Fuel tap OFF.
- Set advance map to ONE conservative point: 5° BTDC at 1500 RPM, INHIBIT above 2500 RPM.
- Release kill switch. Pedal up (or pull recoil briskly). Watch the ECU LED progress: slow blink → fast blink → solid. Dump the clutch on solid. You should hear/see spark inside the cylinder.
- **Verify spark angle with a timing strobe** (critical — this is the sync-alignment check). Strobe should freeze the flywheel TDC mark at ~5° before the case-side mark. If the offset is wrong by an integer multiple of `360°/teeth_per_rev` (≈ 17° at `teeth_per_rev = 21`), adjust `sync_tooth_index` by ±1 via Dash settings and retest. If the offset is non-integer or unstable, the missing-tooth detection is misfiring — stop, raise `missing_tooth_ratio` (Dash → EMTR) one notch, and retry. Cross-check the FLOG screen for any `EDGE BAD` or `SYNC UNSTABLE` entries.
- Reapply kill switch, leave for next stage.

**Stage 9 — Idle on fuel.**
- Replace plug, fuel tap ON, choke as needed.
- Set advance map: 8° BTDC at 1500 RPM, 12° BTDC at 2500 RPM, INHIBIT above 3000 RPM.
- Release kill switch. Start engine via recoil. Idle for 30 seconds.
- Watch Dash for fault flags. `FAULT_UNSTABLE_SYNC` or repeated `FAULT_EDGE_PLAUSIBILITY` here usually means a marginal sensor air gap or a dirty filed-tooth gap — shut down and inspect.
- Listen for engine note.
- Shut off (kill switch), let cool, retighten anything that worked loose.

**Stage 10 — Tune up to mid-RPM.**
- Expand advance map up to 5000 RPM with conservative numbers per the timing-curve table above.
- Run progressively higher with no engine load (in neutral / clutch disengaged).
- At any sign of audible detonation or fault flag, back off advance at the offending RPM band.

**Stage 11 — Tune under load.**
- Mount on bike if not already. Ride in lowest gear, light throttle.
- Watch Dash for fault flags and RPM stability.
- Tune advance map upward in mid-range only after confirming no detonation under load.

**Stage 12 — Final commissioning.**
- Save validated profile via Dash COMMIT.
- Verify the ECU loads it on next boot.
- Document the final advance map in your build log.

### Final Validation Checklist (TCI Build)

Tick before first engine start:

Electrical safety:
- [ ] BMS overvoltage cutoff verified at 4.25 V
- [ ] BMS undervoltage cutoff verified at 2.7-3.0 V
- [ ] BMS short-circuit cutoff verified
- [ ] Battery fuse blown intentionally on a test rig (own bench, not on bike)
- [ ] Reverse-polarity P-FET tested with reversed input
- [ ] Hardware kill switch breaks opto LED path when pressed (gate forced LOW)
- [ ] Hardware kill switch tested with Pico unplugged (kill must still work)
- [ ] Software kill (GP14) inhibits fires in software (verify by injecting GP2 pulses with GP14 grounded, observe IGBT gate stays LOW)

Grounding:
- [ ] ECU GND wire goes directly to BAT NEG STAR (own conductor)
- [ ] Dash GND wire goes directly to BAT NEG STAR (own conductor)
- [ ] IGBT emitter wire goes directly to BAT NEG STAR (own conductor)
- [ ] Bridge rectifier DC− wire goes directly to BAT NEG STAR (own conductor)
- [ ] Engine block bonded to BAT NEG STAR with one short heavy wire
- [ ] No shared GND conductor between Domain A (ignition) and Domain B (logic)
- [ ] Sensor cable shields tied at one end only

EMI mitigation:
- [ ] HT plug lead routed at least 100 mm from sensor cables and UART harness
- [ ] All sensor cables shielded twisted pair
- [ ] Ferrite beads on UART harness near each board
- [ ] All input power has TVS, ferrite, and electrolytic + ceramic filter
- [ ] No wires running across or alongside the exhaust pipe

Ignition isolation:
- [ ] Opto-isolator (6N137) installed between Pico GP15 and gate driver
- [ ] Opto isolation voltage rating verified (≥ 2500 V) on datasheet
- [ ] No copper bridges between Domain A and Domain B except at the BAT NEG STAR
- [ ] IGBT collector-to-emitter TVS clamp installed (or IGBT has internal flyback diode)
- [ ] Gate has 10 kΩ pull-down to emitter (gate fail-safe)

Sensor reliability:
- [ ] Reduction ratio measured directly (mark + count crank revs per ring gear rev) and recorded in build log
- [ ] Ring gear physical tooth count verified by visual count and recorded in build log
- [ ] `teeth_per_rev` in active profile = `physical_teeth / reduction_ratio` (NOT physical_teeth, NOT physical_teeth - 1)
- [ ] Filed sync tooth aligned with TDC ± one tooth; alignment verified by strobe at first start
- [ ] `sync_tooth_index` set so the first edge after the gap fires at TDC (default `0`)
- [ ] `tooth_min_us` < normal tooth period at redline (e.g., < 301 µs at `teeth_per_rev=21`, 9500 RPM); default `300` is OK at the worked example
- [ ] `tooth_max_us` only needs to bound NORMAL teeth — the missing-tooth gap is captured by `missing_tooth_ratio` BEFORE the range check
- [ ] `missing_tooth_ratio` (Dash EMTR) tuned so a real gap consistently triggers but normal-tooth jitter does not (default `1.8`, range 1.2..3.0)
- [ ] Hall sensor output verified clean on scope under hand-spinning the clutch — `teeth_per_rev - 1` pulses per crank rev, one wider gap, no chatter
- [ ] Sensor air gap confirmed at 0.5-1.5 mm at unfiled teeth AND at the gap
- [ ] Steel filings cleaned from inside clutch cover after gear modification
- [ ] Sensor mounted on back face of clutch assembly (not protruding externally); cable exits via rubber grommet, strain-relieved at the case wall
- [ ] Speed sensor frontend tested with magnet swept across by hand
- [ ] MAX6675 reads ambient temperature ±5 °C steady state

ECU failsafe:
- [ ] ECU enters INHIBIT mode when GP14 is held low
- [ ] ECU enters INHIBIT mode when fault_bits ≠ 0
- [ ] Rev limit enforced at 9500 RPM in active profile
- [ ] Geometry-changed configs trigger reboot-required flag
- [ ] Profile saves to `ecu_profile.json` AND `ecu_profile.bak.json`
- [ ] Backup recovery tested (delete primary, verify restore from backup)
- [ ] No `FAULT_ISR_OVERRUN` observed on Dash FLOG screen at 9000+ RPM during bench rev sweep (per-tooth ISR work + per-rev reference path stays under `ISR_OVERRUN_LIMIT_US`)

Mechanical:
- [ ] ECU enclosure rubber-isolated from engine case
- [ ] Dash enclosure rubber-isolated from handlebars
- [ ] Battery pack shock-mounted in fish-paper-lined case
- [ ] Hall sensor mounted with thread-locker, O-ring sealed against clutch cover
- [ ] All cable entries strain-relieved through M12 cable glands
- [ ] Conformal coating applied to perfboard PCBs

Pre-ride:
- [ ] Build log up to date with measurements at each stage
- [ ] Spare cell + spare fuse + spare IGBT carried on first ride
- [ ] Eye protection and fire extinguisher present at first start
- [ ] Stock CDI binned (or set aside; do NOT keep in the bike's electrical bay where it could be confused-wired)



Common frame format:
- Start bytes: 0xAA 0x55
- Header:
  - major (u8)
  - minor (u8)
  - msg_type (u8)
  - seq (u16 LE)
  - ecu_time_ms (u32 LE)
  - payload_len (u16 LE)
- Payload: TLV list
- CRC16-CCITT (u16 LE), computed over header+payload (not start bytes)

Message types:
- 1: MSG_TYPE_ENGINE_STATE
- 2: MSG_TYPE_CONFIG_SET
- 3: MSG_TYPE_CONFIG_RESPONSE

Engine-state TLVs:
- 1 RPM u16
- 2 Sync state u8
- 3 Ignition mode u8
- 4 Fault bits u32
- 5 Validity bits u16
- 6 Speed x10 i16 (optional)
- 7 Temp x10 i16 (optional)
- 8 ECU cycle id u32
- 9 Spark counter u32
- 10 Ignition output u8
- 11 Fault log (optional, omitted entirely if no faults). Variable length:
  N entries × 20 bytes, where N is 1..8. Each entry is packed little-endian:
  `fault_bit u32 | rpm u16 | tooth_period_us u32 | avg_period_us u32 | timestamp_ms u32 | count u16`.
  ECU adds a new entry the first time a `fault_bit` is raised; subsequent
  occurrences of the same bit increment `count` and refresh `timestamp_ms`
  + the captured RPM/tooth_period/avg_period in place. The ring buffer
  holds up to 8 unique fault bits.

Config TLVs:
- 1 Mode u8 (PREVIEW=0, APPLY=1, COMMIT=2)
- 2 JSON payload (utf-8)
- 3 Status u8 (OK=0, REJECTED=1, DEFERRED=2)
- 4 Flags u16
- 5 Active profile CRC16 u16
- 6 Status text (utf-8)

## ECU Config Model and Persistence

Location:
- ecu/config_layer.py

Persistent files on ECU filesystem:
- ecu_profile.json (active)
- ecu_profile.bak.json (backup)
- ecu_profile.tmp.json (temp write)

Default profile fields and shipped values (Strategy B — multi-tooth reduction ring gear with one tooth filed):
- schema = 1
- teeth_per_rev = 21 (worked-example placeholder = 84 physical teeth / 4:1 reduction; confirm both numbers when the engine is opened)
- sync_tooth_index = 0 (the first edge after the missing-tooth gap)
- tooth_min_us = 300 (covers `teeth_per_rev=21` at 9500 RPM with a thin margin)
- tooth_max_us = 8000 (bounds NORMAL teeth only — generous enough for ~340 RPM crank during pedal start; the missing-tooth gap is captured by `missing_tooth_ratio` BEFORE the range check, so this no longer needs to cover the gap interval)
- missing_tooth_ratio = 1.8 (multiplier applied to running EMA tooth period; first edge whose dt exceeds `tooth_period × ratio` is taken as the post-gap reference and resets `tooth_index` to `sync_tooth_index`)
- debounce_us = 40
- sync_edges_to_lock = 8
- safe_fire_delay_us = 2500
- safe_dwell_us = 1700
- advance_map_rpm / advance_map_cd
- dwell_map_rpm / dwell_map_us

Sanitize/clamp rules include:
- teeth_per_rev: 8..240
- sync_tooth_index: 0..teeth_per_rev-1
- tooth_min_us: 20..20000
- tooth_max_us: 200..500000 and > tooth_min_us
- debounce_us: 10..5000
- sync_edges_to_lock: 1..64
- missing_tooth_ratio: 1.2..3.0 (float)
- safe_fire_delay_us: 500..25000
- safe_dwell_us: 800..4000
- map domains are clamped and normalized (sorted, dedup x)

Sanity rules for `tooth_min_us` / `tooth_max_us` / `missing_tooth_ratio` at multi-tooth setups:
```
tooth_min_us         <  60_000_000 / (peak_RPM × teeth_per_rev)
tooth_max_us         >  60_000_000 / (min_normal_cranking_RPM × teeth_per_rev)
missing_tooth_ratio  >  ~1.2  (else normal tooth jitter trips it)
missing_tooth_ratio  <  ~2.0  (else a real gap might not exceed it)
```
With explicit gap detection now implemented, `tooth_max_us` only bounds NORMAL teeth. A long-period interval that exceeds `tooth_period_us × missing_tooth_ratio` is taken as the missing-tooth reference BEFORE the range check fires, so the gap no longer needs to fit under `tooth_max_us`.

Apply behavior (ecu/main.py):
- PREVIEW: validate/sanitize only
- APPLY: queue and apply in safe window (runtime only)
- COMMIT: apply + persist when eligible
- Geometry-changed configs set reboot-required flag

## Dash Settings and ECU Config UI

Settings count: 19 entries.

Local Dash entries:
- DBNC: rpm_debounce_us (2000..9000, step 100)
- RPPR: rpm_pulses_per_rev (1..4, step 1)
- WHL: wheel_size_mm (1000..3000, step 10)
- SPPR: speed_pulses_per_rev (1..20, step 1)
- RBAR: rpm_bar_max (4000..20000, step 500)
- DBG: debug overlay toggle
- DEMO: demo mode toggle

ECU-edit entries (sent over UART):
- ECTH: ecu_teeth_per_rev (8..240)
- ESYN: ecu_sync_tooth_index (0..teeth-1)
- EMIN: ecu_tooth_min_us (20..20000, step 10)
- EMAX: ecu_tooth_max_us (200..500000, step 100)
- ESFD: ecu_safe_fire_delay_us (500..25000, step 100)
- ESDW: ecu_safe_dwell_us (800..4000, step 50)
- EMTR: missing_tooth_ratio (1.2..3.0, step 0.1) — gap-detection threshold
- ECMT: commit action with confirm

Other menu actions:
- TMAP: open the timing-map editor
- RSET: reset settings defaults (confirm)
- TRIP: read-only trip display
- TCLR: trip clear (confirm)

### Main screen layout

- Top: RPM bar (x=4..99) and ECU badge (text "ECU" at x=100..123, status square at x=124..127). The badge no longer overlaps the bar or its tick marks.
- Middle: large speed digits with "km/h" suffix.
- Bottom-left: **live commanded ignition advance** (replaces the previous odometer display). Format `ADV XX.XXd` showing the advance in degrees (centidegrees / 100). When the link is lost or RPM is invalid: `ADV --.-d`. When `ignition_mode == INHIBIT`: `ADV INH`. When `ignition_mode == SAFE`: `ADV SAF`. The dash recomputes this locally by interpolating the cached advance map at the current RPM — no extra TLV is added to the wire. The odometer is still persisted (`trip_mm`/`odo_mm` written to `dashboard_settings.json`) and is shown on the info screen; only the main-screen position has changed.
- Bottom-right: temperature.

### Fault log screen (FLOG)

The fault log screen replaces the previous direct info → graph jump in the dash navigation. Navigation chain:

```
main  --(OK_LONG)-->  info  --(RIGHT)-->  flog  --(RIGHT past last entry)-->  graph
                                                  --(LEFT past first entry)--> info
                                                  --(OK)----------------------> main
```

Inside FLOG:
- LEFT/RIGHT pages through entries (one fault per screen).
- OK exits to main.
- If the log is empty, the screen shows `FLOG CLEAR` and RIGHT goes directly to graph.

Each populated screen shows:
- Row 1: `FLOG N/M` — entry index / total populated entries.
- Row 2: short fault name.
- Row 3: plain-English description.
- Row 4: RPM at fault (`R<rpm>`), instantaneous tooth period at fault (`TP<microseconds>`).
- Row 5: occurrence count (`N<count>`) and seconds since last occurrence (`T-<seconds>s`, computed against the ECU's own clock).

Plain-English fault descriptions:

| Fault bit | Short name | Description |
|---|---|---|
| FAULT_SYNC_TIMEOUT (1<<0) | SYNC TIMEOUT | No teeth seen >250ms |
| FAULT_EDGE_PLAUSIBILITY (1<<1) | EDGE BAD | Implausible tooth edge |
| FAULT_UNSCHEDULABLE (1<<2) | UNSCHED | Fire delay too short |
| FAULT_STALE_EVENT (1<<3) | STALE FIRE | Missed fire window |
| FAULT_ISR_OVERRUN (1<<4) | ISR SLOW | ISR took >20us |
| FAULT_SAFETY_INHIBIT (1<<5) | KILL ACTIVE | Kill switch open |
| FAULT_UNSTABLE_SYNC (1<<6) | SYNC UNSTABLE | Noise on crank signal |

## Operating Modes

Dash modes:
- Main screen
- Info screen (OK_LONG from main)
- Fault log screen (RIGHT from info)
- Graph screen (RIGHT from fault log; or RIGHT from fault log when log is empty)
- Settings screen (OK from main)

ECU sync/mode states:
- Sync: LOST, SYNCING, SYNCED
- Ignition: INHIBIT, SAFE, PRECISION

### ECU Onboard LED (GP25) — Sync Status Indicator

The ECU firmware drives the GP25 onboard LED to mirror the current sync state. This is the **primary** sync indicator during pedal-up bring-up — a rider can read it at a glance from the saddle without looking at the Dash.

| LED pattern | Sync state | Period |
|---|---|---|
| Slow blink | SYNC_LOST | ~600 ms |
| Fast blink | SYNC_SYNCING | ~220 ms |
| Solid on | SYNC_SYNCED | n/a |

Pedal-start workflow: the rider pedals the bike (or pulls recoil); the engine sees multiple crank revolutions before the clutch dumps and the engine fires. SYNC_SYNCING and IGN_MODE_SAFE firing during this acquisition window is expected and normal — the firmware needs `sync_edges_to_lock` consistent edges before it declares SYNC_SYNCED. Wait for the LED to go solid before dumping the clutch for the cleanest first ignition (precision-mode, map-driven timing). The engine WILL also catch in SAFE mode if the clutch is dumped earlier (fixed `safe_fire_delay_us`), but SYNCED is preferable.

This behaviour is implemented entirely in `led_tick()` in `ecu/main.py` and requires no Dash interaction. Make sure the ECU enclosure has a small light pipe or clear epoxy window so GP25 is visible.

## Programming and Flashing

## Prerequisites

- MicroPython installed on each Pico
- USB connection to each board
- mpremote (recommended)

Install mpremote:

```bash
python -m pip install mpremote
```

## Deploy ECU Pico

From repository root:

```bash
mpremote connect COMx fs cp ecu/config_layer.py :config_layer.py
mpremote connect COMx fs cp ecu/main.py :main.py
mpremote connect COMx reset
```

Replace COMx with ECU board serial port.

## Deploy Dash Pico

From repository root:

```bash
mpremote connect COMy fs cp dash/main.py :main.py
mpremote connect COMy reset
```

Replace COMy with Dash board serial port.

## Deploy Legacy Single-Pico Variant

```bash
mpremote connect COMz fs cp main.py :main.py
mpremote connect COMz reset
```

## Runtime Configuration Workflow

1. On Dash, open settings and adjust ECU fields (ECTH..ESDW).
2. Press OK to exit menu to send APPLY.
3. Use ECMT entry to send COMMIT when ready.
4. If response indicates reboot required, reboot ECU Pico.

Status text:
- Shown in ECMT label suffix.
- Derived from ECU config response TLV text/status.

## Bench Testing (No Bike / No ECU)

Dash-only bench mode:
- Enable DEMO in settings.
- Demo now drives display getters in telemetry mode even when no ECU is connected.
- Link indicator may still reflect no live telemetry, but RPM/speed/temp demo values animate.

## Troubleshooting

### OLED freezes while Pico remains powered

- Use built-in recovery path:
  - show_oled_safe() -> recover_oled() -> reset_oled()
- reset_oled() performs:
  - optional I2C deinit
  - optional I2C bus unstick pulses
  - optional hardware reset-pin pulse (if OLED_RESET_PIN configured)
  - OLED driver re-init and blank frame push

### Menu appears unresponsive

- Buttons are active-low and edge-triggered.
- Confirm one side of each button is tied to GND.
- Confirm correct GPIO mapping GP6..GP10.

### Dash cannot receive telemetry

- Verify cross-over UART wiring and shared ground.
- Confirm both sides at 230400 baud.
- Confirm no pin conflicts with other devices.

### ECU config not applying

- APPLY/COMMIT may be deferred until safe window.
- Geometry changes intentionally return reboot-required.
- Check ECMT status text and flags.

### Startup crashes about timers

- Dash uses a timer factory fallback across IDs to handle firmware differences.
- If needed, reduce active timers in custom forks.

## Safety Notes

- ECU controls ignition output; Dash is proposal-only.
- Keep safety inhibit input functional and tested.
- Validate coil driver hardware with proper flyback/protection design.
- Do not test ignition outputs against live engine hardware without isolation and protection.

## Quick Bring-up Checklist (Dual Pico)

1. Flash MicroPython to both boards.
2. Deploy ECU files (ecu/main.py + ecu/config_layer.py).
3. Deploy Dash file (dash/main.py).
4. Wire UART cross-over and shared GND.
5. Power Dash + OLED + buttons and verify menu/graphics.
6. Power ECU and verify telemetry link indicator on Dash.
7. Adjust one ECU setting from Dash and confirm response status updates.
8. Commit and reboot ECU if flagged reboot-required.

## Document Change Log

- 2026-04-24
  - Added full dual-Pico architecture documentation.
  - Added protocol/TLV definitions and config apply semantics.
  - Added flashing/deployment procedures for ECU and Dash.
  - Added OLED reset/recovery and bench/demo troubleshooting notes.
  - Added ECU onboard debug LED behavior and explicit UART direction reminder.

- 2026-04-25
  - Added Dual-Pico Hardware Design (Prototype) section: power, ignition driver, crank/speed/temp frontends, UART harness, grounding, BOM, safety, bring-up procedure.
  - Revised Hardware Design for 1S Li-ion 7000 mAh battery and per-Pico boost-to-5V regulation; clarified three-domain architecture (Ignition / Logic / Sensor) and ground-star rules; expanded BMS, bring-up, and safety procedures.
  - Added 2-Stroke Application Manual (Avenger 85 class): SCR-CDI driver chain replacing TCI, magneto pickup as crank source with `teeth_per_rev=1`, dual-path kill switch, 2-stroke timing model with worked examples, 10-stage build procedure, full validation checklist.
  - Revised 2-Stroke Application Manual for **2-wire single-coil magneto** (no separate pickup): HV wire dual-tapped for cap charging AND timing reference via comparator + opto, ECU sees one rising edge per revolution, max advance equals magneto's natural angle (must be measured on real engine, not in stock CDI). Documented optional Hall trigger disc as a future upgrade path.
  - Replaced the 2-Stroke Application Manual with a **full ECU replacement** topology: stock CDI removed entirely, Hall crank sensor through modified clutch cover is the sole timing source, magneto repurposed as ignition coil power supply only, TCI driver chain (IGBT + gate driver + opto) matching the existing TCI-architected ECU firmware. Updated mechanical mounting, kill-switch dual path (software + hardware via opto LED break), timing model with worked examples mapped to the real `arm_precision_from_edge` formula, 12-stage build procedure, and TCI-specific validation checklist.

- 2026-04-26
  - Committed to **Strategy B (missing-tooth ring gear) as the only sync strategy** for the 2-stroke build. Rewrote the Sync Strategy, Crank Sensor, and Mechanical Mounting sections to describe an internal Hall sensor (Allegro A3144 with back-bias magnet, or 1GT101DC) reading the dry-clutch outer ring gear with one tooth filed off as the sync feature. Strategy A and C demoted to short reference footnotes.
  - Added a Firmware Limitation note: `CRANK_GEAR_LAYER` currently counts edges modulo `teeth_per_rev` and does not yet detect the long missing-tooth gap. Strategy B will require a small gear-layer enhancement (gap-driven `tooth_index` reset) before precision-mode timing can be trusted; the limitation is flagged inline in the build procedure (Stage 7) and in the validation checklist.
  - Updated default profile values for multi-tooth operation: `teeth_per_rev = 90` (placeholder, confirm on engine arrival), `tooth_min_us = 50`, `tooth_max_us = 30000`. Updated `GEAR_DEFAULT_*` constants in `ecu/main.py`, the `default_profile()` payload in `ecu/config_layer.py`, and the matching boot/reset defaults in `dash/main.py` so all three sides agree.
  - Bumped ECU `ISR_OVERRUN_LIMIT_US` from 20 µs to 100 µs to accommodate 80-100 teeth/rev edge throughput at redline (per-tooth ISR work plus the per-rev reference path with two `_interp_map` calls).
  - Fixed `mul_div_smallint` to round toward zero for negative `advance_cd` values (previously used Python floor division, which biased negative advance by ~1 µs and made positive/negative advance asymmetric).
  - Removed redundant `sanitize_profile` calls on save: refactored `ecu/config_layer.py` to compute CRC over already-clean profiles via a new internal `_crc_for_clean` / `_atomic_write_clean` helper. `save_profile_pair` now sanitizes once and writes twice instead of three sanitizes per write × two writes.
  - Added worked-example math and ISR-throughput notes for N=90, 9000 RPM in the Timing and Control Model section. Added reference to filing-alignment offset correction by ±1 in `sync_tooth_index` (one tooth ≈ 4° at N=90).

- 2026-04-27
  - **Architecture correction — reduction gear ratio.** The earlier assumption that the dry-clutch ring gear rotates at crank speed (1:1) was wrong. The ring gear is a REDUCTION gear and rotates slower than the crank by some 3:1..5:1 ratio (to be measured on engine arrival). Rewrote Sync Strategy, Crank Sensor, Mechanical Mounting, Timing and Control Model, default profile, and validation checklist to use `teeth_per_rev = physical_teeth / reduction_ratio`. Added an explicit Reduction-Ratio Measurement Procedure (mark crank + ring gear, rotate crank by hand, count crank revs per ring gear rev). Worked-example placeholder is now 84 physical teeth × 4:1 reduction → `teeth_per_rev = 21`, `tooth_min_us = 300`, `tooth_max_us = 8000`.
  - **Implemented missing-tooth detection.** `CRANK_GEAR_LAYER.on_edge` now tests `dt_us > tooth_period_us × missing_tooth_ratio` AFTER debounce and BEFORE the range check. When that condition holds and a stable EMA tooth period has been established, the firmware resets `tooth_index = sync_tooth_index`, updates the period, and returns `GEAR_EDGE_REFERENCE` — pinning the reference edge directly to the gap on every revolution instead of walking modulo N. Crucial: the check runs BEFORE the range_streak counter increments, so the gap interval no longer accumulates toward `GEAR_ERR_RANGE`. Added `missing_tooth_ratio` to the profile schema (clamp 1.2..3.0, default 1.8) and to the Dash menu as `EMTR` (step 0.1) and to the Dash → ECU config sender (`mtr` alias).
  - **Structured fault log.** Added a ring buffer of 8 fault entries on the ECU, populated inside `set_fault()` with the current RPM, instantaneous tooth period, EMA tooth period, ECU `ticks_ms`, and an occurrence count. Repeats of the same fault bit increment count and refresh in place. Added `TLV_FAULT_LOG (=11)` — variable-length, omitted entirely when no faults are populated; Dash `MAX_PAYLOAD_LEN` bumped from 128 to 256 to accommodate the fault log payload alongside the rest of engine state. Dash decodes the new TLV into `EngineSnapshot.fault_log` and exposes a new FLOG screen (one entry per page, paged with LEFT/RIGHT, OK exits). Navigation chain is now `info → flog → graph` instead of `info → graph` direct.
  - **Documented ECU LED sync indicator.** `led_tick()` was already implementing slow-blink / fast-blink / solid-on for SYNC_LOST / SYNC_SYNCING / SYNC_SYNCED. Added explicit documentation of this behaviour to the Operating Modes section and to the pedal-start procedure in the build manual — the ECU LED is the primary sync indicator during pedal-up; the rider waits for solid-on before dumping the clutch.
  - **Main screen layout.** Replaced the bottom-left odometer display with the live commanded ignition advance (`ADV XX.XXd`, with `ADV INH` / `ADV SAF` / `ADV --.-d` for non-precision states). The dash recomputes advance locally from the cached advance map and current RPM via a new `_interp_map` matching the ECU's algorithm — no new TLV. Odometer remains persisted and is shown on the info screen. Reduced `RPM_BAR_W` from 120 to 96 and moved the ECU badge status square to x=124 so the badge no longer overlaps the bar or its tick marks.
  - **Pedal-start guidance.** Added an explicit pedal-start section to the sync acquisition stage: the engine sees multiple crank revolutions before the clutch dumps; SYNC_SYNCING / IGN_MODE_SAFE firing during initial acquisition is expected and normal; the rider should watch the ECU LED and wait for solid (SYNCED) before dumping the clutch for best first-start behaviour, but the engine will also catch in SAFE mode if the clutch is dumped earlier.
  - **Sensor mounting clarification.** The Hall sensor is mounted on the BACK FACE of the clutch assembly (sensor body inside the assembly, cable exits via a rubber grommet) — it does not protrude externally and reads the ring gear teeth from the inner side. Updated mechanical mounting and validation checklist accordingly.
