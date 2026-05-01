#ifndef ECU_SCHEDULER_H
#define ECU_SCHEDULER_H

#include "ecu_types.h"
#include <stdint.h>
#include <stdbool.h>

/* Hardware-alarm-driven ignition scheduler.
 *
 * Uses the SDK's `alarm_pool` API. Two alarms per fire cycle:
 *   - dwell_on_alarm  : turns coil ON  (start charging)
 *   - fire_alarm      : turns coil OFF (collapse field — spark!)
 *
 * Each alarm carries a 32-bit "cycle_id" tag. On fire, the alarm callback
 * checks that cycle_id matches the latest scheduled cycle; if not, the
 * event is stale (a fresh reference edge already armed a newer cycle) and
 * we silently drop it. This avoids the v1 "polling-with-late-tolerance"
 * design that produces FAULT_STALE_EVENT under load.
 */

void scheduler_init(void);

/* Called by crank.c on each REFERENCE edge. Computes fire/dwell
 * timestamps, arms hardware alarms. Cancels any previously-armed pair
 * for an older cycle.
 *
 *   reference_edge_us : monotonic timer value at the reference edge
 *   cycle_id          : monotonically increasing per reference edge
 *   tooth_period_us   : EMA tooth period (used to compute rev_period)
 */
void scheduler_arm_for_reference(uint64_t reference_edge_us,
                                 uint32_t cycle_id,
                                 uint32_t tooth_period_us);

/* Cancel both alarms (dwell_on, fire). Coil is forced off if active.
 * Safe to call from any IRQ context. */
void scheduler_cancel_all(void);

/* True when no alarm is currently armed. Used by crank_soft_tick to
 * decide whether it's safe to swap the active profile shadow. */
bool scheduler_is_quiescent(void);

/* Spark counter — increments each time the fire alarm successfully
 * collapses the coil. Telemetry. */
uint32_t scheduler_spark_count(void);

/* Last computed advance, in centi-degrees. Telemetry. */
int16_t scheduler_current_advance_cd(void);

#endif /* ECU_SCHEDULER_H */
