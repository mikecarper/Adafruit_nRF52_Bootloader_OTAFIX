#pragma once
#include <stdint.h>
typedef struct {
  uint32_t bank_0_size;
} bootloader_settings_t;
void bootloader_util_settings_get(const bootloader_settings_t **settings);
