#include "ignition.h"
#include "hardware/gpio.h"

#define COIL_PIN 15u

static volatile bool s_active = false;

void ignition_init(void) {
    gpio_init(COIL_PIN);
    gpio_set_dir(COIL_PIN, GPIO_OUT);
    /* Drive LOW before anything else can fire. The hardware pull-down
     * on the IGBT gate (10 kΩ documented in CLAUDE.md) holds it low if
     * we never get this far. */
    gpio_put(COIL_PIN, 0);
    s_active = false;
}

void __not_in_flash_func(ignition_on)(void) {
    gpio_put(COIL_PIN, 1);
    s_active = true;
}

void __not_in_flash_func(ignition_force_off)(void) {
    gpio_put(COIL_PIN, 0);
    s_active = false;
}

bool ignition_is_active(void) {
    return s_active;
}
