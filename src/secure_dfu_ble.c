#include "secure_dfu_ble.h"
#include "app_error.h"
#include "app_timer.h"
#include "boards.h"
#include "bootloader.h"
#include "dfu.h"
#include "dfu_transport.h"
#include "nrf_sdm.h"
#include <string.h>

static secure_dfu_t      session;
static volatile bool     flash_done;
static volatile uint32_t flash_result;
static uint8_t           notifications[8][15], lengths[8], queue_head, queue_count;
static bool              final_response_sent;
static bool              final_notifications[8];
static bool              notifications_enabled;
static bool              connection_blocked;
static uint16_t          tx_pending;
static uint32_t          last_notification_attempt;

static void flash_callback(uint32_t packet, uint32_t result, uint8_t *data) {
  (void)packet;
  (void)data;
  flash_result = result;
  flash_done   = true;
}

static bool flash_wait(void) {
  uint32_t start = app_timer_cnt_get();
  while (!flash_done) {
    (void)proc_soc(); // Do not recursively dispatch incoming BLE writes.
    board_watchdog_feed();
    if (app_timer_cnt_diff_compute(app_timer_cnt_get(), start) > APP_TIMER_TICKS(10000)) {
      return false;
    }
  }
  return flash_result == NRF_SUCCESS;
}

uint32_t secure_dfu_max_image(void) {
  return DFU_IMAGE_MAX_SIZE_FULL;
}
uint16_t secure_dfu_fwid(void) {
  return SD_FWID_GET(MBR_SIZE);
}
void secure_dfu_activity(void) {
  dfu_secure_activity();
}

bool secure_dfu_begin(const secure_dfu_image_t *image) {
  flash_done = false;
  dfu_secure_connection_policy(true);
  uint32_t result = dfu_secure_start(image->size, image->sha256);
  bool     ok     = result == NRF_SUCCESS && flash_wait();
  dfu_secure_connection_policy(false);
  return ok;
}

bool secure_dfu_write(const uint32_t *data, uint32_t length) {
  dfu_secure_connection_policy(true);
  while (length) {
    // pstorage's lazy-erase pending FIFO holds at most 240 bytes per packet.
    uint32_t            n                   = length < 240 ? length : 240;
    dfu_update_packet_t packet              = {.packet_type = DATA_PACKET};
    packet.params.data_packet.p_data_packet = (uint32_t *)data;
    packet.params.data_packet.packet_length = n / 4;
    flash_done                              = false;
    uint32_t result                         = dfu_data_pkt_handle(&packet);
    if ((result != NRF_SUCCESS && result != NRF_ERROR_INVALID_LENGTH) || !flash_wait()) {
      dfu_secure_connection_policy(false);
      return false;
    }
    data += n / 4;
    length -= n;
  }
  dfu_secure_connection_policy(false);
  return true;
}

bool secure_dfu_finish(void) {
  return dfu_image_validate() == NRF_SUCCESS;
}

static void clear_receipts(void) {
  queue_head = queue_count = 0;
  final_response_sent      = false;
  notifications_enabled    = false;
  tx_pending               = 0;
}

static void flush_notifications(ble_dfu_t *service) {
  while (!connection_blocked && queue_count && notifications_enabled && service->conn_handle != BLE_CONN_HANDLE_INVALID) {
    uint16_t               len    = lengths[queue_head];
    ble_gatts_hvx_params_t params = {0};
    params.handle                 = service->dfu_ctrl_pt_handles.value_handle;
    params.type                   = BLE_GATT_HVX_NOTIFICATION;
    params.p_len                  = &len;
    params.p_data                 = notifications[queue_head];
    last_notification_attempt     = app_timer_cnt_get();
    uint32_t err                  = sd_ble_gatts_hvx(service->conn_handle, &params);
    if (err == NRF_ERROR_RESOURCES || err == NRF_ERROR_BUSY) {
      return;
    }
    if (err == NRF_ERROR_INVALID_STATE || err == BLE_ERROR_GATTS_SYS_ATTR_MISSING) {
      return;
    }
    if (err == BLE_ERROR_INVALID_CONN_HANDLE || err == NRF_ERROR_TIMEOUT) {
      // Flash waits pump SOC events only: the disconnect event may still be
      // queued while this cached handle is already unusable. Keep the session
      // for SELECT/CRC resume, but never activate from this lost connection's
      // pending receipts. The normal disconnect event restarts advertising.
      clear_receipts();
      return;
    }
    APP_ERROR_CHECK(err);
    ++tx_pending;
    if (final_notifications[queue_head]) {
      final_response_sent = true;
    }
    queue_head = (queue_head + 1) % 8;
    --queue_count;
  }
}

void secure_dfu_ble_poll(ble_dfu_t *service) {
  // Called after scheduled BLE events (including MTU/sys-attribute setup),
  // never from flash_wait. A blocked first receipt has no HVN_TX_COMPLETE to
  // wake it, so retry from the existing main loop at most every 100 ms.
  if (!connection_blocked && queue_count && notifications_enabled && service->conn_handle != BLE_CONN_HANDLE_INVALID &&
      app_timer_cnt_diff_compute(app_timer_cnt_get(), last_notification_attempt) >= APP_TIMER_TICKS(100)) {
    flush_notifications(service);
  }
}

static uint32_t characteristic(ble_dfu_t *service, uint16_t uuid, bool control) {
  ble_gatts_char_md_t md      = {0};
  ble_gatts_attr_md_t attr_md = {0}, cccd_md = {0};
  ble_uuid_t          id      = {.uuid = uuid, .type = service->uuid_type};
  md.char_props.write         = control;
  md.char_props.write_wo_resp = !control;
  md.char_props.notify        = control;
  BLE_GAP_CONN_SEC_MODE_SET_OPEN(&attr_md.write_perm);
  attr_md.vloc = BLE_GATTS_VLOC_STACK;
  attr_md.vlen = 1;
  if (control) {
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd_md.read_perm);
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd_md.write_perm);
    cccd_md.vloc = BLE_GATTS_VLOC_STACK;
    md.p_cccd_md = &cccd_md;
  }
  ble_gatts_attr_t value = {0};
  value.p_uuid           = &id;
  value.p_attr_md        = &attr_md;
  value.max_len          = control ? 20 : BLEGATT_ATT_MTU_MAX - 3;
  return sd_ble_gatts_characteristic_add(service->service_handle, &md, &value,
                                         control ? &service->dfu_ctrl_pt_handles : &service->dfu_pkt_handles);
}

uint32_t secure_dfu_ble_init(ble_dfu_t *service) {
  secure_dfu_init(&session);
  connection_blocked = true;
  dfu_register_callback(flash_callback);
  service->conn_handle     = BLE_CONN_HANDLE_INVALID;
  const ble_uuid128_t base = {
    {0x50, 0xEA, 0xDA, 0x30, 0x88, 0x83, 0xB8, 0x9F, 0x60, 0x4F, 0x15, 0xF3, 0, 0, 0xC9, 0x8E}};
  uint32_t err = sd_ble_uuid_vs_add(&base, &service->uuid_type);
  if (err != NRF_SUCCESS) {
    return err;
  }
  ble_uuid_t uuid = {.uuid = 0xFE59, .type = BLE_UUID_TYPE_BLE};
  err             = sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &uuid, &service->service_handle);
  if (err != NRF_SUCCESS) {
    return err;
  }
  err = characteristic(service, 1, true);
  if (err != NRF_SUCCESS) {
    return err;
  }
  err = characteristic(service, 2, false);
  // Common DIS/cache logic expects the last DFU value handle in this member.
  service->dfu_rev_handles.value_handle = service->dfu_pkt_handles.value_handle;
  return err;
}

void secure_dfu_ble_event(ble_dfu_t *service, ble_evt_t *event) {
  switch (event->header.evt_id) {
    case BLE_GAP_EVT_CONNECTED:
      service->conn_handle = event->evt.gap_evt.conn_handle;
      clear_receipts();
      connection_blocked = false;
      session.prn_count  = 0;
      break;
    case BLE_GAP_EVT_DISCONNECTED:
      service->conn_handle = BLE_CONN_HANDLE_INVALID;
      connection_blocked   = true;
      clear_receipts();
      // Session metadata, CRCs, and the partial object remain in RAM.
      break;
    case BLE_GATTS_EVT_HVN_TX_COMPLETE:
      if (connection_blocked) {
        break;
      }
      if (event->evt.gatts_evt.params.hvn_tx_complete.count <= tx_pending) {
        tx_pending -= event->evt.gatts_evt.params.hvn_tx_complete.count;
      }
      if (final_response_sent && queue_count == 0 && tx_pending == 0) {
        final_response_sent = false;
        APP_ERROR_CHECK(dfu_transport_ble_close());
        APP_ERROR_CHECK(dfu_image_activate());
      } else {
        flush_notifications(service);
      }
      break;
    case BLE_GATTS_EVT_WRITE: {
      if (connection_blocked || service->conn_handle == BLE_CONN_HANDLE_INVALID) {
        break;
      }
      const ble_gatts_evt_write_t *w = &event->evt.gatts_evt.params.write;
      if (w->handle == service->dfu_ctrl_pt_handles.cccd_handle) {
        notifications_enabled = w->offset == 0 && w->len == 2 && w->data[0] == 1 && w->data[1] == 0;
        flush_notifications(service);
        break;
      }
      if (!notifications_enabled) {
        break;
      }
      bool control = w->handle == service->dfu_ctrl_pt_handles.value_handle;
      if (!control && w->handle != service->dfu_pkt_handles.value_handle) {
        break;
      }
      if (w->offset != 0 || (w->op != BLE_GATTS_OP_WRITE_REQ && w->op != BLE_GATTS_OP_WRITE_CMD)) {
        break;
      }
      if (queue_count == 8) {
        // Never consume bytes or erase flash when their required receipt cannot
        // be queued. A compliant PRN-limited sender cannot fill this queue.
        // Quarantine this link until DISCONNECTED. Clearing counters while old
        // notifications remain in the SoftDevice would let re-subscription
        // mistake an old TX completion for a new final EXECUTE receipt.
        connection_blocked = true;
        uint32_t err = sd_ble_gap_disconnect(service->conn_handle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
        if (err != BLE_ERROR_INVALID_CONN_HANDLE && err != NRF_ERROR_INVALID_STATE) {
          APP_ERROR_CHECK(err);
        }
        // Do not close the DFU transport: its ordinary disconnect handler must
        // restart advertising so the retained session can resume on a new link.
        break;
      }
      uint8_t slot  = (queue_head + queue_count) % 8;
      lengths[slot] = control ? secure_dfu_control(&session, w->data, w->len, notifications[slot])
                              : secure_dfu_packet(&session, w->data, w->len, notifications[slot]);
      // On reconnect, the phone re-executes COMMAND before selecting DATA.
      // That COMMAND receipt must never trigger application activation, even
      // if every data byte was committed before the previous link was lost.
      final_notifications[slot] = control && w->len == 1 && w->data[0] == 4 && session.selected == 2 &&
                                  session.completed && lengths[slot] == 3 && notifications[slot][2] == 1;
      if (lengths[slot]) {
        ++queue_count;
      }
      flush_notifications(service);
      break;
    }
    default:
      break;
  }
}
