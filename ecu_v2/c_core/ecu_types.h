#ifndef ECU_TYPES_H
#define ECU_TYPES_H

#include <stdint.h>
#include <stdbool.h>

/* Wire-protocol-visible enums.
 * These integer values MUST match ecu/main.py and dash/main.py exactly,
 * because they appear in TLV payloads on the UART link to the dash. */

typedef enum {
    SYNC_LOST    = 0,
    SYNC_SYNCING = 1,
    SYNC_SYNCED  = 2,
} sync_state_t;

typedef enum {
    IGN_MODE_INHIBIT   = 0,
    IGN_MODE_SAFE      = 1,
    IGN_MODE_PRECISION = 2,
} ignition_mode_t;

/* Fault bits — same as v1. Visible in TLV_FAULT_BITS_U32. */
#define FAULT_SYNC_TIMEOUT      (1u << 0)
#define FAULT_EDGE_PLAUSIBILITY (1u << 1)
#define FAULT_UNSCHEDULABLE     (1u << 2)
#define FAULT_STALE_EVENT       (1u << 3)
#define FAULT_ISR_OVERRUN       (1u << 4)
#define FAULT_SAFETY_INHIBIT    (1u << 5)
#define FAULT_UNSTABLE_SYNC     (1u << 6)

/* Validity bits — same as v1. */
#define VALID_RPM       (1u << 0)
#define VALID_SYNC      (1u << 1)
#define VALID_IGN_MODE  (1u << 2)
#define VALID_FAULTS    (1u << 3)
#define VALID_IGN_OUT   (1u << 4)
#define VALID_SPEED     (1u << 5)
#define VALID_TEMP      (1u << 6)

/* Profile geometry limits — match config_layer.sanitize_profile bounds. */
#define ECU_TPR_MIN              8
#define ECU_TPR_MAX              240
#define ECU_TOOTH_MIN_US_FLOOR   20
#define ECU_TOOTH_MAX_US_CEIL    500000
#define ECU_DEBOUNCE_US_FLOOR    10
#define ECU_DEBOUNCE_US_CEIL     5000
#define ECU_MTR_X10_MIN          12   /* 1.2 */
#define ECU_MTR_X10_MAX          30   /* 3.0 */
#define ECU_SAFE_FIRE_MIN_US     500
#define ECU_SAFE_FIRE_MAX_US     25000
#define ECU_SAFE_DWELL_MIN_US    800
#define ECU_SAFE_DWELL_MAX_US    4000

/* Map sizes (advance + dwell). Fixed maxima keep the IPC layout static. */
#define ECU_ADV_MAP_MAX          32
#define ECU_DWELL_MAP_MAX        16

/* Fault ring depth (power of two for cheap masking). */
#define ECU_FAULT_RING_LEN       32u
#define ECU_FAULT_RING_MASK      (ECU_FAULT_RING_LEN - 1u)

/* Soft tick rate — runs the sync state machine + RPM publish.
 * 1 kHz is plenty: 1 ms is far below the 250 ms sync timeout and well below
 * any human-perceivable response. */
#define ECU_SOFT_TICK_HZ         1000u

/* Hard limits the ignition path must obey. */
#define ECU_DWELL_MIN_US         1200u
#define ECU_DWELL_MAX_US         2600u
#define ECU_DWELL_TARGET_US      1800u

#define ECU_LEAD_GUARD_ON_US     200u
#define ECU_LEAD_GUARD_FIRE_US   200u
#define ECU_MIN_COIL_ON_US       400u

/* Sync timeout: no edges seen for this long => SYNC_LOST. */
#define ECU_SYNC_TIMEOUT_US      250000u

/* Lock-state thresholds. */
#define ECU_RANGE_STREAK_LIMIT   4
#define ECU_NOISE_STREAK_LIMIT   6

/* ISR overrun threshold (informational; we measure the C ISR runtime
 * each invocation and increment a fault count if it exceeds this). */
#define ECU_ISR_OVERRUN_LIMIT_US 30u

#endif /* ECU_TYPES_H */
