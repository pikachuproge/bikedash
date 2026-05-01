#include "ipc.h"
#include <string.h>

/* Place the IPC block in a fixed RAM section so both cores see the same
 * struct without going through any indirection. .bss is fine on RP2350; the
 * SDK linker script puts it in SRAM. We don't need a custom section unless
 * we ever want to share with the bootloader. */
ecu_ipc_t g_ipc;

/* ---- defaults — must match ecu/config_layer.py default_profile() ---- */
static void ipc_install_default_profile(ecu_profile_t *p) {
    memset(p, 0, sizeof(*p));
    p->teeth_per_rev      = 21;
    p->sync_tooth_index   = 0;
    p->tooth_min_us       = 300;
    p->tooth_max_us       = 8000;
    p->debounce_us        = 40;
    p->sync_edges_to_lock = 8;
    p->mtr_x10            = 18;     /* 1.8 */
    p->safe_fire_delay_us = 2500;
    p->safe_dwell_us      = 1700;

    /* default advance map: matches default_profile() */
    static const uint16_t adv_rpm[6] = {1000, 2000, 3000, 5000, 7000, 9000};
    static const int16_t  adv_cd[6]  = { 800, 1100, 1400, 1700, 2000, 2200};
    p->adv_count = 6;
    memcpy(p->adv_rpm, adv_rpm, sizeof(adv_rpm));
    memcpy(p->adv_cd,  adv_cd,  sizeof(adv_cd));

    static const uint16_t dwell_rpm[4] = {1000, 3000, 6000, 9000};
    static const uint16_t dwell_us[4]  = {1900, 1800, 1600, 1450};
    p->dwell_count = 4;
    memcpy(p->dwell_rpm, dwell_rpm, sizeof(dwell_rpm));
    memcpy(p->dwell_us,  dwell_us,  sizeof(dwell_us));

    p->profile_crc16 = 0;  /* MP recomputes after install */
}

void ipc_init(void) {
    memset(&g_ipc, 0, sizeof(g_ipc));
    g_ipc.magic   = ECU_IPC_MAGIC;
    g_ipc.version = ECU_IPC_VERSION;

    ipc_install_default_profile(&g_ipc.profile_shadow[0]);
    ipc_install_default_profile(&g_ipc.profile_shadow[1]);
    atomic_store_explicit(&g_ipc.cmd.active_idx, 0u, memory_order_release);

    /* Telemetry seqlock starts even (no write in progress). */
    atomic_store_explicit(&g_ipc.telemetry.seq, 0u, memory_order_release);

    atomic_store_explicit(&g_ipc.fault_head, 0u, memory_order_release);
    atomic_store_explicit(&g_ipc.fault_tail, 0u, memory_order_release);
}

/* ---- SPSC fault ring ----
 * Single-producer (C side, called from soft tick) / single-consumer (MP).
 * Drop-on-full policy: an overflowing fault entry is silently dropped because
 * the ring is sized to absorb 32 entries between MP polls and we'd rather
 * lose one duplicate fault than block the soft tick. */
bool ipc_fault_push(const ecu_fault_entry_t *e) {
    uint32_t head = atomic_load_explicit(&g_ipc.fault_head, memory_order_relaxed);
    uint32_t tail = atomic_load_explicit(&g_ipc.fault_tail, memory_order_acquire);
    uint32_t next = (head + 1u) & ECU_FAULT_RING_MASK;
    if (next == (tail & ECU_FAULT_RING_MASK)) {
        return false;  /* full — drop */
    }
    g_ipc.fault_ring[head & ECU_FAULT_RING_MASK] = *e;
    atomic_store_explicit(&g_ipc.fault_head, head + 1u, memory_order_release);
    return true;
}

bool ipc_fault_pop(ecu_fault_entry_t *out) {
    uint32_t tail = atomic_load_explicit(&g_ipc.fault_tail, memory_order_relaxed);
    uint32_t head = atomic_load_explicit(&g_ipc.fault_head, memory_order_acquire);
    if ((head & ECU_FAULT_RING_MASK) == (tail & ECU_FAULT_RING_MASK)) {
        return false;  /* empty */
    }
    *out = g_ipc.fault_ring[tail & ECU_FAULT_RING_MASK];
    atomic_store_explicit(&g_ipc.fault_tail, tail + 1u, memory_order_release);
    return true;
}

/* Called from scheduler.c at a known-quiet boundary (no alarm armed,
 * no fire event between now and the next reference edge). */
void ipc_profile_apply_commit_if_pending(void) {
    uint32_t pending = atomic_exchange_explicit(&g_ipc.cmd.pending_commit, 0u,
                                                memory_order_acq_rel);
    if (!pending) return;

    /* MP wrote into the shadow at index !active_idx. Swap. */
    uint32_t cur = atomic_load_explicit(&g_ipc.cmd.active_idx, memory_order_relaxed);
    atomic_store_explicit(&g_ipc.cmd.active_idx, cur ^ 1u, memory_order_release);
}
