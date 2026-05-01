#ifndef ECU_IGNITION_H
#define ECU_IGNITION_H

#include <stdbool.h>

/* Lowest-level coil GPIO control.
 *
 * IGBT gate is held LOW at boot (hardware pull-down) and any time the
 * Pico is in reset. The init function sets the pin direction and
 * explicitly drives low BEFORE any alarm pool is enabled. */

/* Initialize the coil drive pin (GP15). Drives output low. */
void ignition_init(void);

/* Begin coil charge (GP15 high). Called from dwell_on alarm callback. */
void ignition_on(void);

/* End coil charge / collapse field (GP15 low). Called from fire alarm
 * callback. Also called from any safety path. Idempotent. */
void ignition_force_off(void);

/* True if the coil pin is currently driven high. Telemetry. */
bool ignition_is_active(void);

#endif /* ECU_IGNITION_H */
