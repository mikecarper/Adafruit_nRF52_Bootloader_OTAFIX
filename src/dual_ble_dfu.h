// Experimental shared-flash ownership. A reconnect must not switch protocols
// underneath the retained Secure offset/CRC or an asynchronous Legacy write.
#ifndef OTAFIX_DUAL_BLE_DFU_H
#define OTAFIX_DUAL_BLE_DFU_H

#include <stdbool.h>
#include <stdint.h>

enum {
  DUAL_DFU_NONE,
  DUAL_DFU_LEGACY,
  DUAL_DFU_SECURE
};

static inline bool dual_dfu_claim(uint8_t *owner, uint8_t requested) {
  if (*owner != DUAL_DFU_NONE && *owner != requested) {
    return false;
  }
  *owner = requested;
  return true;
}

#endif
