#include "scheduler.h"
#include "ipc.h"
#include "ignition.h"
#include "advance_map.h"
#include "faults.h"
#include "crank.h"
#include "ecu_core.h"

#include "pico/time.h"

/* We use the Core-1 alarm pool created by ecu_core.c. Each
 * alarm_pool_add_alarm_at() returns an alarm_id_t we must remember and
 * pass back to alarm_pool_cancel_alarm() — small integer literals are
 * not valid alarm IDs. */

typedef struct {
    /* The cycle id the currently-armed alarms belong to. Both alarm
     * callbacks compare their own cycle_id to this; a stale event is
     * silently dropped. */
    volatile uint32_t armed_cycle_id;

    /* True if an alarm is currently armed. Cleared by the fire callback
     * after it runs (the fire is the last event of the cycle). */
    volatile bool dwell_on_armed;
    volatile bool fire_armed;

    /* alarm_id_t values returned by add_alarm_at(). Only valid while the
     * matching *_armed flag is true. */
    volatile alarm_id_t dwell_on_alarm_id;
    volatile alarm_id_t fire_alarm_id;

    volatile uint32_t spark_count;

    /* Most recently computed advance, for telemetry. */
    volatile int16_t current_advance_cd;

    /* Cached dwell so the fire callback doesn't have to re-read the
     * profile (which could have been swapped between arm and fire). */
    volatile uint32_t armed_dwell_us;
} scheduler_state_t;

static scheduler_state_t sch = {0};

void scheduler_init(void) {
    sch.armed_cycle_id   = 0;
    sch.dwell_on_armed   = false;
    sch.fire_armed       = false;
    sch.dwell_on_alarm_id = -1;
    sch.fire_alarm_id     = -1;
    sch.spark_count      = 0;
    sch.current_advance_cd = 0;
    sch.armed_dwell_us   = ECU_DWELL_TARGET_US;
}

uint32_t scheduler_spark_count(void)        { return sch.spark_count; }
int16_t  scheduler_current_advance_cd(void) { return sch.current_advance_cd; }

bool scheduler_is_quiescent(void) {
    return !sch.dwell_on_armed && !sch.fire_armed;
}

/* ---- alarm callbacks ---- */

static int64_t __not_in_flash_func(dwell_on_callback)(alarm_id_t id, void *user_data) {
    (void)id;
    uint32_t cycle = (uint32_t)(uintptr_t)user_data;

    /* Stale check — if a newer cycle has been armed since we were
     * scheduled, drop this event. */
    if (cycle != sch.armed_cycle_id) {
        return 0;
    }
    /* Final safety check inside the callback: never charge coil if
     * inhibit went active between arm time and fire time. */
    if (crank_ignition_mode() == IGN_MODE_INHIBIT) {
        sch.dwell_on_armed = false;
        sch.dwell_on_alarm_id = -1;
        return 0;
    }

    ignition_on();
    sch.dwell_on_armed = false;
    sch.dwell_on_alarm_id = -1;
    return 0;  /* one-shot */
}

static int64_t __not_in_flash_func(fire_callback)(alarm_id_t id, void *user_data) {
    (void)id;
    uint32_t cycle = (uint32_t)(uintptr_t)user_data;

    if (cycle != sch.armed_cycle_id) {
        /* Late event — coil might already be off via cancel_all; force it
         * off again to be sure, but don't count it as a spark. */
        ignition_force_off();
        sch.fire_armed = false;
        sch.fire_alarm_id = -1;
        return 0;
    }

    /* Always turn coil OFF first. If anything else here panics, the coil
     * still ends up off. */
    ignition_force_off();
    sch.spark_count++;
    sch.fire_armed = false;
    sch.fire_alarm_id = -1;
    return 0;
}

/* ---- arm + cancel ---- */

void __not_in_flash_func(scheduler_cancel_all)(void) {
    alarm_pool_t *pool = ecu_core_alarm_pool();
    if (sch.fire_armed) {
        if (pool) alarm_pool_cancel_alarm(pool, sch.fire_alarm_id);
        sch.fire_armed = false;
        sch.fire_alarm_id = -1;
    }
    if (sch.dwell_on_armed) {
        if (pool) alarm_pool_cancel_alarm(pool, sch.dwell_on_alarm_id);
        sch.dwell_on_armed = false;
        sch.dwell_on_alarm_id = -1;
    }
    /* Bump cycle id so any in-flight callback that races us sees a stale
     * cycle and drops itself. */
    sch.armed_cycle_id++;
    ignition_force_off();
}

void __not_in_flash_func(scheduler_arm_for_reference)(uint64_t reference_edge_us,
                                                       uint32_t cycle_id,
                                                       uint32_t tooth_period_us) {
    alarm_pool_t *pool = ecu_core_alarm_pool();
    if (!pool) {
        /* C core not started — nothing to arm. */
        faults_set(FAULT_UNSCHEDULABLE);
        return;
    }

    /* If a previous pair is still armed, cancel it first. The cycle id
     * tagging means even an in-flight callback would drop itself, but we
     * cancel explicitly to free the alarm slots. */
    if (sch.dwell_on_armed) {
        alarm_pool_cancel_alarm(pool, sch.dwell_on_alarm_id);
        sch.dwell_on_armed = false;
        sch.dwell_on_alarm_id = -1;
    }
    if (sch.fire_armed) {
        alarm_pool_cancel_alarm(pool, sch.fire_alarm_id);
        sch.fire_armed = false;
        sch.fire_alarm_id = -1;
    }

    sch.armed_cycle_id = cycle_id;

    ignition_mode_t mode = crank_ignition_mode();
    if (mode == IGN_MODE_INHIBIT) {
        /* Should not happen — caller (crank.c) only invokes us in
         * SAFE/PRECISION — but guard anyway. */
        return;
    }

    const ecu_profile_t *p = ipc_active_profile();

    uint32_t fire_delay_us;
    uint32_t dwell_us;

    if (mode == IGN_MODE_SAFE) {
        fire_delay_us = p->safe_fire_delay_us;
        dwell_us      = p->safe_dwell_us;
        sch.current_advance_cd = 0;
    } else {
        /* PRECISION mode: advance map -> fire delay. */
        uint32_t rev_period_us = tooth_period_us * (uint32_t)p->teeth_per_rev;
        if (rev_period_us == 0) {
            faults_set(FAULT_UNSCHEDULABLE);
            return;
        }

        uint32_t rpm = (uint32_t)(60000000ull / rev_period_us);
        int16_t advance_cd = advance_map_lookup_advance_cd(p, rpm);
        sch.current_advance_cd = advance_cd;

        /* fire_delay = rev_period * (1 - advance/360deg) */
        int32_t advance_offset_us = (int32_t)((int64_t)rev_period_us * advance_cd / 36000);
        int32_t signed_delay = (int32_t)rev_period_us - advance_offset_us;
        if (signed_delay <= (int32_t)ECU_LEAD_GUARD_FIRE_US) {
            faults_set(FAULT_UNSCHEDULABLE);
            return;
        }
        fire_delay_us = (uint32_t)signed_delay;

        dwell_us = advance_map_lookup_dwell_us(p, rpm);
        if (dwell_us < ECU_MIN_COIL_ON_US) {
            faults_set(FAULT_UNSCHEDULABLE);
            return;
        }

        if (fire_delay_us < dwell_us + ECU_LEAD_GUARD_ON_US) {
            faults_set(FAULT_UNSCHEDULABLE);
            return;
        }
    }

    sch.armed_dwell_us = dwell_us;

    /* Compute absolute target times. The SDK's add_alarm_at takes an
     * absolute_time_t; we use that directly so we never accumulate
     * conversion error. */
    uint64_t fire_at_us     = reference_edge_us + fire_delay_us;
    uint64_t dwell_on_at_us = fire_at_us - dwell_us;

    /* Sanity: dwell-on must still be in the future. If we got here late
     * (e.g. prior soft tick stretched), skip arming and flag. */
    uint64_t now = time_us_64();
    if (dwell_on_at_us <= now + ECU_LEAD_GUARD_ON_US) {
        faults_set(FAULT_UNSCHEDULABLE);
        return;
    }

    absolute_time_t dwell_on_t = from_us_since_boot(dwell_on_at_us);
    absolute_time_t fire_t     = from_us_since_boot(fire_at_us);

    /* IMPORTANT: write the armed flags BEFORE calling add_alarm_at.
     * add_alarm_at could in principle return immediately if the time has
     * already passed (negative delta) and invoke the callback inline; the
     * callback would then see armed=false and abort cleanly. We accept
     * that — it's safer than arming an alarm that fires before we've
     * marked it armed. */
    sch.dwell_on_armed = true;
    sch.fire_armed     = true;

    /* Use the Core-1 alarm pool so the callbacks fire on Core 1.
     * user_data carries cycle_id for the stale check. The returned
     * alarm_id_t is what we must hand back to alarm_pool_cancel_alarm. */
    alarm_id_t aid_on = alarm_pool_add_alarm_at(pool, dwell_on_t,
                                                dwell_on_callback,
                                                (void *)(uintptr_t)cycle_id,
                                                true);
    if (aid_on < 0) {
        sch.dwell_on_armed = false;
        sch.fire_armed     = false;
        faults_set(FAULT_UNSCHEDULABLE);
        return;
    }
    sch.dwell_on_alarm_id = aid_on;

    alarm_id_t aid_fire = alarm_pool_add_alarm_at(pool, fire_t,
                                                  fire_callback,
                                                  (void *)(uintptr_t)cycle_id,
                                                  true);
    if (aid_fire < 0) {
        /* fire_at scheduling failed — undo dwell_on if possible. */
        alarm_pool_cancel_alarm(pool, sch.dwell_on_alarm_id);
        sch.dwell_on_armed = false;
        sch.fire_armed     = false;
        sch.dwell_on_alarm_id = -1;
        ignition_force_off();
        faults_set(FAULT_UNSCHEDULABLE);
        return;
    }
    sch.fire_alarm_id = aid_fire;
}
