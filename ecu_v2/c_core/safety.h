#ifndef ECU_SAFETY_H
#define ECU_SAFETY_H

#include <stdbool.h>

/* Safety inhibit: hardware pin (GP14, active-low) OR'd with a software
 * inhibit set by MicroPython (cmd_block.soft_inhibit). Either active =>
 * no spark.
 *
 * The hardware pin is configured with internal pull-up so an unconnected
 * pin reads as 1 (NOT inhibited). To inhibit, the kill switch shorts
 * GP14 to GND. */

void safety_init(void);

/* True iff inhibit is currently active (either source). */
bool safety_inhibit_active(void);

#endif /* ECU_SAFETY_H */
