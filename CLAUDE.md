# Bike2 Project — Claude Code Context

## What this is
Custom dual-Pico ignition ECU system for an Avenger 85 2-stroke motorized bicycle.
Complete replacement of stock CDI. Hall sensor driven TCI ignition with programmable
advance map, OLED dashboard, and bidirectional UART config protocol.

## Repository Structure
- ecu/main.py          — ECU firmware (crank decode, ignition scheduling, telemetry TX, config RX)
- ecu/config_layer.py  — ECU profile schema, sanitize/clamp, CRC, atomic save + recovery
- dash/main.py         — Dash firmware (SSD1309 UI, buttons, telemetry RX, config TX, persistence)
- PROJECT_MANUAL.md    — Full system documentation (living document, always up to date)
- hardware/            — Wiring, BOM, legacy PCB files
- main.py              — Legacy single-Pico implementation (kept for compatibility, not active)

## Hardware
- 2x Raspberry Pi Pico 2 (RP2350), MicroPython
- ECU Pico: crank decode + ignition control
- Dash Pico: SSD1309 128x64 OLED I2C @ 1MHz, 5 buttons (GP6-GP10 active-low)
- UART between Picos: 230400 baud, GP0/GP1 (ECU) <-> GP4/GP5 (Dash), cross-over wired
- Dash overclocked to 266MHz

## ECU Pin Map
- GP2  — Crank pulse input (Hall A3144 via conditioner)
- GP14 — Safety inhibit (active-low kill switch)
- GP15 — Coil drive output (to opto → TC4427 → IGBT)
- GP25 — Onboard LED (sync state indicator)
- GP0  — UART0 TX to Dash
- GP1  — UART0 RX from Dash

## Dash Pin Map
- GP0/GP1  — I2C SDA/SCL (SSD1309)
- GP4      — UART1 TX to ECU
- GP5      — UART1 RX from ECU
- GP6-GP10 — Buttons UP/DOWN/LEFT/RIGHT/OK
- GP16-GP19 — SPI (MAX6675 thermocouple, legacy path)
- GP3      — Speed sensor input

## Crank Sync Strategy
Strategy B — Hall sensor (Allegro A3144 with back-bias magnet) mounted on the BACK
FACE of the dry clutch assembly, reading the reduction ring gear teeth from the
inner side. Sensor does NOT protrude externally; cable exits via rubber grommet.
One tooth filed off as the missing-tooth sync reference. NO magnet on gear.

CRITICAL: The ring gear is a REDUCTION gear, NOT 1:1 with the crank.
  teeth_per_rev = ring_gear_physical_teeth / reduction_ratio
  Worked example placeholder: 84 physical teeth / 4:1 reduction = teeth_per_rev=21
  Both numbers must be confirmed by measurement when engine arrives.

Missing tooth detection: CRANK_GEAR_LAYER.on_edge tests dt_us > tooth_period_us *
missing_tooth_ratio AFTER debounce, BEFORE range check. Triggers GEAR_EDGE_REFERENCE
and resets tooth_index = sync_tooth_index. Must fire BEFORE range_streak increments.

## ECU Default Profile (config_layer.py)
- teeth_per_rev = 21 (placeholder — confirm on engine)
- sync_tooth_index = 0
- tooth_min_us = 300
- tooth_max_us = 8000 (bounds NORMAL teeth only — gap caught by missing_tooth_ratio first)
- missing_tooth_ratio = 1.8 (clamp 1.2..3.0)
- debounce_us = 40
- sync_edges_to_lock = 8
- safe_fire_delay_us = 2500
- safe_dwell_us = 1700

## ECU Ignition Modes
- IGN_MODE_INHIBIT — no firing, coil off
- IGN_MODE_SAFE    — fixed safe_fire_delay_us from reference edge
- IGN_MODE_PRECISION — full advance map, map-driven timing

## ECU Sync States
- SYNC_LOST    — no edges seen, inhibit
- SYNC_SYNCING — edges seen but not yet locked (fires in SAFE mode)
- SYNC_SYNCED  — locked, fires in PRECISION mode

## ECU LED (GP25) — Sync Indicator
- Slow blink ~600ms = SYNC_LOST
- Fast blink ~220ms = SYNC_SYNCING
- Solid on           = SYNC_SYNCED
Rider watches LED during pedal-up, dumps clutch on solid.

## Ignition Driver Chain
GP15 → 220Ω → 6N137 opto (isolation barrier) → TC4427 gate driver → 10Ω → IGBT gate
IGBT: FGA25N120ANTD (1200V 25A, internal flyback diode)
Magneto AC → 4x UF4007 bridge → 220µF/63V cap → SMBJ33CA TVS → coil primary+
IGBT emitter → own dedicated wire → battery negative star point

## UART Protocol
Framed binary, CRC16-CCITT over header+payload (not start bytes).
Start: 0xAA 0x55
Header: major(u8) minor(u8) msg_type(u8) seq(u16LE) ecu_time_ms(u32LE) payload_len(u16LE)
Payload: TLV list
CRC: u16LE

Message types:
- 1 = MSG_TYPE_ENGINE_STATE (ECU → Dash)
- 2 = MSG_TYPE_CONFIG_SET   (Dash → ECU)
- 3 = MSG_TYPE_CONFIG_RESPONSE (ECU → Dash)

Engine state TLVs:
- 1  RPM u16
- 2  Sync state u8
- 3  Ignition mode u8
- 4  Fault bits u32
- 5  Validity bits u16
- 6  Speed x10 i16 (optional)
- 7  Temp x10 i16 (optional)
- 8  ECU cycle id u32
- 9  Spark counter u32
- 10 Ignition output u8
- 11 Fault log (optional, omitted if no faults)
     N entries x 20 bytes, packed LE:
     fault_bit(u32) | rpm(u16) | tooth_period_us(u32) | avg_period_us(u32) | timestamp_ms(u32) | count(u16)

Config TLVs (Dash → ECU):
- 1 Mode u8 (PREVIEW=0, APPLY=1, COMMIT=2)
- 2 JSON payload (utf-8, compact aliases: tpr/sti/tmin/tmax/sfd/sdw/amr/amc/mtr)

Config response TLVs (ECU → Dash):
- 3 Status u8 (OK=0, REJECTED=1, DEFERRED=2)
- 4 Flags u16
- 5 Active profile CRC16 u16
- 6 Status text utf-8

## Fault Bits
- FAULT_SYNC_TIMEOUT      (1<<0) — no teeth >250ms
- FAULT_EDGE_PLAUSIBILITY (1<<1) — implausible tooth edge
- FAULT_UNSCHEDULABLE     (1<<2) — fire delay too short
- FAULT_STALE_EVENT       (1<<3) — missed fire window
- FAULT_ISR_OVERRUN       (1<<4) — ISR took >100us
- FAULT_SAFETY_INHIBIT    (1<<5) — kill switch active
- FAULT_UNSTABLE_SYNC     (1<<6) — noise on crank signal

## Fault Log (ECU ring buffer, 8 entries)
set_fault() captures: fault_bit, rpm, tooth_period_us, avg_period_us, timestamp_ms, count.
Same fault bit repeating: increments count and refreshes fields in-place.
Transmitted as TLV_FAULT_LOG(=11) in engine state packet. Omitted entirely if empty.

## Display Layout (128x64 SSD1309)
- Top:          RPM bar (x=4 to ~96) — full width minus right margin for badge
- Top-right:    ECU link badge (status square only, does NOT overlap RPM bar)
- Middle:       Large speed digits + "km/h"
- Bottom-left:  Live ignition advance — format "XX.XX°" (centidegrees/100)
                States: "INH" (inhibit), "SAF" (safe mode), "--.-" (invalid/link lost)
                Computed locally on dash from cached advance map + current RPM
                NO new TLV — dash interpolates the map itself
- Bottom-right: Temperature ("XXC" or "--C")
- Top-left:     Sync/link status badge (small, does not overlap RPM bar)

## Dash Screen Navigation
main --(OK)--> settings
main --(OK_LONG)--> info --(RIGHT)--> flog --(RIGHT past last / empty)--> graph
                                           --(LEFT past first)--> info
                                           --(OK)--> main

## Dash Menu Entries (19 total)
Local: DBNC, RPPR, WHL, SPPR, RBAR, DBG, DEMO
ECU-edit: ECTH, ESYN, EMIN, EMAX, ESFD, ESDW, EMTR (missing_tooth_ratio, step 0.1)
Actions: TMAP (timing map editor), ECMT (commit), RSET (reset defaults), TRIP, TCLR

## Power System
- 1S Li-ion 3.7V 7000mAh + BMS (DW01A + 8205A)
- Each Pico: polyfuse → AO3401 P-FET → SMBJ5.0CA TVS → 22µH LC filter → Pololu U3V12F5 5V boost → VSYS
- Magneto powers ONLY the ignition coil primary (via bridge rectifier, not Pico)
- Three electrical domains: A=ignition, B=logic, C=sensors — star ground at battery negative
- Domain A return (IGBT emitter) runs on its own dedicated wire to battery negative star
- Optical isolation (6N137) is the ONLY link between Domain A and Domain B

## Critical Rules (never violate these)
1. Domain A return current NEVER flows on Domain B copper
2. Sensor cable shields grounded at ONE end only (the board that owns that sensor)
3. IGBT gate must default LOW at boot and when Pico is unplugged (10kΩ pull-down)
4. tooth_max_us bounds NORMAL teeth only — missing-tooth gap is caught by missing_tooth_ratio
5. Missing tooth detection fires BEFORE range_streak increments
6. teeth_per_rev = physical_teeth / reduction_ratio (NOT physical tooth count)
7. advance_cd is in centidegrees (divide by 100 for degrees)
8. Config changes with geometry impact are reboot-required — do not apply at runtime

## Known Code Issues / Watch Points
- MicroPython GC can pause a few ms — GC is run deterministically once/second in dash
  main loop gated on no pending config TX and no dirty settings
- ECU ISR must stay under 100us — verified by FAULT_ISR_OVERRUN flag
- advance_cd can be negative (retard) — clamp fire_delay_us to > 0 before scheduling
- I2C pull-ups must be 1kΩ-2.2kΩ at 1MHz (not the usual 4.7kΩ)
- SSD1309 clone risk: some modules are actually SSD1306 and cap at 400kHz

## Flashing
mpremote connect COMx fs cp ecu/config_layer.py :config_layer.py
mpremote connect COMx fs cp ecu/main.py :main.py
mpremote connect COMx reset

mpremote connect COMy fs cp dash/main.py :main.py
mpremote connect COMy reset

## Build Status
- Firmware: largely finalized, pending physical hardware testing
- Circuit: not yet built (parts not yet ordered)
- Engine: not yet acquired (arriving in Lithuania, summer 2026)
- Strategy: breadboard first → perfboard → install on bike in Lithuania