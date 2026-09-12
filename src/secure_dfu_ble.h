#ifndef OTAFIX_SECURE_DFU_BLE_H
#define OTAFIX_SECURE_DFU_BLE_H
#include "ble_dfu.h"
#include "secure_dfu.h"

uint32_t secure_dfu_ble_init(ble_dfu_t *service);
void     secure_dfu_ble_event(ble_dfu_t *service, ble_evt_t *event);
void     secure_dfu_ble_poll(ble_dfu_t *service);
uint32_t dfu_secure_start(uint32_t size, const uint8_t digest[32]);
void     dfu_secure_activity(void);
void     dfu_secure_connection_policy(bool writing);

#endif
