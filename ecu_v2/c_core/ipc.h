#ifndef ECU_IPC_H
#define ECU_IPC_H

#include "ecu_types.h"
#include <stdatomic.h>

/* The IPC layout is the single shared region between the C real-time core
 * and the MicroPython surface. It lives at a fixed linker symbol so both
 * sides agree on the layout without runtime negotiation.
 *
 * Concurrency contract per field group:
 *
 *   telemetry_block  : SEQLOCK. C writer; MP readers. Writer increments
 *                      .seq before+after the body; readers retry on odd or
 *                      changed seq.
 *
 *   profile_shadow[] : DOUBLE-BUFFER + commit. MP writes the inactive
 *                      shadow at index !active_idx, then sets pending_commit
 *                      to true. C swaps active_idx between fire events
 *                      (boundary inside scheduler.c).
 *
 *   fault_ring       : SPSC. C is sole producer (head). MP is sole consumer
 *                      (tail). Both indices are atomic.
 *
 *   cmd_block        : single-writer. MP-only writes; C-only reads.
 *                      Each field is a discrete word so there's no need for
 *                      a seqlock.
 */

/* ---- profile (bench-portable copy of the sanitized JSON) ---- */
typedef struct {
    /* geometry */
    uint16_t teeth_per_rev;
    uint16_t sync_tooth_index;
    uint32_t tooth_min_us;
    uint32_t tooth_max_us;
    uint16_t debounce_us;
    uint16_t sync_edges_to_lock;
    uint16_t mtr_x10;             /* missing-tooth ratio × 10 */
    /* safe fallback */
    uint32_t safe_fire_delay_us;
    uint32_t safe_dwell_us;
    /* advance map (rpm, centi-degrees) */
    uint16_t adv_count;
    uint16_t adv_rpm[ECU_ADV_MAP_MAX];
    int16_t  adv_cd[ECU_ADV_MAP_MAX];
    /* dwell map */
    uint16_t dwell_count;
    uint16_t dwell_rpm[ECU_DWELL_MAP_MAX];
    uint16_t dwell_us[ECU_DWELL_MAP_MAX];
    /* identification */
    uint16_t profile_crc16;
} ecu_profile_t;

/* ---- live telemetry (seqlock-published) ---- */
typedef struct {
    /* writer increments seq pre+post; readers retry on odd or changed */
    atomic_uint_fast32_t seq;

    /* body — fields below are written between seq++ ; seq++ */
    uint32_t rpm;
    uint8_t  sync_state;
    uint8_t  ignition_mode;
    uint16_t validity_bits;

    uint32_t fault_bits;
    uint32_t cycle_id;
    uint32_t spark_counter;
    uint8_t  ignition_output;
    uint8_t  pad0;
    int16_t  current_advance_cd;
    uint32_t tooth_period_us;
    uint16_t tooth_index;
    uint16_t pad1;
    uint64_t last_edge_ticks;
} ecu_telemetry_t;

/* ---- fault ring entry (matches v1 TLV_FAULT_LOG layout) ---- */
typedef struct {
    uint32_t fault_bit;
    uint16_t rpm;
    uint16_t pad0;
    uint32_t tooth_period_us;
    uint32_t avg_period_us;
    uint32_t timestamp_ms;
    uint16_t count;
    uint16_t pad1;
} ecu_fault_entry_t;

/* ---- command block (MP -> C) ---- */
typedef struct {
    atomic_uint_fast32_t soft_inhibit;        /* nonzero => inhibit */
    atomic_uint_fast32_t reset_request;       /* bump to request gear-state reset */
    atomic_uint_fast32_t pending_commit;      /* nonzero => swap on next boundary */
    atomic_uint_fast32_t active_idx;          /* 0 or 1 — which shadow is live */
} ecu_cmd_t;

/* ---- the one shared struct ---- */
typedef struct {
    ecu_telemetry_t   telemetry;
    ecu_profile_t     profile_shadow[2];
    ecu_cmd_t         cmd;

    /* SPSC fault ring */
    atomic_uint_fast32_t fault_head;          /* C-only writer */
    atomic_uint_fast32_t fault_tail;          /* MP-only consumer */
    ecu_fault_entry_t   fault_ring[ECU_FAULT_RING_LEN];

    /* boot status, read-once after init */
    uint32_t            magic;
    uint32_t            version;
} ecu_ipc_t;

#define ECU_IPC_MAGIC   0xB1KE2EC0u
#define ECU_IPC_VERSION 1u

/* The single instance, defined in ipc.c. */
extern ecu_ipc_t g_ipc;

/* Active profile pointer (by value of active_idx). C readers should call
 * ipc_active_profile() once per scheduling cycle and not re-read mid-cycle. */
static inline const ecu_profile_t *ipc_active_profile(void) {
    uint32_t idx = atomic_load_explicit(&g_ipc.cmd.active_idx, memory_order_acquire) & 1u;
    return &g_ipc.profile_shadow[idx];
}

/* Telemetry seqlock helpers.
 *
 * fetch_add(release) releases prior writes — wrong direction for the
 * BEGIN side, where we want subsequent (body) writes to be ordered AFTER
 * the seq bump from the reader's perspective. Use a relaxed atomic for
 * the seq bump itself and an explicit release fence to wall off body
 * writes on either side. Mirror with acquire fences on the reader. */
static inline void ipc_telemetry_begin_write(void) {
    /* even -> odd : readers will retry. */
    atomic_fetch_add_explicit(&g_ipc.telemetry.seq, 1u, memory_order_relaxed);
    atomic_thread_fence(memory_order_release);
}
static inline void ipc_telemetry_end_write(void) {
    atomic_thread_fence(memory_order_release);
    atomic_fetch_add_explicit(&g_ipc.telemetry.seq, 1u, memory_order_relaxed);
}

/* Fault ring SPSC. ipc_fault_push runs from C; ipc_fault_pop runs from MP. */
bool ipc_fault_push(const ecu_fault_entry_t *e);
bool ipc_fault_pop(ecu_fault_entry_t *out);

/* Profile commit boundary. Called by scheduler.c between fire events. */
void ipc_profile_apply_commit_if_pending(void);

/* Init: zero the struct, install defaults into shadow 0, set active_idx=0. */
void ipc_init(void);

#endif /* ECU_IPC_H */
