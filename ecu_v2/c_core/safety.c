#include "safety.h"
#include "ipc.h"
#include "hardware/gpio.h"

#define SAFETY_INHIBIT_PIN 14u

void safety_init(void) {
    gpio_init(SAFETY_INHIBIT_PIN);
    gpio_set_dir(SAFETY_INHIBIT_PIN, GPIO_IN);
    gpio_pull_up(SAFETY_INHIBIT_PIN);
}

bool __not_in_flash_func(safety_inhibit_active)(void) {
    /* Hardware: active-low. */
    if (gpio_get(SAFETY_INHIBIT_PIN) == 0) return true;

    /* Software: MP can request inhibit via the IPC cmd block. */
    if (atomic_load_explicit(&g_ipc.cmd.soft_inhibit,
                             memory_order_acquire) != 0u) {
        return true;
    }
    return false;
}
