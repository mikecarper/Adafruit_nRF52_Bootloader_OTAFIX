#ifndef DFU_BLE_PEER_DATA_LAYOUT_H__
#define DFU_BLE_PEER_DATA_LAYOUT_H__

#include <stddef.h>
#include <stdint.h>

#include "dfu_ble_svc.h"

// Bluefruit52Lib BLEDfu writes this retained record before entering the bootloader.
#define DFU_BLE_RETAINED_PEER_DATA_ADDRESS     0x20007F80UL
#define DFU_BLE_RETAINED_PEER_DATA_SIZE        60u
#define DFU_BLE_RETAINED_PEER_DATA_CRC_OFFSET  60u
#define DFU_BLE_RETAINED_PEER_DATA_RECORD_SIZE 62u

typedef struct {
  dfu_ble_peer_data_t peer_data;
  uint16_t            crc;
} dfu_ble_retained_peer_data_t;

typedef char
  dfu_ble_peer_data_size_must_match_writer[(sizeof(dfu_ble_peer_data_t) == DFU_BLE_RETAINED_PEER_DATA_SIZE) ? 1 : -1];
typedef char dfu_ble_peer_data_must_start_record[(offsetof(dfu_ble_retained_peer_data_t, peer_data) == 0u) ? 1 : -1];
typedef char dfu_ble_peer_data_crc_offset_must_match_writer
  [(offsetof(dfu_ble_retained_peer_data_t, crc) == DFU_BLE_RETAINED_PEER_DATA_CRC_OFFSET) ? 1 : -1];
typedef char dfu_ble_peer_data_record_size_must_match_writer
  [(sizeof(dfu_ble_retained_peer_data_t) == DFU_BLE_RETAINED_PEER_DATA_RECORD_SIZE) ? 1 : -1];

#endif // DFU_BLE_PEER_DATA_LAYOUT_H__
