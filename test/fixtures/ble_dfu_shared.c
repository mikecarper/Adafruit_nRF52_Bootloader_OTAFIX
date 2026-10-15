#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ble_dfu.h"
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define VERIFY_SUCCESS(code) do { if ((code) != NRF_SUCCESS) return (code); } while (0)

@PRODUCTION@

static ble_dfu_t *active_dfu;
static ble_dfu_init_t *active_init;
static unsigned uuid_calls, service_calls, char_calls, hvx_calls;
static int fail_at;
static unsigned resources;
static uint32_t final_result;
static uint8_t expected_packet[7];
static uint16_t expected_length;
static bool control_trace, cccd_enabled;
static uint32_t cccd_result, authorize_result;
static unsigned control_events, authorize_calls, error_calls;
static ble_dfu_evt_type_t event_type;
static uint16_t event_count;
static uint8_t event_param_len;
static uint8_t *event_param_data;
static ble_gatts_evt_write_t *active_write;
static char trace[16];
static unsigned trace_count;

static void trace_event(char letter) { if (control_trace) trace[trace_count++] = letter; }
static void event_handler(ble_dfu_t *dfu, ble_dfu_evt_t *evt) {
  assert(dfu == active_dfu);
  trace_event('E'); control_events++;
  event_type = evt->ble_dfu_evt_type;
  if (event_type == BLE_DFU_START || event_type == BLE_DFU_RECEIVE_INIT_DATA) {
    event_param_len = evt->evt.ble_dfu_pkt_write.len;
    event_param_data = evt->evt.ble_dfu_pkt_write.p_data;
  }
  if (event_type == BLE_DFU_PKT_RCPT_NOTIF_ENABLED || event_type == BLE_DFU_PKT_RCPT_NOTIF_DISABLED)
    event_count = evt->evt.pkt_rcpt_notif_req.num_of_pkts;
}
static void error_handler(uint32_t value) { assert(value == cccd_result); error_calls++; trace_event('R'); }

uint32_t sd_ble_gatts_value_get(uint16_t conn, uint16_t handle, ble_gatts_value_t *value) {
  assert(conn == active_dfu->conn_handle && handle == active_dfu->dfu_ctrl_pt_handles.cccd_handle);
  assert(value->len == 2 && value->offset == 0);
  trace_event('G');
  if (cccd_result != NRF_SUCCESS) return cccd_result;
  value->p_value[0] = cccd_enabled; value->p_value[1] = 0;
  return NRF_SUCCESS;
}

uint32_t sd_ble_gatts_rw_authorize_reply(uint16_t conn, ble_gatts_rw_authorize_reply_params_t const *reply) {
  assert(conn == active_dfu->conn_handle && active_write);
  assert(reply->type == BLE_GATTS_AUTHORIZE_TYPE_WRITE && reply->params.write.update == 1);
  assert(reply->params.write.offset == active_write->offset && reply->params.write.len == active_write->len);
  assert(reply->params.write.p_data == active_write->data);
  assert(reply->params.write.gatt_status == (cccd_enabled && cccd_result == NRF_SUCCESS
    ? BLE_GATT_STATUS_SUCCESS : BLE_GATT_STATUS_ATTERR_CPS_CCCD_CONFIG_ERROR));
  authorize_calls++; trace_event('A');
  return authorize_result;
}

uint32_t sd_ble_uuid_vs_add(ble_uuid128_t const *uuid, uint8_t *type) {
  const uint8_t expected[16] = {0x23,0xd1,0xbc,0xea,0x5f,0x78,0x23,0x15,
                               0xde,0xef,0x12,0x12,0,0,0,0};
  assert(memcmp(uuid->uuid128, expected, sizeof(expected)) == 0);
  uuid_calls++;
  if (fail_at == -2) return 0x72;
  *type = 0x42;
  return NRF_SUCCESS;
}

uint32_t sd_ble_gatts_service_add(uint8_t type, ble_uuid_t const *uuid, uint16_t *handle) {
  assert(type == BLE_GATTS_SRVC_TYPE_PRIMARY && uuid->type == 0x42 && uuid->uuid == BLE_DFU_SERVICE_UUID);
  service_calls++;
  if (fail_at == -1) return 0x73;
  *handle = 77;
  return NRF_SUCCESS;
}

uint32_t sd_ble_gatts_characteristic_add(uint16_t service, ble_gatts_char_md_t const *md,
                                       ble_gatts_attr_t const *attr,
                                       ble_gatts_char_handles_t *handles) {
  char_calls++;
  assert(service == 77 && char_calls <= 3);
  const bool packet = char_calls == 1;
  const bool control = char_calls == 2;
  const bool revision = char_calls == 3;
  const uint16_t uuid = packet ? BLE_DFU_PKT_CHAR_UUID : control ? BLE_DFU_CTRL_PT_UUID : BLE_DFU_REV_CHAR_UUID;
  ble_gatts_char_md_t expected_md;
  memset(&expected_md, 0, sizeof(expected_md));
  expected_md.char_props.read = revision;
  expected_md.char_props.write = packet || control;
  expected_md.char_props.write_wo_resp = packet;
  expected_md.char_props.notify = control;
  // Includes extended properties, all optional descriptor pointers and zero padding.
  assert(memcmp(md, &expected_md, sizeof(expected_md)) == 0);
  assert(attr->p_uuid->uuid == uuid && attr->p_uuid->type == 0x42);
  ble_gatts_attr_md_t expected_attr;
  memset(&expected_attr, 0, sizeof(expected_attr));
  if (revision) BLE_GAP_CONN_SEC_MODE_SET_OPEN(&expected_attr.read_perm);
  else BLE_GAP_CONN_SEC_MODE_SET_OPEN(&expected_attr.write_perm);
  expected_attr.vloc = BLE_GATTS_VLOC_STACK;
  expected_attr.wr_auth = control;
  expected_attr.vlen = 1;
  assert(memcmp(attr->p_attr_md, &expected_attr, sizeof(expected_attr)) == 0);
  assert(attr->init_len == (revision ? 2 : 0) && attr->init_offs == 0);
  assert(attr->max_len == (packet ? 244 : control ? BLE_GATT_ATT_MTU_DEFAULT : 2));
  assert(attr->p_value == (revision ? (uint8_t *)&active_init->revision : NULL));
  if (revision) assert(memcmp(attr->p_value, &active_init->revision, 2) == 0);
  assert(handles == (packet ? &active_dfu->dfu_pkt_handles :
                      control ? &active_dfu->dfu_ctrl_pt_handles : &active_dfu->dfu_rev_handles));
  if (fail_at == (int)char_calls) return 0x80 + char_calls;
  memset(handles, 0, sizeof(*handles));
  handles->value_handle = 100 + char_calls;
  handles->cccd_handle = control ? 202 : 0;
  return NRF_SUCCESS;
}

uint32_t sd_ble_gatts_hvx(uint16_t conn, ble_gatts_hvx_params_t const *params) {
  hvx_calls++;
  trace_event('H');
  assert(conn == active_dfu->conn_handle && params->handle == active_dfu->dfu_ctrl_pt_handles.value_handle);
  assert(params->type == BLE_GATT_HVX_NOTIFICATION && params->offset == 0);
  assert(params->p_data == m_notif_buffer && *params->p_len == expected_length);
  assert(memcmp(params->p_data, expected_packet, expected_length) == 0);
  if (resources) {
    resources--;
    // The real SVC owns the in/out length. Corrupt both after checking to
    // prove each retry reconstructs the identical original packet and length.
    *params->p_len = 1;
    memset(m_notif_buffer, 0xa5, sizeof(m_notif_buffer));
    return NRF_ERROR_RESOURCES;
  }
  return final_result;
}

static void reset(ble_dfu_t *dfu, ble_dfu_init_t *init) {
  memset(dfu, 0, sizeof(*dfu));
  *init = (ble_dfu_init_t){.revision = 0x1234, .evt_handler = event_handler, .error_handler = error_handler};
  active_dfu = dfu; active_init = init;
  uuid_calls = service_calls = char_calls = hvx_calls = resources = 0;
  final_result = NRF_SUCCESS; fail_at = 0;
  m_is_dfu_service_initialized = false;
  memset(m_notif_buffer, 0x5a, sizeof(m_notif_buffer));
  control_trace = false; cccd_enabled = true; cccd_result = authorize_result = NRF_SUCCESS;
  control_events = authorize_calls = error_calls = trace_count = 0;
  memset(trace, 0, sizeof(trace)); active_write = NULL;
}

static void expect(uint8_t kind, uint32_t count, uint8_t procedure, uint8_t response) {
  expected_packet[0] = kind == 1 ? 17 : 16;
  expected_packet[1] = procedure;
  expected_packet[2] = response;
  expected_length = kind == 1 ? 5 : kind == 2 ? 7 : 3;
  if (kind) for (unsigned i = 0; i < 4; i++) expected_packet[expected_length - 4 + i] = count >> (8 * i);
}

static uint32_t send(unsigned kind, ble_dfu_t *dfu, uint32_t count,
                     ble_dfu_procedure_t proc, ble_dfu_resp_val_t result) {
  if (kind == 1) return ble_dfu_pkts_rcpt_notify(dfu, count);
  if (kind == 2) return ble_dfu_bytes_rcvd_report(dfu, count);
  return ble_dfu_response_send(dfu, proc, result);
}

int main(int argc, char **argv) {
  assert(argc == 2);
  const int scenario = atoi(argv[1]);
  ble_dfu_t dfu;
  ble_dfu_init_t init;
  reset(&dfu, &init);
  if (scenario == 0) {
    assert(ble_dfu_init(&dfu, &init) == NRF_SUCCESS);
    assert(uuid_calls == 1 && service_calls == 1 && char_calls == 3);
    assert(dfu.dfu_pkt_handles.value_handle == 101 && dfu.dfu_ctrl_pt_handles.value_handle == 102);
    assert(dfu.dfu_rev_handles.value_handle == 103 && dfu.dfu_ctrl_pt_handles.cccd_handle == 202);
    assert(dfu.evt_handler == event_handler && dfu.error_handler == error_handler);
    assert(dfu.conn_handle == BLE_CONN_HANDLE_INVALID && m_is_dfu_service_initialized);
    // A NULL optional error handler leaves an existing handler untouched.
    reset(&dfu, &init); dfu.error_handler = error_handler; init.error_handler = NULL;
    assert(ble_dfu_init(&dfu, &init) == NRF_SUCCESS && dfu.error_handler == error_handler);
  } else if (scenario == 1) {
    dfu.conn_handle = 25;
    assert(ble_dfu_init(NULL, &init) == NRF_ERROR_NULL);
    assert(ble_dfu_init(&dfu, NULL) == NRF_ERROR_NULL);
    init.evt_handler = NULL;
    assert(ble_dfu_init(&dfu, &init) == NRF_ERROR_NULL);
    assert(uuid_calls == 0 && service_calls == 0 && char_calls == 0 && dfu.conn_handle == 25);
    for (int failure = -2; failure <= 3; failure++) {
      if (!failure) continue;
      reset(&dfu, &init); fail_at = failure;
      assert(ble_dfu_init(&dfu, &init) == (uint32_t)(failure == -2 ? 0x72 : failure == -1 ? 0x73 : 0x80 + failure));
      assert(char_calls == (failure < 0 ? 0u : (unsigned)failure) && !m_is_dfu_service_initialized);
    }
  } else if (scenario >= 2 && scenario <= 4) {
    m_is_dfu_service_initialized = true;
    dfu.conn_handle = 17; dfu.dfu_ctrl_pt_handles.value_handle = 99;
    for (unsigned kind = 0; kind < 3; kind++) {
      for (unsigned iteration = 0; iteration < 6; iteration++) {
        const uint32_t count = iteration == 0 ? 0 : iteration == 1 ? UINT32_MAX : 0x12345678;
        const ble_dfu_procedure_t proc = (ble_dfu_procedure_t)(iteration == 4 ? 0x1234 : iteration == 5 ? -1 : 3);
        const ble_dfu_resp_val_t result = (ble_dfu_resp_val_t)(iteration == 4 ? 0x2345 : iteration == 5 ? -1 : 1);
        expect(kind, count, kind == 2 ? 7 : (uint8_t)proc, kind == 2 ? 1 : (uint8_t)result);
        if (scenario == 4) {
          hvx_calls = 0;
          uint8_t saved[sizeof(m_notif_buffer)]; memcpy(saved, m_notif_buffer, sizeof(saved));
          assert(send(kind, NULL, count, proc, result) == NRF_ERROR_NULL);
          m_is_dfu_service_initialized = false;
          assert(send(kind, &dfu, count, proc, result) == NRF_ERROR_INVALID_STATE);
          m_is_dfu_service_initialized = true; dfu.conn_handle = BLE_CONN_HANDLE_INVALID;
          assert(send(kind, &dfu, count, proc, result) == NRF_ERROR_INVALID_STATE);
          dfu.conn_handle = 17;
          assert(hvx_calls == 0 && memcmp(m_notif_buffer, saved, sizeof(saved)) == 0);
        } else {
          hvx_calls = 0; resources = scenario == 3 ? 2 : 0;
          final_result = iteration % 2 ? NRF_SUCCESS : 0x90;
          assert(send(kind, &dfu, count, proc, result) == final_result);
          assert(hvx_calls == (scenario == 3 ? 3u : 1u));
        }
      }
    }
  } else if (scenario == 5 || scenario == 6) {
    active_write = calloc(1, sizeof(*active_write) + 8);
    assert(active_write);
    control_trace = true;
    m_is_dfu_service_initialized = true;
    dfu.conn_handle = 17;
    dfu.dfu_ctrl_pt_handles.value_handle = 99;
    dfu.dfu_ctrl_pt_handles.cccd_handle = 100;
    dfu.evt_handler = event_handler; dfu.error_handler = error_handler;
    for (unsigned opcode = 0; opcode <= 255; opcode++) {
      for (unsigned len = 0; len <= 4; len++) {
        for (unsigned variant = 0; variant < (scenario == 5 ? 2u : 4u); variant++) {
          active_write->len = len; active_write->offset = 5;
          active_write->data[0] = opcode;
          active_write->data[1] = variant == 0 ? 0 : 0x34;
          active_write->data[2] = variant == 0 ? 0 : 0x12;
          cccd_enabled = scenario == 5 || variant >= 2;
          cccd_result = scenario == 6 && variant == 1 ? 0x57 : NRF_SUCCESS;
          authorize_result = scenario == 6 && variant >= 2 ? 0x58 : NRF_SUCCESS;
          control_events = authorize_calls = error_calls = hvx_calls = trace_count = 0;
          memset(trace, 0, sizeof(trace));
          event_param_data = NULL; event_param_len = 0; event_count = 0;
          if (opcode <= 2 && opcode != 0 && len < 2) expect(0, 0, opcode, BLE_DFU_RESP_VAL_OPER_FAILED);
          else expect(0, 0, opcode, BLE_DFU_RESP_VAL_NOT_SUPPORTED);
          assert(on_ctrl_pt_write(&dfu, active_write) == authorize_result);
          assert(authorize_calls == 1);
          if (scenario == 6) {
            assert(control_events == 0 && hvx_calls == 0);
            assert(strcmp(trace, variant == 1 ? "GRA" : "GA") == 0);
            assert(error_calls == (variant == 1 ? 1u : 0u));
          } else {
            const bool dispatch = (opcode >= 1 && opcode <= 8 &&
                !((opcode <= 2 && len < 2) || (opcode == 8 && len < 3)));
            assert(control_events == (dispatch ? 1u : 0u) && hvx_calls == (dispatch ? 0u : 1u));
            assert(strcmp(trace, dispatch ? "GAE" : "GAH") == 0);
            if (dispatch) {
              const ble_dfu_evt_type_t expected = opcode <= 6 ? (ble_dfu_evt_type_t)(opcode - 1) :
                opcode == 7 ? BLE_DFU_BYTES_RECEIVED_SEND : variant == 0 ?
                BLE_DFU_PKT_RCPT_NOTIF_DISABLED : BLE_DFU_PKT_RCPT_NOTIF_ENABLED;
              assert(event_type == expected);
              if (opcode <= 2) assert(event_param_len == 1 && event_param_data == &active_write->data[1]);
              if (opcode == 8) assert(event_count == (variant == 0 ? 0 : 0x1234));
            }
          }
        }
      }
    }
    free(active_write);
  } else abort();
  return 0;
}
