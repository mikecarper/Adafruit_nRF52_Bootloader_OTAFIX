// Experimental size profile: construct the same SoftDevice configurations in
// one frame. Typed payloads retain the SDK's field and bitfield encodings.
#ifndef OTAFIX_DFU_BLE_CONFIG_H
#define OTAFIX_DFU_BLE_CONFIG_H

#include "ble.h"
#include <stddef.h>
#include <string.h>

typedef union {
  ble_gap_cfg_role_count_t        role;
  ble_gatts_cfg_service_changed_t changed;
  ble_common_cfg_vs_uuid_t        uuids;
  ble_gatt_conn_cfg_t             gatt;
  ble_gap_conn_cfg_t              gap;
  ble_gatts_conn_cfg_t            gatts;
  ble_gattc_conn_cfg_t            gattc;
} dfu_ble_cfg_value_t;

__attribute__((noinline, noclone)) static void dfu_ble_stack_configure(uint32_t ram_start) {
  enum {
    GLOBAL_CONFIGURATION_COUNT = 3
  };
  static const struct {
    uint16_t            id;
    dfu_ble_cfg_value_t value;
  } configurations[] = {
    {BLE_GAP_CFG_ROLE_COUNT, {.role = {.adv_set_count = 1, .periph_role_count = 1}}},
    {BLE_GATTS_CFG_SERVICE_CHANGED, {.changed = {.service_changed = 1}}},
    {BLE_COMMON_CFG_VS_UUID, {.uuids = {.vs_uuid_count = 2}}},
    {BLE_CONN_CFG_GATT, {.gatt = {.att_mtu = BLEGATT_ATT_MTU_MAX}}},
    {BLE_CONN_CFG_GAP, {.gap = {.conn_count = 1, .event_length = BLEGAP_EVENT_LENGTH}}},
    {BLE_CONN_CFG_GATTS, {.gatts = {.hvn_tx_queue_size = BLEGATTS_HVN_QSIZE}}},
    {BLE_CONN_CFG_GATTC, {.gattc = {.write_cmd_tx_queue_size = BLEGATTC_WRCMD_QSIZE}}},
  };
  _Static_assert(sizeof(dfu_ble_cfg_value_t) <= sizeof(ble_cfg_t), "configuration payload exceeds SDK global union");
  _Static_assert(sizeof(dfu_ble_cfg_value_t) <= sizeof(((ble_cfg_t *)0)->conn_cfg.params),
                 "configuration payload exceeds SDK connection union");
  _Static_assert(offsetof(ble_cfg_t, conn_cfg.conn_cfg_tag) == 0, "SDK connection tag must be at byte zero");
  for (unsigned i = 0; i < sizeof(configurations) / sizeof(configurations[0]); ++i) {
    ble_cfg_t      config = {0};
    const uint16_t id     = configurations[i].id;
    // Global payloads overwrite byte zero; connection payloads retain the tag.
    // The three global configurations precede the four connection settings.
    config.conn_cfg.conn_cfg_tag = BLE_CONN_CFG_HIGH_BANDWIDTH;
    void *destination            = i < GLOBAL_CONFIGURATION_COUNT ? (void *)&config : (void *)&config.conn_cfg.params;
    memcpy(destination, &configurations[i].value, sizeof(dfu_ble_cfg_value_t));
    uint32_t error = sd_ble_cfg_set(id, &config, ram_start);
    // Preserve the original policy: only the added dual-profile UUID count
    // is fatal here. Do not change handling of the existing setup requests.
    if (id == BLE_COMMON_CFG_VS_UUID) {
      APP_ERROR_CHECK(error);
    }
  }
}

#endif
