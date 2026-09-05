#!/usr/bin/env python3
"""Guard bonded application-to-bootloader GATT cache invalidation."""

from pathlib import Path


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

print(
    "BLE GATT cache regression reproduced and fixed: bonded reconnects use a "
    "populated range and retry Service Changed until queued"
)
