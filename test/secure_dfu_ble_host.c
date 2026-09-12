// Compile the complete production BLE adapter and protocol. Only hardware,
// SoftDevice entry points, and the asynchronous flash backend are simulated.
#define __STATIC_INLINE static inline
#define __REV(value)    __builtin_bswap32(value)
#include "dfu.h"
#undef DFU_IMAGE_MAX_SIZE_FULL
#define DFU_IMAGE_MAX_SIZE_FULL 10000u
#undef SD_FWID_GET
#define SD_FWID_GET(base) 0xB6u
#include "../src/secure_dfu_ble.c"
#include "sha256.h"
#include <assert.h>
#include <setjmp.h>

static ble_dfu_t      service;
static jmp_buf        fault_return;
static uint32_t       fault_code, hvx_error, flash_error, clock_ticks, watchdog_feeds;
static uint32_t       hvx_calls;
static uint32_t       begins, writes, finishes, activations, closes;
static uint32_t       image_size, flash_offset, pending_size;
static uint32_t       disconnect_on_flash;
static const uint8_t *pending_data;
static bool           pending, stall_flash;
static uint8_t        flash_image[10000], expected_hash[32], receipt[15];
static uint16_t       receipt_size;
static dfu_callback_t completion;

void test_app_error(uint32_t error) {
  fault_code = error;
  longjmp(fault_return, 1);
}
uint32_t app_timer_cnt_get(void) {
  return clock_ticks++ & 0xFFFFFFu;
}
uint32_t app_timer_cnt_diff_compute(uint32_t now, uint32_t then) {
  return (now - then) & 0xFFFFFFu;
}
void board_watchdog_feed(void) {
  ++watchdog_feeds;
}
void dfu_register_callback(dfu_callback_t callback) {
  completion = callback;
}
void dfu_secure_activity(void) {
}
void dfu_secure_connection_policy(bool writing) {
  (void)writing;
}

uint32_t proc_soc(void) {
  if (!pending || stall_flash) {
    return NRF_ERROR_NOT_FOUND;
  }
  pending = false;
  if (disconnect_on_flash) {
    hvx_error = disconnect_on_flash;
  }
  if (pending_data && flash_error == NRF_SUCCESS) {
    assert(flash_offset + pending_size <= sizeof(flash_image));
    memcpy(flash_image + flash_offset, pending_data, pending_size);
    flash_offset += pending_size;
    ++writes;
  }
  completion(pending_data ? DATA_PACKET : START_PACKET, flash_error, (uint8_t *)pending_data);
  return NRF_SUCCESS;
}
uint32_t dfu_secure_start(uint32_t size, const uint8_t digest[32]) {
  assert(!pending);
  ++begins;
  image_size = size;
  memcpy(expected_hash, digest, 32);
  memset(flash_image, 0xff, sizeof(flash_image));
  flash_offset = pending_size = 0;
  pending_data                = NULL;
  pending                     = true;
  return NRF_SUCCESS;
}
uint32_t dfu_data_pkt_handle(dfu_update_packet_t *packet) {
  assert(!pending);
  pending_data = (const uint8_t *)packet->params.data_packet.p_data_packet;
  pending_size = packet->params.data_packet.packet_length * 4;
  pending      = true;
  return NRF_SUCCESS;
}
uint32_t dfu_image_validate(void) {
  uint8_t      digest[32];
  sha256_ctx_t sha;
  sha256_init(&sha);
  sha256_update(&sha, flash_image, flash_offset);
  sha256_final(&sha, digest);
  ++finishes;
  return flash_offset == image_size && memcmp(digest, expected_hash, 32) == 0 ? NRF_SUCCESS : NRF_ERROR_INVALID_DATA;
}
uint32_t dfu_transport_ble_close(void) {
  ++closes;
  return NRF_SUCCESS;
}
uint32_t dfu_image_activate(void) {
  ++activations;
  return NRF_SUCCESS;
}

uint32_t sd_ble_uuid_vs_add(const ble_uuid128_t *uuid, uint8_t *type) {
  (void)uuid;
  *type = BLE_UUID_TYPE_VENDOR_BEGIN;
  return NRF_SUCCESS;
}
uint32_t sd_ble_gatts_service_add(uint8_t type, const ble_uuid_t *uuid, uint16_t *handle) {
  (void)type;
  (void)uuid;
  *handle = 1;
  return NRF_SUCCESS;
}
uint32_t sd_ble_gatts_characteristic_add(uint16_t handle, const ble_gatts_char_md_t *md, const ble_gatts_attr_t *value,
                                         ble_gatts_char_handles_t *handles) {
  (void)handle;
  (void)value;
  handles->value_handle = md->char_props.notify ? 2 : 4;
  handles->cccd_handle  = md->char_props.notify ? 3 : 0;
  return NRF_SUCCESS;
}
uint32_t sd_ble_gatts_hvx(uint16_t handle, const ble_gatts_hvx_params_t *params) {
  assert(handle == service.conn_handle);
  ++hvx_calls;
  if (hvx_error) {
    return hvx_error;
  }
  assert(*params->p_len <= sizeof(receipt));
  memcpy(receipt, params->p_data, *params->p_len);
  receipt_size = *params->p_len;
  return NRF_SUCCESS;
}

static void dispatch(ble_evt_t *event) {
  if (!setjmp(fault_return)) {
    secure_dfu_ble_event(&service, event);
  }
}
void test_ble_reset(void) {
  clear_receipts();
  fault_code = hvx_error = flash_error = clock_ticks = watchdog_feeds = 0;
  hvx_calls                                                           = 0;
  begins = writes = finishes = activations = closes = 0;
  image_size = flash_offset = pending_size = disconnect_on_flash = 0;
  pending = stall_flash = false;
  pending_data          = NULL;
  receipt_size          = 0;
  memset(&service, 0, sizeof(service));
  assert(secure_dfu_ble_init(&service) == NRF_SUCCESS);
}
void test_ble_connection(bool connected) {
  ble_evt_t event               = {0};
  event.header.evt_id           = connected ? BLE_GAP_EVT_CONNECTED : BLE_GAP_EVT_DISCONNECTED;
  event.evt.gap_evt.conn_handle = 0;
  dispatch(&event);
}
void test_ble_write(uint16_t handle, const uint8_t *data, size_t size) {
  union {
    ble_evt_t event;
    uint8_t   bytes[sizeof(ble_evt_t) + 256];
  } buffer = {0};
  assert(size <= 244);
  ble_evt_t *event                 = &buffer.event;
  event->header.evt_id             = BLE_GATTS_EVT_WRITE;
  event->evt.gatts_evt.conn_handle = 0;
  ble_gatts_evt_write_t *write     = &event->evt.gatts_evt.params.write;
  write->handle                    = handle;
  write->op                        = handle == 4 ? BLE_GATTS_OP_WRITE_CMD : BLE_GATTS_OP_WRITE_REQ;
  write->len                       = (uint16_t)size;
  memcpy(write->data, data, size);
  receipt_size = 0;
  dispatch(event);
}
void test_ble_tx_complete(uint16_t count) {
  ble_evt_t event                                  = {0};
  event.header.evt_id                              = BLE_GATTS_EVT_HVN_TX_COMPLETE;
  event.evt.gatts_evt.params.hvn_tx_complete.count = count;
  dispatch(&event);
}
void test_ble_poll(uint32_t elapsed) {
  clock_ticks += elapsed;
  if (!setjmp(fault_return)) {
    secure_dfu_ble_poll(&service);
  }
}
void test_ble_set_clock(uint32_t ticks) {
  clock_ticks = ticks;
}
void test_ble_ready(unsigned kind) {
  const uint16_t ids[] = {BLE_GATTS_EVT_EXCHANGE_MTU_REQUEST, BLE_GATTS_EVT_SYS_ATTR_MISSING,
                          BLE_GAP_EVT_CONN_SEC_UPDATE};
  assert(kind < sizeof(ids) / sizeof(ids[0]));
  ble_evt_t event     = {0};
  event.header.evt_id = ids[kind];
  dispatch(&event);
}
uint32_t test_ble_hvx_calls(void) {
  return hvx_calls;
}
void test_ble_hvx_error(uint32_t error) {
  hvx_error = error;
}
void test_ble_flash_error(uint32_t error) {
  flash_error = error;
}
void test_ble_disconnect_on_flash(uint32_t error) {
  disconnect_on_flash = error;
}
void test_ble_stall_flash(bool stall) {
  stall_flash = stall;
}
void test_ble_finish_pending(void) {
  (void)proc_soc();
}
uint32_t test_ble_fault(void) {
  return fault_code;
}
uint32_t test_ble_activations(void) {
  return activations;
}
uint32_t test_ble_begins(void) {
  return begins;
}
uint32_t test_ble_writes(void) {
  return writes;
}
uint32_t test_ble_finishes(void) {
  return finishes;
}
uint32_t test_ble_watchdog_feeds(void) {
  return watchdog_feeds;
}
uint32_t test_ble_queued(void) {
  return queue_count;
}
uint32_t test_ble_tx_pending(void) {
  return tx_pending;
}
bool test_ble_failed(void) {
  return session.failed;
}
bool test_ble_completed(void) {
  return session.completed;
}
const uint8_t *test_ble_flash(void) {
  return flash_image;
}
size_t test_ble_receipt(uint8_t out[15]) {
  memcpy(out, receipt, receipt_size);
  return receipt_size;
}
