#ifndef ECU_CORE_H
#define ECU_CORE_H

#include <stdbool.h>
#include "pico/time.h"

/* The C real-time core entry point.
 *
 * ecu_core_start() initializes ALL hardware (ignition GPIO, safety pin,
 * PIO + state machine, alarm pool, soft tick), launches the C real-time
 * loop on Core 1, and returns immediately. After this returns, the
 * MicroPython runtime on Core 0 is free to run UART and config logic
 * with no further interaction with the ignition path.
 *
 * Idempotent: calling start() twice returns false the second time.
 *
 * ecu_core_stop() halts Core 1 and forces the coil off. Used for clean
 * shutdown / device-mode reset. */

bool ecu_core_start(void);
void ecu_core_stop(void);

/* Alarm pool created on Core 1. Used by scheduler.c so its hardware
 * alarms (dwell_on / fire) fire on Core 1 alongside the soft tick. */
alarm_pool_t *ecu_core_alarm_pool(void);

#endif /* ECU_CORE_H */
