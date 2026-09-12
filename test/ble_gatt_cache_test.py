#!/usr/bin/env python3
"""Guard bonded application-to-bootloader GATT cache invalidation."""

import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    raise AssertionError(f"unterminated function: {signature}")


source = SOURCE.read_text(encoding="utf-8")
service_change = function_body(source, "static void service_change_try(void)")

# Reproduce the Android failure without hardware. S140 exposes user attributes
# at 0x000E..0x001C in this bootloader. The legacy code requested 0x000C..0xFFFF,
# so the SoftDevice rejected it; treating that error as success left the phone
# reading an application-era DFU handle that does not exist after the reset.
FIRST_USER_HANDLE = 0x000E
LAST_BOOTLOADER_HANDLE = 0x001C
STALE_APPLICATION_DFU_VERSION_HANDLE = LAST_BOOTLOADER_HANDLE + 1


def fake_service_changed(start: int, end: int) -> str:
    if not (
        FIRST_USER_HANDLE <= start <= end <= LAST_BOOTLOADER_HANDLE
    ):
        return "invalid attribute handle"
    return "success"


legacy_result = fake_service_changed(0x000C, 0xFFFF)
require(
    legacy_result == "invalid attribute handle",
    "synthetic fixture must reproduce the rejected legacy range",
)
legacy_discarded_error = legacy_result in {
    "invalid attribute handle",
    "invalid state",
    "busy",
}
require(
    legacy_discarded_error
    and STALE_APPLICATION_DFU_VERSION_HANDLE > LAST_BOOTLOADER_HANDLE,
    "legacy behavior must expose the stale-read GATT INVALID HANDLE failure",
)
require(
    fake_service_changed(FIRST_USER_HANDLE, LAST_BOOTLOADER_HANDLE) == "success",
    "runtime user-service bounds must be accepted by the synthetic SoftDevice",
)

# A temporary ATT-state failure must not consume the one cache-invalidation
# opportunity. This mirrors service_change_try(): pending clears only on success.
pending = True
for result in ("invalid state", "busy", "success"):
    if result == "success":
        pending = False
require(not pending, "a later successful retry must clear pending state")

require(
    "!m_service_change_pending" in service_change,
    "cache invalidation retries must be gated by pending state",
)
require(
    service_change.count("sd_ble_gatts_sys_attr_set(") == 2,
    "bonded system and user attributes must be restored before indicating",
)
require(
    "if (!m_service_attrs_initialized)" in service_change
    and "m_service_attrs_initialized = true;" in service_change,
    "indication retries must not reinitialize the peer's DFU CCCDs",
)
require(
    "sd_ble_gatts_service_changed(m_conn_handle," in service_change
    and "m_dfu.service_handle," in service_change
    and "m_dfu.dfu_rev_handles.value_handle + 7U);" in service_change,
    "Service Changed must use the runtime-populated user-service range",
)
require(
    "BLE_HANDLE_MAX" not in source,
    "an unpopulated end handle makes the SoftDevice reject Service Changed",
)
success = service_change.index("if (err_code == NRF_SUCCESS)")
clear = service_change.index("m_service_change_pending = false;")
require(
    success < clear,
    "only a successfully queued Service Changed indication may clear pending state",
)
require(
    "APP_ERROR_CHECK" not in service_change and "VERIFY_SUCCESS" not in service_change,
    "transient cache-invalidation failures must not reset the bootloader",
)

on_ble_evt = function_body(source, "static void on_ble_evt(")
connected_at = on_ble_evt.index("case BLE_GAP_EVT_CONNECTED:")
disconnected_at = on_ble_evt.index("case BLE_GAP_EVT_DISCONNECTED:")
connected = on_ble_evt[connected_at:disconnected_at]
require(
    "m_service_change_pending = m_ble_peer_data_valid;" in connected,
    "each bonded reconnect must arm cache invalidation",
)
require(
    "m_service_attrs_initialized = false;" in connected
    and connected.index("m_service_attrs_initialized = false;") < connected.index("service_change_try();"),
    "each connection must initialize its own system attributes before indicating",
)
require(
    "sd_ble_gap_data_length_update" not in connected,
    "CONNECTED must not start an optional procedure before cache invalidation",
)

conn_update_at = on_ble_evt.index("case BLE_GAP_EVT_CONN_PARAM_UPDATE:")
disconnected = on_ble_evt[disconnected_at:conn_update_at]
require(
    "m_service_change_pending = false;" in disconnected,
    "pending state must not survive a disconnected handle",
)
require(
    "m_service_attrs_initialized = false;" in disconnected,
    "attribute initialization state must not survive a disconnected handle",
)
require(
    "sd_ble_gatts_sys_attr_get" not in disconnected,
    "disconnect must not reset on an unused system-attribute readback",
)

require(
    "m_service_change_pending = m_ble_peer_data_valid;" in connected
    and "service_change_try();" in connected,
    "a bonded connection must attempt cache invalidation immediately",
)
retry_start = on_ble_evt.index("case BLE_GAP_EVT_CONN_SEC_UPDATE:")
retry_end = on_ble_evt.index("case BLE_GAP_EVT_DATA_LENGTH_UPDATE_REQUEST:")
retry_events = on_ble_evt[retry_start:retry_end]
require(
    "case BLE_GAP_EVT_CONN_SEC_UPDATE:" in retry_events
    and retry_events.count("service_change_try();") == 1,
    "encryption completion must retry pending cache invalidation",
)
require(
    on_ble_evt.count("service_change_try();") == 4,
    "cache invalidation must run only at connect, system-attribute, "
    "procedure-completion, and MTU-unblock points",
)

# Execute the actual shared helper and link-event cases, not just a Python
# model. Simulate SoftDevice's NULL user-attribute reset clearing DFU CCCDs.
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "nrf_error.h"
#define BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS 1
#define BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS 2
#define BLE_GAP_EVT_CONNECTED 1
#define BLE_GAP_EVT_DISCONNECTED 2
#define BLE_CONN_HANDLE_INVALID 0xffff
#define APP_DIRECTED_ADV_TIMEOUT 3
static bool m_service_change_pending, m_service_attrs_initialized;
static bool m_ble_peer_data_valid, m_is_advertising, m_ble_data_policy_active;
static bool m_tear_down_in_progress, m_accum_active;
static uint16_t m_conn_handle, m_accum_len;
static unsigned m_direct_adv_cnt;
static void *mp_final_packet;
static struct { uint8_t sys_serv_attr[8]; } m_ble_peer_data;
static struct { uint16_t service_handle; struct { uint16_t value_handle; } dfu_rev_handles; } m_dfu;
static bool dfu_cccd;
static unsigned sys_calls, usr_calls, indication_calls, attr_fail_flag;
static uint32_t indication_result;
static void advertising_start(void) { m_is_advertising = true; }
static uint32_t sd_ble_gatts_sys_attr_set(uint16_t conn, const uint8_t *data, uint16_t len, uint32_t flags) {
    (void)conn; (void)len;
    if (flags == BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS) ++sys_calls;
    else { assert(data == NULL); ++usr_calls; }
    if (flags == attr_fail_flag) return NRF_ERROR_BUSY;
    if (flags == BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS) dfu_cccd = false;
    return NRF_SUCCESS;
}
static uint32_t sd_ble_gatts_service_changed(uint16_t conn, uint16_t first, uint16_t last) {
    (void)conn; (void)first; (void)last;
    assert(m_service_attrs_initialized);
    ++indication_calls;
    return indication_result;
}
static void service_change_try(void)
'''
link_wrapper = r'''
static void link_event(unsigned type) {
    struct { struct { struct { uint16_t conn_handle; } gap_evt; } evt; } event = {{{42}}};
    const __typeof__(event) *p_ble_evt = &event;
    switch (type) {
'''
main = r'''
int main(void) {
    m_ble_peer_data_valid = true;
    indication_result = NRF_ERROR_BUSY;
    link_event(BLE_GAP_EVT_CONNECTED);
    assert(m_service_attrs_initialized && m_service_change_pending);
    assert(sys_calls == 1 && usr_calls == 1 && indication_calls == 1);
    dfu_cccd = true; /* Peer subscribes between the initial attempt and retry. */
    for (unsigned i = 0; i < 4; ++i) service_change_try();
    assert(dfu_cccd && sys_calls == 1 && usr_calls == 1 && m_service_change_pending);
    indication_result = NRF_SUCCESS;
    service_change_try();
    assert(dfu_cccd && !m_service_change_pending && indication_calls == 6);
    service_change_try();
    assert(indication_calls == 6);

    link_event(BLE_GAP_EVT_DISCONNECTED);
    assert(!m_service_attrs_initialized && !m_service_change_pending);
    link_event(BLE_GAP_EVT_CONNECTED);
    assert(m_service_attrs_initialized && !dfu_cccd && sys_calls == 2 && usr_calls == 2);

    /* Failure in either initialization step must not mark setup complete or
       indicate prematurely. Retry setup until both calls succeed. */
    for (unsigned failed_flag = 1; failed_flag <= 2; ++failed_flag) {
        link_event(BLE_GAP_EVT_DISCONNECTED);
        sys_calls = usr_calls = indication_calls = 0;
        attr_fail_flag = failed_flag;
        link_event(BLE_GAP_EVT_CONNECTED);
        assert(!m_service_attrs_initialized && m_service_change_pending && indication_calls == 0);
        assert(sys_calls == 1 && usr_calls == (failed_flag == 2));
        attr_fail_flag = 0;
        indication_result = NRF_ERROR_INVALID_STATE;
        service_change_try();
        assert(m_service_attrs_initialized && m_service_change_pending && indication_calls == 1);
        const unsigned saved_sys = sys_calls, saved_usr = usr_calls;
        dfu_cccd = true;
        service_change_try();
        assert(dfu_cccd && sys_calls == saved_sys && usr_calls == saved_usr);
    }

    link_event(BLE_GAP_EVT_DISCONNECTED);
    unsigned saved_calls = indication_calls;
    service_change_try();
    assert(indication_calls == saved_calls);
    m_ble_peer_data_valid = false;
    link_event(BLE_GAP_EVT_CONNECTED);
    assert(!m_service_change_pending && !m_service_attrs_initialized && indication_calls == saved_calls);
    return 0;
}
'''
code = prefix + service_change + link_wrapper + connected + disconnected + "\n}}\n" + main
sdk = ROOT / "lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include"
with tempfile.TemporaryDirectory(prefix="otafix-gatt-cache-") as directory:
    for secure in (False, True):
        binary = Path(directory) / ("cache.exe" if os.name == "nt" else "cache")
        flags = ["-DSECURE_DFU_TEST"] if secure else []
        if os.environ.get("SECURE_DFU_TEST_SANITIZE") == "1":
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-O1", "-g"]
        subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                        *flags, "-I" + str(sdk), "-x", "c", "-", "-o", str(binary)],
                       input=code, text=True, check=True)
        subprocess.run([str(binary)], check=True)

print("BLE GATT cache guards and compiled Legacy/Secure retry tests passed: DFU subscriptions survive retries")
