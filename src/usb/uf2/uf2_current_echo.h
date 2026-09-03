#ifndef UF2_CURRENT_ECHO_H_
#define UF2_CURRENT_ECHO_H_

#include <stdbool.h>
#include <stdint.h>

// CURRENT.UF2 is a synthetic, read-only view of application flash. Host writes
// to its physical clusters are filesystem traffic, not a firmware transfer.
// A saved CURRENT.UF2 copied back under another filename is allocated outside
// this extent and therefore still follows the normal UF2 write path.
static inline bool uf2_current_lba_is_synthetic(
    uint32_t disk_lba,
    uint32_t current_first_lba,
    uint32_t current_sector_count) {
  if (disk_lba < current_first_lba) {
    return false;
  }

  uint32_t const current_index = disk_lba - current_first_lba;
  return current_index < current_sector_count;
}

#endif
