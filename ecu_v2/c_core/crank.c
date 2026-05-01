#include "crank.h"
#include "ipc.h"
#include "scheduler.h"
#include "faults.h"
#include "safety.h"
#include "ignition.h"

#include "pico/time.h"
#include "hardware/pio.h"
#include "hardware/timer.h"

/* The PIO instance + state machine are configured by ecu_core.c. We hold
 * references here so the IRQ handler can read the FIFO directly. */
static PIO  s_pio = NULL;
static uint s_sm  = 0;

/* Internal real-time state. None of these are touched outside IRQ
 * contexts (PIO ISR, soft tick), so we don't need atomics — the only
 * cross-context publication is via the IPC seqlock. */
typedef struct {
    uint64_t last_edge_us;
    uint32_t last_dt_us;
    uint32_t tooth_period_us;   /* EMA */
    uint16_t tooth_index;
    uint16_t sync_edge_count;
    uint16_t noise_streak;
    uint16_t range_streak;

    sync_state_t    sync_state;
    ignition_mode_t ignition_mode;

    uint32_t rpm;
    uint32_t cycle_id;
    uint32_t spark_counter_mirror;  /* mirror of scheduler's count, for telemetry */

    uint64_t precision_lockout_until_us;

    /* counters drained by soft tick / diag */
    uint32_t isr_overrun_count;
    uint32_t stale_event_count;

    uint32_t fault_bits;
} crank_state_t;

static crank_state_t s = {0};

/* Constants tuned for soft-tick budgeting. */
#define PRECISION_REENTRY_LOCKOUT_US 1500000u   /* 1.5 s */

/* Public: install PIO references — called by ecu_core.c after PIO setup. */
void crank_set_pio(PIO pio, uint sm) {
    s_pio = pio;
    s_sm  = sm;
}

void crank_init(void) {
    crank_reset_state();
    s.sync_state    = SYNC_LOST;
    s.ignition_mode = IGN_MODE_INHIBIT;
}

void crank_reset_state(void) {
    s.last_edge_us       = 0;
    s.last_dt_us         = 0;
    s.tooth_period_us    = 0;
    s.tooth_index        = 0;
    s.sync_edge_count    = 0;
    s.noise_streak       = 0;
    s.range_streak       = 0;
    /* sync_state / ignition_mode / cycle_id are owned by the soft tick
     * promotion logic; we don't touch them here. */
}

uint32_t crank_tooth_period_us(void)   { return s.tooth_period_us; }
uint32_t crank_current_rpm(void)       { return s.rpm; }
sync_state_t crank_sync_state(void)    { return s.sync_state; }
ignition_mode_t crank_ignition_mode(void) { return s.ignition_mode; }

uint32_t crank_isr_overrun_count_take(void) {
    uint32_t v = s.isr_overrun_count;
    s.isr_overrun_count = 0;
    return v;
}

/* ---- hot path ---- */

/* Process a single tooth edge captured at edge_us. Inlined into the PIO
 * ISR loop. Keeps the per-edge cost fully inside the L1 cache. */
static inline void process_one_edge(uint64_t edge_us) {
    const ecu_profile_t *p = ipc_active_profile();

    uint64_t last = s.last_edge_us;
    if (last == 0) {
        s.last_edge_us = edge_us;
        return;
    }

    uint32_t dt = (uint32_t)(edge_us - last);

    /* Debounce. */
    if (dt < p->debounce_us) {
        s.noise_streak++;
        return;
    }

    s.last_edge_us = edge_us;
    s.last_dt_us   = dt;

    uint32_t period = s.tooth_period_us;
    bool is_ref = false;

    /* MISSING-TOOTH GAP CHECK MUST PRECEDE RANGE CHECK.
     * If we range-checked first, the gap would always exceed tooth_max_us
     * and trip the plausibility fault. */
    if (period > 0 && (uint64_t)dt * 10u > (uint64_t)period * p->mtr_x10) {
        is_ref = true;
        s.tooth_index = p->sync_tooth_index;
        s.range_streak = 0;
    } else if (dt < p->tooth_min_us || dt > p->tooth_max_us) {
        s.range_streak++;
        return;  /* don't update period/EMA from a bad edge */
    } else {
        s.range_streak = 0;
        uint16_t idx = (uint16_t)(s.tooth_index + 1u);
        if (idx >= p->teeth_per_rev) idx = 0;
        s.tooth_index = idx;
        if (idx == p->sync_tooth_index) is_ref = true;
    }

    /* EMA period: (period*3 + dt) / 4 — same as v1. */
    if (period == 0) {
        s.tooth_period_us = dt;
    } else {
        s.tooth_period_us = ((period * 3u) + dt) >> 2;
    }

    if (s.sync_edge_count < p->sync_edges_to_lock) {
        s.sync_edge_count++;
    }

    if (is_ref) {
        s.cycle_id++;
        scheduler_arm_for_reference(edge_us, s.cycle_id, s.tooth_period_us);
    }
}

/* PIO RX FIFO ISR. Wired by ecu_core.c.
 *
 * We pop AT MOST ONE entry per ISR invocation. The FIFO-not-empty IRQ
 * source is level-triggered: if more entries remain after we return, the
 * NVIC re-pends the IRQ and we re-enter immediately. Draining the whole
 * FIFO in a single call would reuse the same entry_us timestamp for every
 * edge in the batch, so dt = entry_us - entry_us = 0 for every batched
 * edge after the first — that fails the debounce check and falsely
 * increments noise_streak. Take one edge, sample the timer freshly. */
void __not_in_flash_func(crank_pio_isr)(void) {
    uint64_t entry_us = time_us_64();

    if (!pio_sm_is_rx_fifo_empty(s_pio, s_sm)) {
        (void)pio_sm_get(s_pio, s_sm);  /* discard payload — we use entry_us */
        process_one_edge(entry_us);
    }

    /* Self-overrun check: how long did we take? */
    uint32_t isr_us = (uint32_t)(time_us_64() - entry_us);
    if (isr_us > ECU_ISR_OVERRUN_LIMIT_US) {
        s.isr_overrun_count++;
    }
}

/* ---- soft tick ---- */

void __not_in_flash_func(crank_soft_tick)(uint64_t now_us) {
    const ecu_profile_t *p = ipc_active_profile();

    /* 1) Safety inhibit (highest priority — kills ignition immediately). */
    if (safety_inhibit_active()) {
        scheduler_cancel_all();
        ignition_force_off();
        s.ignition_mode = IGN_MODE_INHIBIT;
        s.sync_state    = SYNC_LOST;
        s.rpm           = 0;
        crank_reset_state();
        faults_set(FAULT_SAFETY_INHIBIT);
        s.fault_bits = faults_get();
        goto publish;
    }

    /* 2) Sync timeout. */
    if (s.last_edge_us != 0 &&
        (now_us - s.last_edge_us) > ECU_SYNC_TIMEOUT_US) {
        scheduler_cancel_all();
        ignition_force_off();
        s.ignition_mode = IGN_MODE_INHIBIT;
        s.sync_state    = SYNC_LOST;
        s.rpm           = 0;
        s.precision_lockout_until_us = now_us + PRECISION_REENTRY_LOCKOUT_US;
        crank_reset_state();
        faults_set(FAULT_SYNC_TIMEOUT);
        s.fault_bits = faults_get();
        goto publish;
    }

    /* 3) Range/noise streak promotion. */
    if (s.range_streak >= ECU_RANGE_STREAK_LIMIT) {
        scheduler_cancel_all();
        ignition_force_off();
        s.ignition_mode = IGN_MODE_INHIBIT;
        s.sync_state    = SYNC_LOST;
        s.rpm           = 0;
        s.precision_lockout_until_us = now_us + PRECISION_REENTRY_LOCKOUT_US;
        crank_reset_state();
        faults_set(FAULT_EDGE_PLAUSIBILITY);
        s.fault_bits = faults_get();
        goto publish;
    }
    if (s.noise_streak >= ECU_NOISE_STREAK_LIMIT) {
        scheduler_cancel_all();
        ignition_force_off();
        s.ignition_mode = IGN_MODE_INHIBIT;
        s.sync_state    = SYNC_LOST;
        s.rpm           = 0;
        s.precision_lockout_until_us = now_us + PRECISION_REENTRY_LOCKOUT_US;
        crank_reset_state();
        faults_set(FAULT_UNSTABLE_SYNC);
        s.fault_bits = faults_get();
        goto publish;
    }

    /* 4) RPM. */
    if (s.tooth_period_us > 0 && p->teeth_per_rev > 0) {
        uint64_t rev_period = (uint64_t)s.tooth_period_us * p->teeth_per_rev;
        if (rev_period > 0) {
            s.rpm = (uint32_t)(60000000ull / rev_period);
        } else {
            s.rpm = 0;
        }
    } else {
        s.rpm = 0;
    }

    /* 5) Sync state machine. */
    if (s.tooth_period_us == 0) {
        s.sync_state = SYNC_LOST;
    } else if (s.sync_edge_count >= p->sync_edges_to_lock) {
        s.sync_state = SYNC_SYNCED;
        if (now_us < s.precision_lockout_until_us) {
            s.sync_state = SYNC_SYNCING;
        }
    } else {
        s.sync_state = SYNC_SYNCING;
    }

    /* 6) Ignition mode mirrors sync state. */
    switch (s.sync_state) {
    case SYNC_LOST:    s.ignition_mode = IGN_MODE_INHIBIT;   break;
    case SYNC_SYNCING: s.ignition_mode = IGN_MODE_SAFE;      break;
    case SYNC_SYNCED:  s.ignition_mode = IGN_MODE_PRECISION; break;
    }

    /* 7) Drain ISR-side counters and promote to faults. */
    if (s.isr_overrun_count > 0) {
        faults_set(FAULT_ISR_OVERRUN);
        s.isr_overrun_count = 0;
    }
    /* stale_event_count is populated by scheduler.c via faults_set already;
     * we don't need to mirror it here. */

    s.fault_bits = faults_get();

    /* 8) Profile-commit boundary check. Only safe to swap when we're not
     * mid-cycle: scheduler exposes a quiescence flag. */
    if (scheduler_is_quiescent()) {
        ipc_profile_apply_commit_if_pending();
    }

publish:
    /* Publish telemetry via seqlock. */
    ipc_telemetry_begin_write();
    g_ipc.telemetry.rpm                = s.rpm;
    g_ipc.telemetry.sync_state         = (uint8_t)s.sync_state;
    g_ipc.telemetry.ignition_mode      = (uint8_t)s.ignition_mode;
    g_ipc.telemetry.fault_bits         = s.fault_bits;
    g_ipc.telemetry.cycle_id           = s.cycle_id;
    g_ipc.telemetry.spark_counter      = scheduler_spark_count();
    g_ipc.telemetry.ignition_output    = ignition_is_active() ? 1u : 0u;
    g_ipc.telemetry.tooth_period_us    = s.tooth_period_us;
    g_ipc.telemetry.tooth_index        = s.tooth_index;
    g_ipc.telemetry.last_edge_ticks    = s.last_edge_us;
    g_ipc.telemetry.current_advance_cd = scheduler_current_advance_cd();

    uint16_t valid = VALID_SYNC | VALID_IGN_MODE | VALID_FAULTS | VALID_IGN_OUT;
    if (s.rpm > 0 && s.sync_state != SYNC_LOST) valid |= VALID_RPM;
    g_ipc.telemetry.validity_bits = valid;
    ipc_telemetry_end_write();

    /* If MP requested a state reset, honor it now (after publication so the
     * dash sees one tick of "valid_bits cleared" before reset takes hold). */
    uint32_t rr = atomic_exchange_explicit(&g_ipc.cmd.reset_request, 0u,
                                           memory_order_acq_rel);
    if (rr) {
        crank_reset_state();
        faults_clear_all();
    }
}
