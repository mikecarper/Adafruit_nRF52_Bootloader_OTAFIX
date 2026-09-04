#pragma once

#include <stdint.h>

// APP_TIMER_CLOCK_FREQ is 32768 Hz with this project's fixed RTC prescaler 0.
// Reduce 32768/1000 to 4096/125 and split the quotient so every uint32_t
// millisecond input produces the same low 32 bits as APP_TIMER_TICKS without
// linking the Arm 64-bit division runtime into the size-constrained image.
static inline uint32_t dfu_timeout_ticks(uint32_t milliseconds) {
  uint32_t const whole = milliseconds / 125U;
  uint32_t const remainder = milliseconds - whole * 125U;
  return (whole << 12) + ((remainder * 4096U + 62U) / 125U);
}
