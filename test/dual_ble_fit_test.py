#!/usr/bin/env python3
"""Compile the fit experiment's real dispatcher, advertising and glyph code."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = (ROOT / "lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c").read_text()


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                return source[start:end + 1] + "\n"
    raise AssertionError(signature)


def execute(code, *flags):
    with tempfile.TemporaryDirectory(prefix="otafix-dual-fit-") as tmp:
        binary = Path(tmp) / ("test.exe" if os.name == "nt" else "test")
        sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] \
            if os.environ.get("SECURE_DFU_TEST_SANITIZE") == "1" else []
        subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                        *sanitizers, *flags, "-I" + str(ROOT / "src"), "-x", "c", "-", "-o", str(binary)],
                       input=code, text=True, check=True)
        subprocess.run([str(binary)], check=True)


class DualFit(unittest.TestCase):
    def test_actual_dispatcher_latches_protocol_across_reconnect(self):
        code = r'''
#include <assert.h>
#include "dual_ble_dfu.h"
#define DUAL_BLE_DFU_TEST 1
#define SECURE_DFU_TEST 1
#define BLE_GATTS_EVT_WRITE 1
#define BLE_GATTS_EVT_RW_AUTHORIZE_REQUEST 4
#define BLE_GATTS_AUTHORIZE_TYPE_WRITE 1
#define BLE_GATT_STATUS_ATTERR_WRITE_NOT_PERMITTED 3
#define APP_ERROR_CHECK(error) assert((error) == 0)
typedef struct { struct { unsigned evt_id; } header;
  struct { struct { uint16_t conn_handle; struct {
    struct { uint16_t handle; } write;
    struct { uint8_t type; struct { struct { uint16_t handle; } write; } request; } authorize_request;
  } params; } gatts_evt; } evt;
} ble_evt_t;
typedef struct { uint8_t type; struct { struct { uint16_t gatt_status; } write; } params;
} ble_gatts_rw_authorize_reply_params_t;
static unsigned rejected;
static int sd_ble_gatts_rw_authorize_reply(uint16_t conn, ble_gatts_rw_authorize_reply_params_t *reply) {
  (void)conn;
  assert(reply->type == 1 && reply->params.write.gatt_status == 3);
  ++rejected; return 0;
}
typedef struct { struct { uint16_t value_handle; } dfu_ctrl_pt_handles, dfu_pkt_handles; } ble_dfu_t;
static ble_dfu_t m_dfu = {{10}, {11}}, m_secure_dfu = {{20}, {21}};
static uint8_t m_dual_owner;
static unsigned legacy_events, secure_events, common_events;
static void ble_dfu_on_ble_evt(ble_dfu_t *s, ble_evt_t *e) {
  (void)s; (void)e; ++legacy_events;
}
static void secure_dfu_ble_event(ble_dfu_t *s, ble_evt_t *e) {
  (void)s; (void)e; ++secure_events;
}
static void on_ble_evt(ble_evt_t *e) { (void)e; ++common_events; }
'''
        code += function(TRANSPORT, "static bool dual_ble_write_allowed(")
        code += function(TRANSPORT, "/*static*/ void ble_evt_dispatch(")
        code += r'''
static void send(unsigned type, uint16_t handle) {
  ble_evt_t event = {.header = {type}, .evt.gatts_evt.params.write.handle = handle};
  event.evt.gatts_evt.params.authorize_request.type = BLE_GATTS_AUTHORIZE_TYPE_WRITE;
  event.evt.gatts_evt.params.authorize_request.request.write.handle = handle;
  ble_evt_dispatch(&event);
}
int main(void) {
  for (unsigned first = DUAL_DFU_LEGACY; first <= DUAL_DFU_SECURE; ++first) {
    m_dual_owner = 0;
    send(1, 30); /* CCCD/discovery must not claim flash ownership. */
    assert(m_dual_owner == 0);
    send(first == DUAL_DFU_LEGACY ? 4 : 1, first == DUAL_DFU_LEGACY ? 10 : 20);
    assert(m_dual_owner == first);
    send(2, 0); /* Disconnect. */
    send(3, 0); /* Reconnect: ownership survives. */
    assert(m_dual_owner == first);
    unsigned saved_legacy = legacy_events, saved_secure = secure_events;
    unsigned saved_common = common_events;
    unsigned saved_rejected = rejected;
    send(first == DUAL_DFU_LEGACY ? 1 : 4, first == DUAL_DFU_LEGACY ? 20 : 10);
    send(1, first == DUAL_DFU_LEGACY ? 21 : 11);
    assert(legacy_events == saved_legacy && secure_events == saved_secure);
    assert(common_events == saved_common + 2);
    assert(rejected == saved_rejected + (first == DUAL_DFU_SECURE));
    send(1, first == DUAL_DFU_LEGACY ? 11 : 21);
    assert(legacy_events == saved_legacy + 1 && secure_events == saved_secure + 1);
  }
  return 0;
}
'''
        execute(code)

    def test_advertisement_preserves_both_services_within_31_bytes(self):
        code = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#define DUAL_BLE_DFU_TEST 1
#define SECURE_DFU_TEST 1
#define BLE_GAP_ADV_SET_DATA_SIZE_MAX 31
#define BLE_GAP_AD_TYPE_FLAGS 1
#define BLE_GAP_AD_TYPE_16BIT_SERVICE_UUID_COMPLETE 3
#define BLE_GAP_AD_TYPE_128BIT_SERVICE_UUID_MORE_AVAILABLE 6
#define BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME 9
#define BLE_GAP_AD_TYPE_SHORT_LOCAL_NAME 8
#define BLE_DFU_SERVICE_UUID 0x1530
#define DEVICE_NAME "TOWER_V2_OTA"
typedef struct { uint8_t *p_data; uint16_t len; } ble_data_t;
typedef struct { uint16_t uuid; uint8_t type; } ble_uuid_t;
static struct { uint8_t uuid_type; } m_dfu;
static void sd_ble_uuid_encode(ble_uuid_t *uuid, uint8_t *length, uint8_t *out) {
  assert(uuid->uuid == BLE_DFU_SERVICE_UUID);
  *length = 16; memset(out, 0x55, 16);
}
'''
        code += function(TRANSPORT, "static void advertising_add(")
        code += function(TRANSPORT, "static void advertising_init(")
        code += r'''
int main(void) {
  uint8_t guarded[33] = {0}; guarded[31] = 0xaa; guarded[32] = 0xbb;
  ble_data_t data = {guarded, 0};
  advertising_init(&data, 6);
  assert(data.len <= 31 && guarded[31] == 0xaa && guarded[32] == 0xbb);
  unsigned legacy = 0, secure = 0, name = 0;
  for (unsigned i = 0; i < data.len; i += guarded[i] + 1) {
    assert(guarded[i] && i + guarded[i] < data.len);
    if (guarded[i + 1] == 6) { assert(guarded[i] == 17); ++legacy; }
    if (guarded[i + 1] == 3) {
      assert(guarded[i] == 3 && guarded[i + 2] == 0x59 && guarded[i + 3] == 0xfe); ++secure;
    }
    if (guarded[i + 1] == 8) ++name;
  }
  assert(legacy == 1 && secure == 1 && name == 1);
  return 0;
}
'''
        execute(code)

    def test_block_display_bounds_on_both_controllers(self):
        draw = function((ROOT / "src/screen.c").read_text(),
                        "__attribute__((noinline, noclone)) static void draw_dfu(")
        code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#define DUAL_BLE_DFU_TEST 1
static unsigned lines, white;
static void board_display_draw_line(int x, const uint8_t *bytes, size_t size) {
  assert(x == (int)lines++ && size == DISPLAY_HEIGHT * 2);
  const uint16_t *pixels = (const uint16_t *)bytes;
  const uint8_t glyph[3][5] = {{0x7f, 0x41, 0x41, 0x22, 0x1c},
    {0x7f, 0x09, 0x09, 0x09, 0x01}, {0x3f, 0x40, 0x40, 0x40, 0x3f}};
  const int scale = DISPLAY_WIDTH / 23;
  const int left = (DISPLAY_WIDTH - 17 * scale) / 2;
  const int top = (DISPLAY_HEIGHT - 7 * scale) / 2;
  for (unsigned y = 0; y < DISPLAY_HEIGHT; ++y) {
    bool expected = false;
    for (unsigned letter = 0; letter < 3; ++letter) {
      int column = x - left - (int)letter * 6 * scale;
      if (column >= 0 && column < 5 * scale && (int)y >= top && (int)y < top + 7 * scale) {
        expected = (glyph[letter][column / scale] & (1u << ((y - top) / scale))) != 0;
      }
    }
    assert(pixels[y] == (expected ? 0xffff : 0));
    white += pixels[y] != 0;
  }
}
'''
        code += draw + r'''
int main(void) {
  draw_dfu(false); assert(lines == DISPLAY_WIDTH && white > 0);
  unsigned previous = white; lines = white = 0;
  draw_dfu(true); assert(lines == DISPLAY_WIDTH && white == previous);
  return 0;
}
'''
        for width, height in ((160, 80), (240, 135)):
            execute(code, f"-DDISPLAY_WIDTH={width}", f"-DDISPLAY_HEIGHT={height}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
