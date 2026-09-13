#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "../src/boards/lilygo_techo_lite/board.h"
#define STATIC_ASSERT(condition) _Static_assert(condition, #condition)
#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define PRINTF(...) ((void)0)
#define PRINT_HEX(...) ((void)0)
typedef struct {
  struct { uint32_t RAM; } INFO;
} uf2_test_ficr_t;
extern uf2_test_ficr_t uf2_test_ficr;
#define NRF_FICR (&uf2_test_ficr)
