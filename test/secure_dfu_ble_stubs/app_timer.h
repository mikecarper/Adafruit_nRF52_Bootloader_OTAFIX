#pragma once
#include <stdint.h>
#define APP_TIMER_TICKS(ms) (ms)
uint32_t app_timer_cnt_get(void);
uint32_t app_timer_cnt_diff_compute(uint32_t now, uint32_t then);
