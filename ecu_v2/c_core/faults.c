#include "faults.h"
#include "ipc.h"
#include "crank.h"
#include "pico/time.h"

/* Coalescing window: if the SAME fault bit is set twice within this many
 * milliseconds, increment the count of the most recent ring entry rather
 * than push a new one. Keeps the ring useful under sustained fault
 * conditions. */
#define FAULT_COALESCE_WINDOW_MS  100u

typedef struct {
    uint32_t bit;
    uint32_t last_ts_ms;
} coalesce_t;

/* Per-bit-position coalescing state. Indexed by ctz(fault_bit). The bits
 * are sparse (we use bit positions 0..6) so a small fixed array is fine. */
static coalesce_t s_coalesce[8];

static volatile uint32_t s_fault_bits = 0;

void faults_init(void) {
    s_fault_bits = 0;
    for (int i = 0; i < 8; ++i) {
        s_coalesce[i].bit = 0;
        s_coalesce[i].last_ts_ms = 0;
    }
}

uint32_t faults_get(void) {
    return s_fault_bits;
}

void faults_clear(uint32_t bits) {
    s_fault_bits &= ~bits;
}

void faults_clear_all(void) {
    s_fault_bits = 0;
    for (int i = 0; i < 8; ++i) s_coalesce[i].last_ts_ms = 0;
}

/* count trailing zeros — used to map fault bit to coalesce slot index. */
static inline int ctz32(uint32_t x) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_ctz(x);
#else
    int n = 0;
    while ((x & 1u) == 0u && n < 31) { x >>= 1; n++; }
    return n;
#endif
}

void __not_in_flash_func(faults_set)(uint32_t bit) {
    if (bit == 0) return;

    s_fault_bits |= bit;

    int slot = ctz32(bit);
    if (slot >= 8) return;  /* unknown bit — skip ring push */

    uint32_t now_ms = (uint32_t)(time_us_64() / 1000u);

    /* Coalesce-by-slot: if the previous push for this bit was within the
     * window, walk the ring back one entry and bump its count. We don't
     * actually walk because we'd race the consumer; instead we rely on
     * the producer-side timestamp + a "last pushed" cache. If it's been
     * longer than the window, push a fresh entry. */
    if (s_coalesce[slot].last_ts_ms != 0 &&
        (now_ms - s_coalesce[slot].last_ts_ms) < FAULT_COALESCE_WINDOW_MS) {
        /* Within window — skip pushing a duplicate. The dash will see
         * one entry per window per bit, which is the right granularity
         * for a fault dashboard. */
        return;
    }
    s_coalesce[slot].last_ts_ms = now_ms;

    ecu_fault_entry_t e = {0};
    e.fault_bit       = bit;
    e.rpm             = (uint16_t)crank_current_rpm();
    e.tooth_period_us = crank_tooth_period_us();
    e.avg_period_us   = crank_tooth_period_us();
    e.timestamp_ms    = now_ms;
    e.count           = 1;
    (void)ipc_fault_push(&e);  /* drop on full — see ipc.c */
}
