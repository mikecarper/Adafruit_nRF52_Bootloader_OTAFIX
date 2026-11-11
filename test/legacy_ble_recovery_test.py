#!/usr/bin/env python3
"""Run production Legacy disconnect/callback paths with delayed flash ownership."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ble_recovery_test import CORE, ROOT, declaration, function


class LegacyBleRecoveryTest(unittest.TestCase):
    def test_disconnect_restarts_only_accepted_legacy_sessions_without_recycling_owned_buffers(self):
        source = (CORE / "dfu_transport_ble.c").read_text()
        types = (CORE / "dfu_types.h").read_text()
        event = function(source, "static void on_ble_evt(")
        start = event.index("case BLE_GAP_EVT_DISCONNECTED:")
        end = event.index("case BLE_GAP_EVT_CONN_PARAM_UPDATE:", start)
        disconnect = event[start:end]
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "nrf_error.h"
#define APP_ERROR_CHECK(code) assert((code) == NRF_SUCCESS)
#define BLE_GAP_EVT_DISCONNECTED 2
#define BLE_CONN_HANDLE_INVALID 0xffff
#define BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION 0x13
#define APP_DIRECTED_ADV_TIMEOUT 3
#define START_PACKET 3
#define DATA_PACKET 4
#define INIT_PACKET 1
#define SD_IMAGE_SIZE_OFFSET 0
#define BL_IMAGE_SIZE_OFFSET 4
#define APP_IMAGE_SIZE_OFFSET 8
#define BLE_DFU_START_PROCEDURE 1
#define BLE_DFU_INIT_PROCEDURE 2
#define BLE_DFU_RECEIVE_APP_PROCEDURE 3
#define BLE_DFU_RESP_VAL_SUCCESS 1
#define BLE_DFU_RESP_VAL_NOT_SUPPORTED 2
typedef unsigned ble_dfu_resp_val_t;
typedef struct { unsigned unused; } ble_dfu_t;
typedef struct { struct { struct { uint32_t len; uint8_t *p_data; } ble_dfu_pkt_write; } evt; } ble_dfu_evt_t;
'''
        for name in ("dfu_start_packet_t;", "dfu_data_packet_t;", "dfu_update_packet_t;"):
            harness += declaration(types, name)
        harness += r'''
static bool m_is_advertising, m_ble_data_policy_active, m_service_change_pending;
static bool m_service_attrs_initialized, m_accum_active, m_tear_down_in_progress;
static uint16_t m_conn_handle, m_accum_len;
static unsigned m_direct_adv_cnt;
static uint32_t m_reported_image_size, m_num_of_firmware_bytes_rcvd;
static uint8_t m_update_mode;
static void *mp_final_packet;
static ble_dfu_t m_dfu;
static unsigned advertising, resets, responses, consumed, disconnects, starts;
static uint32_t start_result;
static uint8_t owned_buffer[32];
static bool flash_owns_buffer;
#define IS_CONNECTED() (m_conn_handle != BLE_CONN_HANDLE_INVALID)
static uint32_t uint32_decode(uint8_t const *data) {
  return (uint32_t)data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16 | (uint32_t)data[3] << 24;
}
static void advertising_start(void) { ++advertising; m_is_advertising = true; }
static void restore_ble_connection_policy(void) { m_ble_data_policy_active = false; }
static void prioritize_flash_writes_over_ble(void) { m_ble_data_policy_active = false; }
static uint32_t dfu_start_pkt_handle(dfu_update_packet_t *packet) {
  assert(packet->packet_type == START_PACKET); ++starts; return start_result;
}
static ble_dfu_resp_val_t nrf_err_code_translate(uint32_t result, uint8_t procedure) {
  (void)procedure; return result;
}
static uint32_t ble_dfu_response_send(ble_dfu_t *dfu, unsigned procedure, unsigned result) {
  (void)dfu; (void)procedure; (void)result;
  assert(IS_CONNECTED()); ++responses; return NRF_SUCCESS;
}
static uint32_t sd_ble_gap_disconnect(uint16_t conn, unsigned reason) {
  assert(conn == m_conn_handle && reason == BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
  ++disconnects; return NRF_SUCCESS;
}
static uint32_t hci_mem_pool_rx_consume(uint8_t *data) {
  assert(data == owned_buffer && flash_owns_buffer);
  for (unsigned i = 0; i != sizeof(owned_buffer); ++i) assert(owned_buffer[i] == (uint8_t)(i ^ 0xA5));
  flash_owns_buffer = false; ++consumed; return NRF_SUCCESS;
}
static __attribute__((unused)) void bootloader_dfu_restart(void) {
  assert(m_conn_handle == BLE_CONN_HANDLE_INVALID);
  assert(m_tear_down_in_progress);
  ++resets;
}
'''
        harness += function(source, "static void start_data_process(") + "\n"
        harness += function(source, "static void dfu_cb_handler(") + "\n"
        harness += "static void disconnected(void) { switch (BLE_GAP_EVT_DISCONNECTED) {\n"
        harness += disconnect + "}}\n"
        harness += r'''
static void reset_case(void) {
  m_conn_handle = 42; m_reported_image_size = 0; m_update_mode = 4;
  m_tear_down_in_progress = false; m_is_advertising = false;
  m_ble_data_policy_active = m_service_change_pending = m_service_attrs_initialized = true;
  m_accum_len = 3; m_accum_active = true;
  m_num_of_firmware_bytes_rcvd = 256;
  advertising = resets = responses = consumed = disconnects = starts = 0;
  start_result = NRF_SUCCESS;
  for (unsigned i = 0; i != sizeof(owned_buffer); ++i) owned_buffer[i] = i ^ 0xA5;
  mp_final_packet = owned_buffer; flash_owns_buffer = true;
}
static void start_packet(unsigned length, uint32_t result) {
  uint8_t sizes[16] = {0}; sizes[9] = 2; /* 512-byte application. */
  ble_dfu_evt_t event = {.evt.ble_dfu_pkt_write = {.len = length, .p_data = sizes}};
  start_result = result; start_data_process(&m_dfu, &event);
}
int main(void) {
  /* A connection or a malformed/rejected START has no accepted upload to restart. */
  const unsigned malformed[] = {0, 4, 11, 13};
  for (unsigned i = 0; i != sizeof(malformed) / sizeof(malformed[0]); ++i) {
    reset_case(); start_packet(malformed[i], NRF_SUCCESS);
    assert(starts == 0 && m_reported_image_size == 0 && responses == 1);
    disconnected(); assert(resets == 0 && advertising == 1);
  }
  reset_case(); start_packet(12, NRF_ERROR_INVALID_STATE);
  assert(starts == 1 && m_reported_image_size == 0 && responses == 1);
  disconnected(); assert(resets == 0 && advertising == 1);

  reset_case(); start_packet(12, NRF_SUCCESS);
  assert(starts == 1 && m_reported_image_size == 512 && responses == 0);
  disconnected();
  assert(m_conn_handle == BLE_CONN_HANDLE_INVALID && mp_final_packet == NULL);
  assert(!m_accum_active && m_accum_len == 0);
  assert(!m_ble_data_policy_active && !m_service_change_pending && !m_service_attrs_initialized);
  assert(flash_owns_buffer && consumed == 0 && m_num_of_firmware_bytes_rcvd == 256);
#ifdef SECURE_DFU_TEST
  assert(resets == 0 && advertising == 1 && !m_tear_down_in_progress);
#else
  assert(resets == 1 && advertising == 0 && m_tear_down_in_progress);
#endif
  /* Old flash completions still release their exact owned packet, without sending to a stale peer. */
  dfu_cb_handler(START_PACKET, NRF_SUCCESS, NULL);
#ifdef SIGNED_FW
  dfu_cb_handler(INIT_PACKET, NRF_SUCCESS, NULL);
#endif
  assert(responses == 0 && flash_owns_buffer && consumed == 0);
  dfu_cb_handler(DATA_PACKET, NRF_SUCCESS, owned_buffer);
  assert(consumed == 1 && !flash_owns_buffer && responses == 0);
  disconnected();
#ifndef SECURE_DFU_TEST
  assert(resets == 1 && advertising == 0);
#endif
  /* An intentional close/activation already owns its exit; disconnect must not replace it. */
  reset_case(); start_packet(12, NRF_SUCCESS); m_tear_down_in_progress = true;
  disconnected(); assert(resets == 0 && advertising == 0);
  dfu_cb_handler(DATA_PACKET, NRF_SUCCESS, owned_buffer);
  assert(consumed == 1 && responses == 0);
  /* A failed late DATA callback must never try to disconnect an invalid handle. */
  reset_case(); start_packet(12, NRF_SUCCESS); disconnected();
  dfu_cb_handler(DATA_PACKET, NRF_ERROR_INTERNAL, owned_buffer);
  assert(disconnects == 0 && consumed == 0 && flash_owns_buffer);
  return 0;
}
'''
        sdk = ROOT / "lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include"
        with tempfile.TemporaryDirectory(prefix="otafix-legacy-recovery-") as directory:
            for secure in (False, True):
                for signed in (False, True):
                    with self.subTest(secure=secure, signed=signed):
                        binary = Path(directory) / ("recovery.exe" if os.name == "nt" else "recovery")
                        flags = (["-DSECURE_DFU_TEST"] if secure else []) + (["-DSIGNED_FW"] if signed else [])
                        subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                                        "-Werror", *flags, "-I" + str(sdk), "-x", "c", "-", "-o", str(binary)],
                                       input=harness, text=True, check=True)
                        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
