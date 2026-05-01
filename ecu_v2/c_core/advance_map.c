#include "advance_map.h"

/* Generic linear interp helper. */
static int32_t interp(uint32_t rpm,
                      const uint16_t *xs, const int32_t *ys,
                      uint16_t n) {
    if (n == 0) return 0;
    if (rpm <= xs[0]) return ys[0];
    for (uint16_t i = 1; i < n; ++i) {
        if (rpm <= xs[i]) {
            uint32_t x0 = xs[i - 1], x1 = xs[i];
            int32_t  y0 = ys[i - 1], y1 = ys[i];
            if (x1 <= x0) return y1;
            return y0 + (int32_t)(((int64_t)(rpm - x0) * (y1 - y0)) / (int64_t)(x1 - x0));
        }
    }
    return ys[n - 1];
}

int16_t __not_in_flash_func(advance_map_lookup_advance_cd)(const ecu_profile_t *p,
                                                            uint32_t rpm) {
    if (p->adv_count == 0) return 1200;  /* sane fallback ~12° */
    int32_t ys[ECU_ADV_MAP_MAX];
    for (uint16_t i = 0; i < p->adv_count; ++i) ys[i] = (int32_t)p->adv_cd[i];
    int32_t v = interp(rpm, p->adv_rpm, ys, p->adv_count);
    if (v >  32767) v =  32767;
    if (v < -32768) v = -32768;
    return (int16_t)v;
}

uint32_t __not_in_flash_func(advance_map_lookup_dwell_us)(const ecu_profile_t *p,
                                                           uint32_t rpm) {
    if (p->dwell_count == 0) return ECU_DWELL_TARGET_US;
    int32_t ys[ECU_DWELL_MAP_MAX];
    for (uint16_t i = 0; i < p->dwell_count; ++i) ys[i] = (int32_t)p->dwell_us[i];
    int32_t v = interp(rpm, p->dwell_rpm, ys, p->dwell_count);
    if (v < (int32_t)ECU_DWELL_MIN_US) v = (int32_t)ECU_DWELL_MIN_US;
    if (v > (int32_t)ECU_DWELL_MAX_US) v = (int32_t)ECU_DWELL_MAX_US;
    return (uint32_t)v;
}
