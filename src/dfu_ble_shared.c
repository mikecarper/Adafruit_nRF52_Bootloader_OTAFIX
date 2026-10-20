#include "boards.h"
#include "sdk_config.h"
#include "dfu_ble_shared.h"
#include <string.h>

// Do not let LTO create a copy for each of the six constant characteristic
// kinds. These constructors deliberately share one stack frame and SVC call.
__attribute__((noinline, noclone)) uint32_t dfu_gatt_characteristic_add(ble_dfu_t *service, uint16_t uuid, uint8_t kind,
                                                                        const void *initial, uint16_t length) {
  const bool                         is_revision = (kind & DFU_GATT_REVISION) != 0;
  const bool                         is_packet   = (kind & DFU_GATT_PACKET) != 0;
  const bool                         is_secure   = (kind & DFU_GATT_SECURE) != 0;
  ble_gatts_char_md_t                md          = {0};
  ble_gatts_attr_md_t                attr_md = {0}, cccd_md = {0};
  ble_uuid_t                         id             = {.uuid = uuid, .type = service->uuid_type};
  static const ble_gatt_char_props_t properties[10] = {
    [DFU_GATT_CONTROL]                   = {.write = 1, .notify = 1},
    [DFU_GATT_REVISION]                  = {.read = 1},
    [DFU_GATT_PACKET]                    = {.write = 1, .write_wo_resp = 1},
    [DFU_GATT_SECURE | DFU_GATT_CONTROL] = {.write = 1, .notify = 1},
    [DFU_GATT_SECURE | DFU_GATT_PACKET]  = {.write_wo_resp = 1},
    [DFU_GATT_INFORMATION]               = {.read = 1},
  };
  md.char_props = properties[kind];
  if (is_revision) {
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&attr_md.read_perm);
  } else {
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&attr_md.write_perm);
  }
  attr_md.vloc    = BLE_GATTS_VLOC_STACK;
  attr_md.vlen    = kind != DFU_GATT_INFORMATION;
  attr_md.wr_auth = kind == DFU_GATT_CONTROL;
  if (kind == (DFU_GATT_SECURE | DFU_GATT_CONTROL)) {
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd_md.read_perm);
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd_md.write_perm);
    cccd_md.vloc = BLE_GATTS_VLOC_STACK;
    md.p_cccd_md = &cccd_md;
  }
  ble_gatts_attr_t value            = {0};
  value.p_uuid                      = &id;
  value.p_attr_md                   = &attr_md;
  value.init_len                    = is_revision ? length : 0;
  value.max_len                     = is_revision ? length
                                      : is_packet ? BLEGATT_ATT_MTU_MAX - 3
                                      : is_secure ? 20
                                                  : BLE_GATT_ATT_MTU_DEFAULT;
  value.p_value                     = is_revision ? (uint8_t *)initial : NULL;
  ble_gatts_char_handles_t *handles = is_revision ? &service->dfu_rev_handles
                                      : is_packet ? &service->dfu_pkt_handles
                                                  : &service->dfu_ctrl_pt_handles;
  return sd_ble_gatts_characteristic_add(service->service_handle, &md, &value, handles);
}

__attribute__((noinline, noclone)) uint32_t dfu_gatt_service_add(ble_dfu_t *service, const ble_uuid128_t *base,
                                                                 uint16_t uuid, bool standard_uuid) {
  uint8_t  type;
  uint32_t err = sd_ble_uuid_vs_add(base, &type);
  if (err != NRF_SUCCESS) {
    return err;
  }
  ble_uuid_t id = {.uuid = uuid, .type = standard_uuid ? BLE_UUID_TYPE_BLE : type};
  err           = sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &id, &service->service_handle);
  if (err == NRF_SUCCESS) {
    service->uuid_type = type;
  }
  return err;
}

__attribute__((noinline, noclone)) uint32_t dfu_gatt_notify(ble_dfu_t *service, const uint8_t *data, uint16_t length) {
  // Length is an in/out SVC parameter. Reconstruct it and all metadata on every
  // attempt; neither a blocked Secure receipt nor Legacy retry may inherit it.
  ble_gatts_hvx_params_t params = {0};
  params.handle                 = service->dfu_ctrl_pt_handles.value_handle;
  params.type                   = BLE_GATT_HVX_NOTIFICATION;
  params.p_len                  = &length;
  params.p_data                 = data;
  return sd_ble_gatts_hvx(service->conn_handle, &params);
}
