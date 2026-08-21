#ifndef UF2_APP_FLASH_H_
#define UF2_APP_FLASH_H_

#include <stdbool.h>
#include <stdint.h>

typedef enum {
  UF2_APP_FLASH_INVALIDATE_SETTINGS,
  UF2_APP_FLASH_ERASE_PAGE,
  UF2_APP_FLASH_PROGRAM_BLOCK,
} uf2_app_flash_action_t;

static inline uf2_app_flash_action_t uf2_app_flash_next_action(bool* settings_invalidated,
                                                               uint8_t* erased_mask,
                                                               uint32_t page) {
  if (!*settings_invalidated) {
    *settings_invalidated = true;
    return UF2_APP_FLASH_INVALIDATE_SETTINGS;
  }

  uint8_t const mask = 1U << (page % 8);
  uint32_t const pos = page / 8;
  if (!(erased_mask[pos] & mask)) {
    erased_mask[pos] |= mask;
    return UF2_APP_FLASH_ERASE_PAGE;
  }

  return UF2_APP_FLASH_PROGRAM_BLOCK;
}

#endif
