/* ecu_native.c
 *
 * MicroPython native module that exposes the C real-time core to Python.
 * All functions here are non-blocking shims over the IPC layer; none of
 * them touch the ignition path directly.
 *
 * Build: this file is compiled as part of MicroPython's USER_C_MODULES.
 * See micropython.cmake for the integration glue.
 */

#include "py/runtime.h"
#include "py/objstr.h"
#include "py/objlist.h"
#include "py/objdict.h"
#include "py/objint.h"
#include "py/mphal.h"

#include "../c_core/ecu_types.h"
#include "../c_core/ipc.h"
#include "../c_core/ecu_core.h"
#include "../c_core/faults.h"

/* ---- start / stop ---- */
static mp_obj_t ecu_start(void) {
    bool ok = ecu_core_start();
    return mp_obj_new_bool(ok);
}
static MP_DEFINE_CONST_FUN_OBJ_0(ecu_start_obj, ecu_start);

static mp_obj_t ecu_stop(void) {
    ecu_core_stop();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ecu_stop_obj, ecu_stop);

/* ---- read_state: seqlock-safe snapshot ---- */
static mp_obj_t ecu_read_state(void) {
    /* Retry up to 8 times on torn read (writer in progress). 8 is far
     * more than necessary — at 1 kHz writer rate the reader has ms of
     * window — but it bounds the loop. Pairs with the release fences in
     * ipc_telemetry_begin/end_write: relaxed seq loads + acquire fences
     * around the body read. */
    ecu_telemetry_t snap;
    int tries = 0;
    do {
        uint32_t s1 = atomic_load_explicit(&g_ipc.telemetry.seq,
                                           memory_order_relaxed);
        if (s1 & 1u) { tries++; continue; }   /* write in progress */
        atomic_thread_fence(memory_order_acquire);
        snap = g_ipc.telemetry;
        atomic_thread_fence(memory_order_acquire);
        uint32_t s2 = atomic_load_explicit(&g_ipc.telemetry.seq,
                                           memory_order_relaxed);
        if (s1 == s2) break;                  /* clean read */
        tries++;
    } while (tries < 8);

    /* Build a Python dict. We allocate fresh but only once per call;
     * this is invoked at telemetry rate (50 Hz) so the GC pressure is
     * negligible compared to v1's per-edge allocation. */
    mp_obj_t d = mp_obj_new_dict(12);
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_rpm),               mp_obj_new_int_from_uint(snap.rpm));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_sync_state),        MP_OBJ_NEW_SMALL_INT(snap.sync_state));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_ignition_mode),     MP_OBJ_NEW_SMALL_INT(snap.ignition_mode));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_validity_bits),     MP_OBJ_NEW_SMALL_INT(snap.validity_bits));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_fault_bits),        mp_obj_new_int_from_uint(snap.fault_bits));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_cycle_id),          mp_obj_new_int_from_uint(snap.cycle_id));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_spark_counter),     mp_obj_new_int_from_uint(snap.spark_counter));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_ignition_output),   MP_OBJ_NEW_SMALL_INT(snap.ignition_output));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_advance_cd),        MP_OBJ_NEW_SMALL_INT(snap.current_advance_cd));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_tooth_period_us),   mp_obj_new_int_from_uint(snap.tooth_period_us));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_tooth_index),       MP_OBJ_NEW_SMALL_INT(snap.tooth_index));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_last_edge_us),      mp_obj_new_int_from_ull(snap.last_edge_ticks));
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ecu_read_state_obj, ecu_read_state);

/* ---- profile push ----
 *
 * We accept a fully-sanitized profile dict from Python (the v1
 * config_layer.sanitize_profile() is preserved verbatim and runs in
 * Python before this is called). This function copies fields into the
 * inactive shadow and sets pending_commit. The C scheduler picks the
 * swap up at its next quiet boundary.
 *
 * Profile validation that requires JSON parsing / heap allocation
 * (sanitize, default-fill, CRC) lives in Python. This function does
 * only direct-typed extraction — no parsing. */

/* Look up a key in a dict via the canonical mp_map_lookup path. Returns
 * MP_OBJ_NULL if absent. Works on both `dict` and `OrderedDict` (they
 * share the same underlying map layout). */
static mp_obj_t dict_lookup(mp_obj_t d, qstr key) {
    mp_obj_dict_t *dict = MP_OBJ_TO_PTR(d);
    mp_map_elem_t *elem = mp_map_lookup(&dict->map,
                                        MP_OBJ_NEW_QSTR(key),
                                        MP_MAP_LOOKUP);
    return elem ? elem->value : MP_OBJ_NULL;
}

static int dict_get_int(mp_obj_t d, qstr key, int dflt) {
    mp_obj_t v = dict_lookup(d, key);
    if (v == MP_OBJ_NULL || v == mp_const_none) return dflt;
    return mp_obj_get_int(v);
}

static void load_int_array_u16(mp_obj_t d, qstr key, uint16_t *out,
                               uint16_t max_n, uint16_t *out_count) {
    *out_count = 0;
    mp_obj_t v = dict_lookup(d, key);
    if (v == MP_OBJ_NULL || v == mp_const_none) return;
    size_t n;
    mp_obj_t *items;
    mp_obj_get_array(v, &n, &items);
    if (n > max_n) n = max_n;
    for (size_t i = 0; i < n; ++i) {
        int x = mp_obj_get_int(items[i]);
        if (x < 0) x = 0;
        if (x > 0xFFFF) x = 0xFFFF;
        out[i] = (uint16_t)x;
    }
    *out_count = (uint16_t)n;
}

static void load_int_array_i16(mp_obj_t d, qstr key, int16_t *out,
                               uint16_t max_n, uint16_t *out_count) {
    *out_count = 0;
    mp_obj_t v = dict_lookup(d, key);
    if (v == MP_OBJ_NULL || v == mp_const_none) return;
    size_t n;
    mp_obj_t *items;
    mp_obj_get_array(v, &n, &items);
    if (n > max_n) n = max_n;
    for (size_t i = 0; i < n; ++i) {
        int x = mp_obj_get_int(items[i]);
        if (x >  32767) x =  32767;
        if (x < -32768) x = -32768;
        out[i] = (int16_t)x;
    }
    *out_count = (uint16_t)n;
}

static mp_obj_t ecu_set_profile(mp_obj_t profile_dict) {
    if (!mp_obj_is_type(profile_dict, &mp_type_dict)) {
        mp_raise_TypeError(MP_ERROR_TEXT("profile must be a dict"));
    }

    /* Pick the inactive shadow (the one the C scheduler is NOT reading). */
    uint32_t active = atomic_load_explicit(&g_ipc.cmd.active_idx,
                                           memory_order_acquire) & 1u;
    ecu_profile_t *shadow = &g_ipc.profile_shadow[active ^ 1u];

    shadow->teeth_per_rev      = (uint16_t)dict_get_int(profile_dict, MP_QSTR_teeth_per_rev, 21);
    shadow->sync_tooth_index   = (uint16_t)dict_get_int(profile_dict, MP_QSTR_sync_tooth_index, 0);
    shadow->tooth_min_us       = (uint32_t)dict_get_int(profile_dict, MP_QSTR_tooth_min_us, 300);
    shadow->tooth_max_us       = (uint32_t)dict_get_int(profile_dict, MP_QSTR_tooth_max_us, 8000);
    shadow->debounce_us        = (uint16_t)dict_get_int(profile_dict, MP_QSTR_debounce_us, 40);
    shadow->sync_edges_to_lock = (uint16_t)dict_get_int(profile_dict, MP_QSTR_sync_edges_to_lock, 8);

    /* missing_tooth_ratio comes in as a float in v1's profile; we want
     * it as ×10 integer for the C side. */
    mp_obj_t mtr = dict_lookup(profile_dict, MP_QSTR_missing_tooth_ratio);
    int mtr_x10 = 18;
    if (mtr != MP_OBJ_NULL && mtr != mp_const_none) {
        mp_float_t f = mp_obj_get_float(mtr);
        mtr_x10 = (int)(f * 10.0f + 0.5f);
        if (mtr_x10 < ECU_MTR_X10_MIN) mtr_x10 = ECU_MTR_X10_MIN;
        if (mtr_x10 > ECU_MTR_X10_MAX) mtr_x10 = ECU_MTR_X10_MAX;
    }
    shadow->mtr_x10 = (uint16_t)mtr_x10;

    shadow->safe_fire_delay_us = (uint32_t)dict_get_int(profile_dict, MP_QSTR_safe_fire_delay_us, 2500);
    shadow->safe_dwell_us      = (uint32_t)dict_get_int(profile_dict, MP_QSTR_safe_dwell_us, 1700);

    load_int_array_u16(profile_dict, MP_QSTR_advance_map_rpm,
                       shadow->adv_rpm, ECU_ADV_MAP_MAX, &shadow->adv_count);
    load_int_array_i16(profile_dict, MP_QSTR_advance_map_cd,
                       shadow->adv_cd,  ECU_ADV_MAP_MAX, &shadow->adv_count);

    load_int_array_u16(profile_dict, MP_QSTR_dwell_map_rpm,
                       shadow->dwell_rpm, ECU_DWELL_MAP_MAX, &shadow->dwell_count);
    load_int_array_u16(profile_dict, MP_QSTR_dwell_map_us,
                       shadow->dwell_us,  ECU_DWELL_MAP_MAX, &shadow->dwell_count);

    /* Profile CRC is left for Python to compute and stash (it owns the
     * canonical byte sequence). MP can write it into shadow->profile_crc16
     * if needed for telemetry. */

    /* Signal the C side: swap on next quiet boundary. */
    atomic_store_explicit(&g_ipc.cmd.pending_commit, 1u, memory_order_release);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(ecu_set_profile_obj, ecu_set_profile);

/* ---- inhibit / reset ---- */
static mp_obj_t ecu_set_inhibit(mp_obj_t v) {
    atomic_store_explicit(&g_ipc.cmd.soft_inhibit,
                          mp_obj_is_true(v) ? 1u : 0u,
                          memory_order_release);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(ecu_set_inhibit_obj, ecu_set_inhibit);

static mp_obj_t ecu_request_reset(void) {
    atomic_store_explicit(&g_ipc.cmd.reset_request, 1u, memory_order_release);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ecu_request_reset_obj, ecu_request_reset);

/* ---- drain_faults: pop everything from the ring as a list of dicts ---- */
static mp_obj_t ecu_drain_faults(void) {
    mp_obj_t out = mp_obj_new_list(0, NULL);
    ecu_fault_entry_t e;
    int popped = 0;
    /* Cap at ECU_FAULT_RING_LEN to avoid an unbounded loop if producer
     * happens to keep pushing while we drain. */
    while (popped < (int)ECU_FAULT_RING_LEN && ipc_fault_pop(&e)) {
        mp_obj_t d = mp_obj_new_dict(6);
        mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_fault_bit),       mp_obj_new_int_from_uint(e.fault_bit));
        mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_rpm),             MP_OBJ_NEW_SMALL_INT(e.rpm));
        mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_tooth_period_us), mp_obj_new_int_from_uint(e.tooth_period_us));
        mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_avg_period_us),   mp_obj_new_int_from_uint(e.avg_period_us));
        mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_timestamp_ms),    mp_obj_new_int_from_uint(e.timestamp_ms));
        mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_count),           MP_OBJ_NEW_SMALL_INT(e.count));
        mp_obj_list_append(out, d);
        popped++;
    }
    return out;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ecu_drain_faults_obj, ecu_drain_faults);

/* ---- profile_crc helper for the dash response ---- */
static mp_obj_t ecu_set_profile_crc16(mp_obj_t v) {
    uint16_t crc = (uint16_t)mp_obj_get_int(v);
    /* Stamp the CRC into both shadows so whichever is active reports the
     * correct value. */
    g_ipc.profile_shadow[0].profile_crc16 = crc;
    g_ipc.profile_shadow[1].profile_crc16 = crc;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(ecu_set_profile_crc16_obj, ecu_set_profile_crc16);

static mp_obj_t ecu_get_profile_crc16(void) {
    return mp_obj_new_int_from_uint(ipc_active_profile()->profile_crc16);
}
static MP_DEFINE_CONST_FUN_OBJ_0(ecu_get_profile_crc16_obj, ecu_get_profile_crc16);

/* ---- module table ---- */
static const mp_rom_map_elem_t ecu_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),           MP_ROM_QSTR(MP_QSTR_ecu) },
    { MP_ROM_QSTR(MP_QSTR_start),              MP_ROM_PTR(&ecu_start_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop),               MP_ROM_PTR(&ecu_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_read_state),         MP_ROM_PTR(&ecu_read_state_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_profile),        MP_ROM_PTR(&ecu_set_profile_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_inhibit),        MP_ROM_PTR(&ecu_set_inhibit_obj) },
    { MP_ROM_QSTR(MP_QSTR_request_reset),      MP_ROM_PTR(&ecu_request_reset_obj) },
    { MP_ROM_QSTR(MP_QSTR_drain_faults),       MP_ROM_PTR(&ecu_drain_faults_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_profile_crc16),  MP_ROM_PTR(&ecu_set_profile_crc16_obj) },
    { MP_ROM_QSTR(MP_QSTR_get_profile_crc16),  MP_ROM_PTR(&ecu_get_profile_crc16_obj) },
    /* Sync-state constants — exported so Python doesn't repeat them. */
    { MP_ROM_QSTR(MP_QSTR_SYNC_LOST),          MP_ROM_INT(SYNC_LOST) },
    { MP_ROM_QSTR(MP_QSTR_SYNC_SYNCING),       MP_ROM_INT(SYNC_SYNCING) },
    { MP_ROM_QSTR(MP_QSTR_SYNC_SYNCED),        MP_ROM_INT(SYNC_SYNCED) },
    { MP_ROM_QSTR(MP_QSTR_IGN_INHIBIT),        MP_ROM_INT(IGN_MODE_INHIBIT) },
    { MP_ROM_QSTR(MP_QSTR_IGN_SAFE),           MP_ROM_INT(IGN_MODE_SAFE) },
    { MP_ROM_QSTR(MP_QSTR_IGN_PRECISION),      MP_ROM_INT(IGN_MODE_PRECISION) },
};
static MP_DEFINE_CONST_DICT(ecu_module_globals, ecu_module_globals_table);

const mp_obj_module_t ecu_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&ecu_module_globals,
};

/* Module is registered through micropython.cmake (see that file). */
MP_REGISTER_MODULE(MP_QSTR_ecu, ecu_user_cmodule);
