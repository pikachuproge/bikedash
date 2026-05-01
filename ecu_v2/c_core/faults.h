#ifndef ECU_FAULTS_H
#define ECU_FAULTS_H

#include "ecu_types.h"
#include <stdint.h>

/* Fault tracking.
 *
 * faults_set() is safe to call from any C context. It sets the global
 * fault_bits mask AND pushes a structured entry into the IPC fault ring
 * (where MicroPython will drain it for telemetry).
 *
 * Repeat occurrences within a short window are coalesced — see
 * implementation. */

void faults_init(void);

/* OR a fault bit into the active mask and push/coalesce a ring entry. */
void faults_set(uint32_t bit);

/* Clear specific bits from the active mask. */
void faults_clear(uint32_t bits);

/* Clear ALL bits AND drain coalescing window. Used on cmd_reset. */
void faults_clear_all(void);

/* Read current bitmask. */
uint32_t faults_get(void);

#endif /* ECU_FAULTS_H */
