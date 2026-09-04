#include "dfu_timeout.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static uint32_t reference_ticks(uint32_t milliseconds) {
  return (uint32_t)(((uint64_t)milliseconds * 32768U + 500U) / 1000U);
}

int main(void) {
  static uint32_t const cases[] = {
    0U, 1U, 2U, 124U, 125U, 126U, 999U, 1000U, 3000U, 30000U,
    511999U, 1000000U, UINT32_MAX - 1U, UINT32_MAX,
  };

  for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
    assert(dfu_timeout_ticks(cases[i]) == reference_ticks(cases[i]));
  }

  puts("DFU timeout tick conversion: PASS");
  return 0;
}
