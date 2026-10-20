// Common SoftDevice construction only. Each wire protocol keeps its own
// permissions, retry policy, receipt ownership and activation conditions.
#ifndef OTAFIX_DFU_BLE_SHARED_H
#define OTAFIX_DFU_BLE_SHARED_H

#include "ble_dfu.h"

enum {
  DFU_GATT_CONTROL     = 0,
  DFU_GATT_REVISION    = 1,
  DFU_GATT_PACKET      = 2,
  DFU_GATT_SECURE      = 4,
  DFU_GATT_INFORMATION = 9, // Read-only, fixed-length Device Information value.
};

uint32_t dfu_gatt_characteristic_add(ble_dfu_t *service, uint16_t uuid, uint8_t kind, const void *initial,
                                     uint16_t length);
uint32_t dfu_gatt_service_add(ble_dfu_t *service, const ble_uuid128_t *base, uint16_t uuid, bool standard_uuid);
uint32_t dfu_gatt_notify(ble_dfu_t *service, const uint8_t *data, uint16_t length);

#endif
