# Bike2 ECU v2 — Hybrid C / PIO / MicroPython Architecture

> **Status:** design + skeleton implementation, pre-bring-up.
> The current `ecu/main.py` remains the bench reference until each migration stage's
> acceptance gate is met. See **Migration plan** at the bottom.

---

## 1. Root-cause analysis of the v1 (pure-MicroPython) failure modes

Measured (signal-generator bench, Hall input pin GP2):

| Tooth rate | Equivalent RPM (tpr=21) | Observed                             |
| ---------- | ----------------------- | ------------------------------------ |
| ~1.2 kHz   | ~3 400                  | ~1000 `FAULT_ISR_OVERRUN` /sec, ~50 `FAULT_STALE_EVENT` /sec |
| ~2.2 kHz   | ~6 300                  | UART telemetry stalls, runtime occasionally crashes outright |

Causes, in order of contribution:

### 1.1 The crank ISR runs through the MicroPython interpreter

`ecu/main.py:1357` registers `crank_isr` as a hard IRQ:

```python
crank_pin.irq(trigger=Pin.IRQ_RISING, handler=crank_isr, hard=True)
```

`hard=True` only means the callback runs in actual ISR context; the body
(`ecu/main.py:815-912`) is still MicroPython bytecode, decorated `@micropython.native`.
Even with native compilation, every operation pays interpreter cost an order of
magnitude above the equivalent C:

- `utime.ticks_us()` (`ecu/main.py:836`, `:910`), `ticks_diff()` (`:843`, `:910`),
  `ticks_add()` (`:891`, `:892`, `:900`, `:901`) — each is a C call wrapped by an
  interpreter-side argument marshal and a return value that allocates a small-int
  object on the MicroPython heap if it doesn't fit the cached small-int range.
- Globals are read on every reference. Lines 831-834 declare 11 `global` names; with
  `@micropython.native` these are resolved via a per-module dict lookup. Each lookup
  is single-digit-µs but occurs ~40 times per ISR invocation.
- The missing-tooth check `(dt * 10) > (period * g_mtr_x10)` (`ecu/main.py:856`) is
  two multiplications and a comparison; safe for small ints, but the products can
  exceed 30 bits at long periods and trigger big-int allocation, which can in turn
  trigger GC.
- The ISR itself includes the cost of measuring its own runtime
  (`utime.ticks_diff(utime.ticks_us(), now_us)` at `:910`) and a conditional fault
  counter increment.

End-to-end the ISR takes ~30–80 µs typical, with worst-case spikes >150 µs whenever
GC, a bigint allocation, or a soft-IRQ tail occurs concurrently. At 1.2 kHz tooth
rate the ISR is invoked every ~830 µs, so even short tail events leave too little
slack for the rest of the system to make progress.

### 1.2 Polling scheduler in a `machine.Timer` callback

`ecu/main.py:170,1369`:

```python
SCHEDULER_TICK_HZ = const(5000)            # 200 µs poll
scheduler_timer.init(freq=SCHEDULER_TICK_HZ, callback=scheduler_tick)
```

The comment at `ecu/main.py:168-169` already concedes the design limit:
*"Higher rates (10k+) overwhelm the soft-IRQ queue when telemetry/config TX run,
which is what was crashing UART."*

Each tick of `scheduler_tick` (`ecu/main.py:915-968`):

- Disables IRQs twice (`disable_irq()` at `:926`, `:948`) — gated windows of ~10 µs
  during which the crank ISR cannot run, *added on top of* the ISR's own runtime.
- Runs MicroPython bytecode for the conditional check and global writes.
- Calls `force_coil_off()` which itself does an attribute lookup and a method call
  through `Pin`.

At 5000 Hz this is an unconditional ~25–50 µs overhead per tick whether or not an
event is actually due. Combined with a 1.2 kHz crank ISR, the soft-IRQ queue and the
hard-IRQ queue together saturate a single Cortex-M33 core. At 2.2 kHz the crank ISR
alone consumes ~15–20 % of one core; the scheduler timer adds another ~25 %; the
200 Hz watchdog and 50 Hz telemetry timers add ~5 %. UART RX/TX share the same core
and are starved — *that is the 2.2 kHz UART crash mode*.

### 1.3 No hardware-event scheduling

There is no use of the SDK's `hardware_alarm` pool or PIO-driven timing. Every
ignition fire/dwell-on event is "delivered" by polling its scheduled timestamp from
within `scheduler_tick` (`ecu/main.py:927`, `:949`). Hence the `LATE_SLACK_US =
1500` (`:164`) — the design admits a 1.5 ms late tolerance because the scheduler
can't actually meet its own 200 µs tick window under load. That tolerance is the
direct cause of `FAULT_STALE_EVENT` being logged at ~50/sec.

### 1.4 Allocations on the IRQ path

Several MicroPython idioms in the soft-IRQ paths allocate:

- `set_fault()` at `ecu/main.py:444-483` indexes Python lists under
  `disable_irq()` (`:451`, `:483`). Each list indexing returns an interpreter-level
  object; if list grows or shrinks elsewhere, GC can be invoked.
- `_telemetry_uart_write()` at `ecu/main.py:1190` allocates a `memoryview` slice
  on every UART write attempt.
- `ConfigIngest._consume_frame` at `ecu/main.py:1218-1246` does several
  `bytearray` slice copies (`:1226`, `:1236`, `:1241`, `:1245`) per frame.
- `ujson.loads(...)` at `ecu/main.py:704` — config parse can allocate hundreds
  of small objects and trigger a multi-millisecond GC.

Any of these can collide with a crank edge. Even if no individual allocation blocks
the ISR, the *combination* with non-deterministic GC means the worst-case ISR
latency is essentially unbounded.

### 1.5 Why the 2.2 kHz UART crash specifically

At 2.2 kHz tooth rate the crank ISR is invoked every ~454 µs. The 5 kHz scheduler
tick every 200 µs means *between two crank edges, the scheduler timer fires twice*.
Each scheduler invocation re-arms IRQ-disable windows that delay the crank ISR;
each crank ISR delays the scheduler. The MicroPython soft-IRQ queue has finite
depth and accumulates pending callbacks. The main loop's `utime.sleep_ms(2)` at
`ecu/main.py:1418` lets ~5 crank edges pass between UART RX drain attempts, so the
UART RX hardware FIFO (configured `rxbuf=256` at `:1362`) overruns. The MP runtime
then either silently drops bytes (telemetry stalls) or, when soft-IRQ queue
overflow propagates as a `RuntimeError`, the firmware crashes.

### 1.6 Summary

The hot path is implemented in an interpreter that costs ~10× what the same path
costs in C, schedules events by polling instead of by hardware alarm, allocates on
multiple sub-paths, and shares one core with UART. This design cannot meet
real-time at engine-relevant tooth rates regardless of MicroPython tuning.

---

## 2. Architecture diagram

```
                             RP2350 (Pico 2)
   ┌────────────────────────────────────────────────────────────────────┐
   │                                                                    │
   │   ┌──────────────────────────┐        ┌────────────────────────┐   │
   │   │ Core 0 — MicroPython     │        │ Core 1 — C real-time   │   │
   │   │                          │        │                        │   │
   │   │ • UART telemetry TX      │        │ • Crank decode         │   │
   │   │ • UART config RX/parse   │        │ • Sync state machine   │   │
   │   │ • Profile sanitize/save  │        │ • Advance map interp   │   │
   │   │ • Profile push to C core │        │ • Fire/dwell scheduler │   │
   │   │ • Telemetry pull from C  │        │ • Soft tick @ 1 kHz    │   │
   │   │ • LED, debug             │        │ • Safety inhibit poll  │   │
   │   │                          │        │                        │   │
   │   │   ┌──────────────────────┴────────┴───────────────────┐    │   │
   │   │   │             SHARED RAM (ipc_t)                    │    │   │
   │   │   │  • telemetry_block (seqlocked, C writes, MP reads)│    │   │
   │   │   │  • profile_shadow[2] + active_idx (MP writes,     │    │   │
   │   │   │    C reads — pointer swap)                        │    │   │
   │   │   │  • fault_ring (lock-free SPSC, C writes, MP reads)│    │   │
   │   │   │  • cmd_block (MP writes, C reads — soft inhibit,  │    │   │
   │   │   │    reset, etc.)                                   │    │   │
   │   │   └───────────────────────────────────────────────────┘    │   │
   │   └──────────────────────────┘        └────────────────────────┘   │
   │                                                  ▲                 │
   │                                                  │ FIFO IRQ        │
   │                                                  │                 │
   │                                  ┌───────────────┴────────────────┐│
   │                                  │ PIO0 SM0 — crank_capture       ││
   │                                  │ • Wait rising edge GP2         ││
   │                                  │ • Push 32-bit ticks to RX FIFO ││
   │                                  │ • One word per tooth edge      ││
   │                                  └────────────────┬───────────────┘│
   │                                                   │                │
   │  GP15 (coil drive) ◀── alarm_pool callback ◀──────┤                │
   │                                                   │                │
   └───────────────────────────────────────────────────┼────────────────┘
                                                       │
                                                  GP2 (Hall in)
```

Data-flow rules:

- **Crank edges** never enter the CPU through a GPIO IRQ. The PIO state machine
  timestamps them in hardware; the FIFO wakes Core 1 via a DMA transfer or PIO
  IRQ. The CPU reads N pre-timestamped edges in a tight loop.
- **Coil GPIO** is driven by C alarm callbacks scheduled at a known absolute
  64-bit timestamp. No polling; alarms are queued in the SDK's alarm pool and
  fire at hardware-level precision (sub-µs).
- **Profile updates** from MP go through a double-buffered shadow region. C
  swaps the active pointer once per soft tick, so a profile update never tears
  a fire-delay computation in progress.
- **Telemetry** is published by C using a seqlock pattern (see §IPC contract).
  MP reads opportunistically without blocking C.

---

## 3. New file layout

```
ecu_v2/
├── ARCHITECTURE.md             ← this document
├── CMakeLists.txt              ← top-level build glue (Pico SDK + MP user C)
├── c_core/
│   ├── ecu_types.h             ← shared enums (sync state, ignition mode, faults)
│   ├── ipc.h                   ← shared-RAM struct definitions; seqlock helpers
│   ├── ipc.c                   ← seqlock impl, shadow swap, ring push/pop
│   ├── crank.h                 ← crank decoder API
│   ├── crank.c                 ← tooth → angle, missing-tooth, sync state machine
│   ├── scheduler.h             ← scheduler API
│   ├── scheduler.c             ← hardware-alarm fire/dwell scheduling
│   ├── ignition.h              ← coil GPIO API
│   ├── ignition.c              ← coil drive + force-off + safety override
│   ├── safety.h
│   ├── safety.c                ← safety-inhibit pin polling
│   ├── faults.h
│   ├── faults.c                ← fault bit + fault ring helpers
│   ├── advance_map.h
│   ├── advance_map.c           ← rpm→advance_cd / rpm→dwell_us interpolation
│   ├── ecu_core.h
│   ├── ecu_core.c              ← init, core1 entry, soft tick
│   └── crank_capture.pio       ← PIO program (rising-edge timestamp capture)
└── micropython/
    ├── ecu_native.c            ← MicroPython native module (Python bindings)
    ├── micropython.cmake       ← USER_C_MODULES include
    ├── main.py                 ← boot, telemetry framing, config TLV
    └── config_layer.py         ← copied from ecu/ — schema preserved verbatim
```

Module responsibilities (one line each):

- `ecu_types.h` — Enums and constants shared between C core and Python bindings.
- `ipc.h/.c` — The single struct that lives at a fixed RAM address; all cross-core
  and cross-language traffic goes through here.
- `crank.h/.c` — Drains the PIO FIFO, runs the missing-tooth state machine,
  publishes RPM/sync state into the IPC block.
- `scheduler.h/.c` — Owns the hardware-alarm pool; arms a (dwell-on, fire) pair
  for each reference edge.
- `ignition.h/.c` — Lowest-level coil GPIO. Force-off path is callable from any
  context.
- `safety.h/.c` — Reads the inhibit pin in the soft tick; sets a flag the
  crank decoder honors before arming any alarm.
- `faults.h/.c` — Bit set + ring buffer push (lock-free SPSC).
- `advance_map.h/.c` — Pure-function interpolation against the active profile.
- `ecu_core.h/.c` — Wires PIO + DMA + IRQs + alarm pool, launches Core 1.
- `crank_capture.pio` — One state machine: wait rising edge, push timestamp.
- `ecu_native.c` — Thin Python bindings: `start()`, `read_state()`,
  `set_profile()`, `set_advance_map()`, `drain_faults()`, `set_inhibit()`.
- `micropython/main.py` — UART TLV framing, identical wire protocol to v1; no
  ignition-path code.

---

## 4. IPC contract (the ONE shared struct)

All cross-core traffic lives in a single `volatile ipc_t` instance at a fixed
linker-known symbol. No mutexes — we use:

- **seqlock** for telemetry: writer increments seq → writes → increments seq.
  Reader samples seq before+after, retries if the seq changed or is odd.
- **shadow + commit** for profiles: MP writes the inactive shadow, sets a
  pending-commit flag; C swaps active pointer on the next soft tick boundary
  (between fire events).
- **SPSC ring** for faults: producer (C) advances head, consumer (MP) advances
  tail. Both indices are 32-bit atomics.
- **single writer per field** for cmd_block: MP-only writes, C-only reads.

See `c_core/ipc.h` for layout, `c_core/ipc.c` for primitives.

---

## 5. C core ISR/scheduler invariants (the only things that matter for safety)

Every one of these must be true at all times, or the design is rejected:

1. The crank-capture path (PIO → CPU) does **no allocation** and uses **no FP**.
2. `scheduler_arm_fire()` writes both alarm slots **before** enabling them, so
   the alarm pool callback can never fire with a half-written event.
3. The fire alarm callback runs `coil_off()` *first*, then increments
   `spark_counter`. If anything panics in between, the coil ends up off.
4. The dwell-on alarm callback double-checks `cycle_id` matches the cycle the
   alarm was armed in. A new reference edge that arrives early will have
   bumped `cycle_id`, which invalidates the stale on-event before it can fire
   into a window that already has a fresh schedule.
5. Safety inhibit is checked in three places: (a) soft tick, (b) immediately
   before arming a new pair, (c) inside the dwell-on alarm callback. Any one
   of them seeing inhibit = no spark.
6. The IGBT GPIO is configured with `GPIO_PULLDOWN` and the bring-up sequence
   sets it low *before* enabling the alarm pool. If C panics, the SDK's
   default exception handler resets — pulldown holds it low through reset.

---

## 6. PIO program (crank_capture.pio)

One state machine, one program, ~5 instructions:

```
.program crank_capture
.wrap_target
    wait 0 pin 0      ; wait for low (debounce floor — optional, see crank.c)
    wait 1 pin 0      ; wait for rising edge
    in   pins, 1      ; shift edge bit (always 1) just to consume input
    mov  isr, !null   ; load 0xFFFFFFFF — sentinel ignored on CPU side
    push noblock      ; push event marker; CPU reads cycle counter on its side
.wrap
```

Why this minimal design and not a full hardware timestamp: the PIO state machine
clock can be made identical to the system 64-bit timer by clock division, but
sampling the timer in PIO requires extra instructions and introduces a 1-cycle
ambiguity. Instead we let the **PIO IRQ wake the CPU within 1–2 µs of the edge**
and the CPU samples the 64-bit timer at the top of the IRQ handler. The error
this introduces is bounded by IRQ entry latency (~1 µs on RP2350 at 150 MHz),
which is below our 10 µs scheduling resolution.

If 1 µs of jitter ever proves to be the bottleneck, the program can be replaced
with a full hardware-timestamping variant that pushes the PIO timer divider
counter. The interface to `crank.c` (one 32-bit word per edge) is unchanged.

DMA vs. FIFO IRQ: at the maximum sustained tooth rate of 5 kHz the FIFO never
exceeds 1–2 entries. We use the FIFO not-empty IRQ directly; DMA would add
latency without benefit.

---

## 7. MicroPython interface (ecu_native.c)

Surface area:

| Python call                                | Effect                                              |
| ------------------------------------------ | --------------------------------------------------- |
| `ecu.start()`                              | Boots PIO + alarm pool, launches Core 1             |
| `ecu.stop()`                               | Halts Core 1, force-off coil                        |
| `ecu.read_state() -> dict`                 | Seqlock-safe snapshot of telemetry                  |
| `ecu.set_profile(dict)`                    | Atomically install a new profile (shadow + commit)  |
| `ecu.set_advance_map(rpm, cd)`             | Replace advance map only                            |
| `ecu.set_dwell_map(rpm, us)`               | Replace dwell map only                              |
| `ecu.drain_faults() -> list[dict]`         | Pop everything from the fault ring                  |
| `ecu.set_inhibit(bool)`                    | Soft inhibit (in addition to hardware pin)          |
| `ecu.profile_crc16() -> int`               | CRC of the active profile, for the dash response    |

All Python-callable functions take a copy of inputs into the C-side staging
buffer and return immediately. None of them block on the C core. None of them
disable IRQs.

---

## 8. Migration plan (with bench-test gates)

Each stage MUST pass its acceptance gate on the signal generator before the
next stage starts. The gates re-use the existing fault ring so the v1 dash
firmware can read the result unchanged.

### Stage 0 — Lock down the bench harness

- **Action:** Stand up a repeatable test rig using the signal generator.
  Document waveform parameters per scenario (steady 1.2 kHz, steady 2.2 kHz,
  ramp 500→2500 Hz over 10 s, missing-tooth pattern with 84 teeth and one
  gap). Capture v1 numbers as the baseline.
- **Gate:** Reproduce the documented v1 failure rates within ±20 %
  (~1000 ISR overruns/sec @ 1.2 kHz, UART crash @ 2.2 kHz). If you cannot
  reproduce, the bench setup is wrong; **do not proceed**.

### Stage 1 — PIO crank capture under unmodified MicroPython

- **Action:** Replace the GPIO IRQ in v1 with a tiny native C helper that runs
  the PIO program and exposes a "tooth_event_count" counter and last-tooth
  timestamp via memory-mapped RAM. The existing Python ISR becomes a soft
  tick that drains accumulated events.
- **Why this stage:** Validates the PIO program in isolation and proves the
  PIO→CPU plumbing works before any decoder rewrite.
- **Gate:** 1.2 kHz signal-generator input held for 10 minutes shows zero
  PIO FIFO overruns. The fault count for `FAULT_ISR_OVERRUN` may still be
  non-zero (Python soft tick is still there) but should be visibly lower.

### Stage 2 — Move tooth decode and sync state machine into C

- **Action:** Compile `crank.c` as part of the MicroPython native module.
  Replace `g_*` Python globals with reads from the IPC block. The Python
  side still owns the scheduler.
- **Gate:** 2.5 kHz steady input held for 30 minutes. Sync state must remain
  `SYNCED` continuously. `FAULT_EDGE_PLAUSIBILITY` count must be zero.

### Stage 3 — Move scheduling into C with hardware alarms

- **Action:** Compile `scheduler.c` and wire it to the SDK alarm pool. The
  Python `scheduler_tick` Timer is **deleted** entirely.
- **Gate:** 5 kHz steady input held for 30 minutes. Zero `FAULT_STALE_EVENT`,
  zero `FAULT_UNSCHEDULABLE` (with default profile and a synthetic advance
  map), measured spark count exactly equal to expected (1 per missing-tooth
  reference per gap, count via DMM frequency on coil pin or LA).

### Stage 4 — Run the full C core on Core 1

- **Action:** Move all of `ecu_core.c` to Core 1 via `multicore_launch_core1`.
  Core 0 runs only MicroPython (UART, config, telemetry framing).
- **Gate:** 5 kHz steady input AND simultaneous saturation of the UART link
  (continuous 50 Hz telemetry plus a synthetic config-blast loop), held for
  30 minutes. Same zero-fault criteria as Stage 3.

### Stage 5 — Swap profiles under load

- **Action:** Have the dash push profile updates at a high rate while the
  signal generator runs the ramp scenario. Validate the shadow+commit
  pattern: each push must either apply cleanly or be rejected with a clear
  status; no half-applied profile must ever reach the scheduler.
- **Gate:** 1000 profile pushes during a 5 kHz signal-generator run; spark
  count remains exact, no fault counts increment.

### Stage 6 — First hardware bring-up

- **Action:** Wire the breadboarded ignition driver chain (opto → TC4427 →
  IGBT → coil) and replay the same signal-generator scenarios with the coil
  driving a real load. Verify with an oscilloscope on the IGBT collector.
- **Gate:** Every spark visible on the scope at the expected delay relative
  to the synthesized crank edge, ±20 µs.

### Stage 7 — On-engine

- **Action:** Install on the Avenger 85. Pedal-up to running.
- **Gate:** Engine starts. Steady-state idle holds with no fault counts.
  Pull rider-visible LED logic forward from v1 unchanged.

If any stage's gate is not met, do not paper over the fault: revert to the
previous stage and diagnose. The bench is the source of truth, not the
on-engine behavior — getting bench-clean before install is what makes this
migration safe.
