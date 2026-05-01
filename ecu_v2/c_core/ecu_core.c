#include "ecu_core.h"
#include "ipc.h"
#include "crank.h"
#include "scheduler.h"
#include "ignition.h"
#include "safety.h"
#include "faults.h"

#include "pico/multicore.h"
#include "pico/time.h"
#include "hardware/pio.h"
#include "hardware/irq.h"
#include "hardware/sync.h"

#include "crank_capture.pio.h"  /* generated from crank_capture.pio */

#define CRANK_PIN 2u
#define CRANK_PIO pio0
#define CRANK_SM  0

static volatile bool s_started        = false;
static volatile bool s_core1_running  = false;
static volatile bool s_core1_ready    = false;

/* Alarm pool created on Core 1. The alarm pool's hardware-alarm IRQ is
 * registered on whichever core called alarm_pool_create_*; creating it
 * inside core1_entry() keeps every alarm callback (scheduler dwell_on /
 * fire / soft tick) firing on Core 1 — leaving Core 0 free for MP / UART. */
static alarm_pool_t *s_alarm_pool = NULL;

static repeating_timer_t s_soft_tick_timer;

alarm_pool_t *ecu_core_alarm_pool(void) { return s_alarm_pool; }

static bool soft_tick_cb(repeating_timer_t *rt) {
    (void)rt;
    crank_soft_tick(time_us_64());
    return true;  /* keep repeating */
}

static void __not_in_flash_func(pio_irq_handler)(void) {
    crank_pio_isr();
}

/* SIO FIFO-RX handler — used purely so a multicore_fifo push from Core 0
 * wakes Core 1 from WFI on the stop() path. The IRQ has to be enabled on
 * Core 1 for WFI to wake on it; otherwise Core 1 would sit indefinitely.
 * We don't need the payload, just drain the FIFO and clear status. */
static void __not_in_flash_func(core1_sio_fifo_handler)(void) {
    multicore_fifo_clear_irq();
    while (multicore_fifo_rvalid()) {
        (void)multicore_fifo_pop_blocking();
    }
}

/* ---- Core 1 entry ---- */
static void core1_entry(void) {
    /* Build a Core-1-owned alarm pool. This both reserves a hardware
     * alarm slot AND registers the corresponding TIMER_IRQ on Core 1 —
     * exactly what we need so scheduler/soft-tick callbacks fire here. */
    s_alarm_pool = alarm_pool_create_with_unused_hardware_alarm(8);

    /* 1 kHz soft tick on the Core 1 pool. Negative period = strict
     * periodicity (fire every N µs from start) instead of "wait N µs
     * after the last callback returned". */
    alarm_pool_add_repeating_timer_us(s_alarm_pool, -1000,
                                      soft_tick_cb, NULL,
                                      &s_soft_tick_timer);

    /* PIO RX-FIFO-not-empty IRQ. On RP2350 the NVIC enable bit is
     * per-core; both irq_set_exclusive_handler (writes the per-core
     * vector) and irq_set_enabled (writes per-core NVIC) must happen on
     * the destination core for the IRQ to actually fire here. */
    irq_set_exclusive_handler(PIO0_IRQ_0, pio_irq_handler);
    irq_set_priority(PIO0_IRQ_0, 0);   /* highest */
    irq_set_enabled(PIO0_IRQ_0, true);

    /* SIO FIFO IRQ — wake source for stop(). */
    irq_set_exclusive_handler(SIO_IRQ_FIFO, core1_sio_fifo_handler);
    irq_set_enabled(SIO_IRQ_FIFO, true);

    s_core1_ready   = true;
    s_core1_running = true;

    while (s_core1_running) {
        __wfi();
    }

    /* ---- cleanup on stop ---- */
    cancel_repeating_timer(&s_soft_tick_timer);
    scheduler_cancel_all();
    ignition_force_off();
    irq_set_enabled(PIO0_IRQ_0,    false);
    irq_set_enabled(SIO_IRQ_FIFO,  false);
}

bool ecu_core_start(void) {
    if (s_started) return false;

    /* Order matters. Drive coil low first, then init everything else. */
    ignition_init();          /* coil pin -> output low */
    safety_init();            /* inhibit pin pull-up */
    ipc_init();               /* shared block + default profile */
    faults_init();            /* clear bits + coalesce state */
    crank_init();             /* gear-state defaults */
    scheduler_init();         /* alarm slots */

    /* PIO program load + SM config — these don't touch the NVIC, so
     * they're safe to run on Core 0 before launching Core 1. */
    uint offset = pio_add_program(CRANK_PIO, &crank_capture_program);
    crank_capture_program_init(CRANK_PIO, CRANK_SM, offset, CRANK_PIN);
    crank_set_pio(CRANK_PIO, CRANK_SM);

    /* Route the FIFO-not-empty source onto PIO0_IRQ_0. The NVIC enable
     * for that IRQ is done from Core 1's entry. */
    pio_set_irqn_source_enabled(CRANK_PIO, 0,
        (enum pio_interrupt_source)(pis_sm0_rx_fifo_not_empty + CRANK_SM),
        true);

    /* Launch Core 1 — it creates the alarm pool and wires its own IRQs. */
    multicore_launch_core1(core1_entry);

    /* Spin until Core 1 has finished its setup. MP must not push a
     * profile (and thus depend on the alarm pool) before this. */
    while (!s_core1_ready) {
        tight_loop_contents();
    }

    s_started = true;
    return true;
}

void ecu_core_stop(void) {
    if (!s_started) return;

    /* Stop new edges before tearing the rest down. The PIO source enable
     * is not per-core, so we can clear it from Core 0. */
    pio_set_irqn_source_enabled(CRANK_PIO, 0,
        (enum pio_interrupt_source)(pis_sm0_rx_fifo_not_empty + CRANK_SM),
        false);
    pio_sm_set_enabled(CRANK_PIO, CRANK_SM, false);

    /* Tell Core 1 to exit, then push a byte through the SIO FIFO so its
     * SIO_IRQ_FIFO fires — that's the IRQ that lets WFI return. */
    s_core1_running = false;
    multicore_fifo_push_blocking(0);

    /* Brief wait for Core 1 cleanup. */
    sleep_ms(5);

    scheduler_cancel_all();
    ignition_force_off();
    s_alarm_pool = NULL;
    s_core1_ready = false;
    s_started     = false;
}
