#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "dfu_ble_peer_data_layout.h"

int main(void) {
  if (sizeof(dfu_ble_peer_data_t) != DFU_BLE_RETAINED_PEER_DATA_SIZE ||
      offsetof(dfu_ble_retained_peer_data_t, peer_data) != 0u ||
      offsetof(dfu_ble_retained_peer_data_t, crc) != DFU_BLE_RETAINED_PEER_DATA_CRC_OFFSET ||
      sizeof(dfu_ble_retained_peer_data_t) != DFU_BLE_RETAINED_PEER_DATA_RECORD_SIZE) {
    return 1;
  }

  printf("retained BLE peer data: base=0x%08lX data=%u CRC=+%u record=%u PASS\n",
         (unsigned long)DFU_BLE_RETAINED_PEER_DATA_ADDRESS, (unsigned)DFU_BLE_RETAINED_PEER_DATA_SIZE,
         (unsigned)DFU_BLE_RETAINED_PEER_DATA_CRC_OFFSET, (unsigned)DFU_BLE_RETAINED_PEER_DATA_RECORD_SIZE);
  return 0;
}
