#ifndef ECU_CRANK_H
#define ECU_CRANK_H

#include "ecu_types.h"
#include "hardware/pio.h"
#include <stdint.h>
#include <stdbool.h>

/* Crank decoder. Owns the PIO IRQ handler and the soft tick that updates
 * the public sync state.
 *
 * Hot path (PIO IRQ):
 *   - Sample timer
 *   - Pop FIFO entries (1 to N at a time)
 *   - For each entry: debounce + missing-tooth + range + tooth-index advance
 *   - On reference edge: scheduler_arm_for_reference()
 *   - Update tooth-period EMA
 *
 * No allocation, no FP, no string ops, no logging. */

/* Initialize the decoder. Must be called after ipc_init() and before the
 * PIO IRQ is enabled. */
void crank_init(void);

/* Stash the PIO instance + state machine the crank ISR should drain.
 * Called from ecu_core.c after the PIO program is loaded but before the
 * PIO IRQ is enabled. */
void crank_set_pio(PIO pio, uint sm);

/* PIO RX-FIFO-not-empty IRQ handler. Wired in ecu_core.c. Drains the FIFO,
 * processes every queued tooth event. */
void crank_pio_isr(void);

/* Soft tick: 1 kHz. Owns sync timeout, sync state machine, range/noise
 * promotion to faults, RPM publish (via ipc_telemetry seqlock).
 *
 * Runs from a repeating SDK alarm so it is itself in IRQ context but at
 * a known low rate. Safe to call ipc_fault_push() from here. */
void crank_soft_tick(uint64_t now_us);

/* Reset all real-time gear state. Called from soft tick on sync loss /
 * fault recovery, and from the C side of the MP cmd_reset path. */
void crank_reset_state(void);

/* Maintenance accessors used by scheduler.c (no IPC indirection in the
 * hot path; scheduler reads these directly via inlining). */
uint32_t crank_tooth_period_us(void);
uint32_t crank_current_rpm(void);
sync_state_t crank_sync_state(void);
ignition_mode_t crank_ignition_mode(void);

/* For tests/diagnostics. */
uint32_t crank_isr_overrun_count_take(void);

#endif /* ECU_CRANK_H */
