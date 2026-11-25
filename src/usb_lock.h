#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

// MeshCore adds this optional entry after the littlefs-v1 superblock. Blocks
// 0 and 1 are the fixed superblock pair. Lock if either copy has the entry:
// an interrupted unlock must be retried before wired recovery is available.
static const char usb_lock_marker[] __attribute__((used, aligned(4))) = "MCULOCK1";
static inline bool mesh_usb_locked(const uint8_t *fs) {
  const char *marker = usb_lock_marker;
  // Keep the capability discoverable in the installed binary even under LTO.
  __asm__ ("" : "+r"(marker));
  return memcmp(fs + 52, marker, 8) == 0 || memcmp(fs + 128 + 52, marker, 8) == 0;
}
#if defined(NRF52840_XXAA)
#define MESH_USB_LOCK_FS ((const uint8_t *)0xed000u)
#else
#define MESH_USB_LOCK_FS ((const uint8_t *)0x6d000u)
#endif
