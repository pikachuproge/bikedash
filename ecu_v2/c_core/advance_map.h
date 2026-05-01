#ifndef ECU_ADVANCE_MAP_H
#define ECU_ADVANCE_MAP_H

#include "ipc.h"
#include <stdint.h>

/* Pure-function interpolation against a profile's advance and dwell maps.
 * No state of its own — fully reentrant. */

/* Returns advance in centi-degrees at the given RPM. Linear interpolation
 * between points; clamped to first/last point outside the range. */
int16_t advance_map_lookup_advance_cd(const ecu_profile_t *p, uint32_t rpm);

/* Returns dwell in microseconds at the given RPM. Same interpolation.
 * Clamped to [ECU_DWELL_MIN_US, ECU_DWELL_MAX_US]. */
uint32_t advance_map_lookup_dwell_us(const ecu_profile_t *p, uint32_t rpm);

#endif /* ECU_ADVANCE_MAP_H */
