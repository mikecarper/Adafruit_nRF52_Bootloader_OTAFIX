#!/usr/bin/env python3
"""Guard BLE DFU phase latency without reviving fatal GAP update races."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


source = SOURCE.read_text(encoding="utf-8")

local_start = source.index("static void set_local_connection_latency")
slave_start = source.index("static void set_slave_latency_disabled", local_start)
fast_start = source.index("static void prioritize_ble_over_flash_writes(void)", slave_start)
restore_start = source.index("static void restore_ble_connection_policy(void)", fast_start)
flash_start = source.index("static void prioritize_flash_writes_over_ble(void)", restore_start)
fast = source[fast_start:restore_start]
restore = source[restore_start:flash_start]
flash = source[flash_start:source.index("#else", flash_start)]
require(
    "set_local_connection_latency(0);" in fast,
    "DATA phase must clear the bootloader's added local latency",
)
require(
    "set_slave_latency_disabled(true);" in fast,
    "DATA phase must disable inherited slave latency locally",
)
require(
    "m_ble_data_policy_active = true;" in fast,
    "DATA phase must become explicit only after applying its options",
)
require(
    "set_local_connection_latency(0);" in restore
    and "set_slave_latency_disabled(false);" in restore
    and "m_ble_data_policy_active = false;" in restore,
    "leaving DATA must restore both latency options and phase state",
)
require(
    "set_slave_latency_disabled(false);" in flash
    and "set_local_connection_latency(50);" in flash
    and "m_ble_data_policy_active = false;" in flash,
    "START erasure must restore slave latency before applying flash priority",
)

option_helpers = source[local_start:fast_start]
require(
    option_helpers.count("(void) sd_ble_opt_set(") == 2,
    "both DATA-phase SoftDevice options must remain fail-open",
)

connected = source.index("case BLE_GAP_EVT_CONNECTED:")
disconnected = source.index("case BLE_GAP_EVT_DISCONNECTED:", connected)
connected_body = source[connected:disconnected]
require(
    "sd_ble_gap_conn_param_update" not in connected_body,
    "CONNECTED must not revive the PHY/DLE connection-update race",
)

update = source.index("case BLE_GAP_EVT_CONN_PARAM_UPDATE:")
security = source.index("case BLE_GAP_EVT_SEC_PARAMS_REQUEST:", update)
update_body = source[update:security]
require(
    "if (m_ble_data_policy_active)" in update_body,
    "connection updates may restore fast latency only during firmware DATA",
)
require(
    "m_pkt_type" not in update_body,
    "stale packet type must not stand in for the live DATA phase",
)
require(
    "prioritize_ble_over_flash_writes();" in update_body,
    "DATA policy must be reapplied after a connection-parameter update",
)
require(
    "prioritize_flash_writes_over_ble" not in update_body,
    "a connection update must never start a new flash-priority phase",
)

receive = source.index("case BLE_DFU_RECEIVE_APP_DATA:")
packet_write = source.index("case BLE_DFU_PACKET_WRITE:", receive)
receive_body = source[receive:packet_write]
require(
    "m_pkt_type = PKT_TYPE_FIRMWARE_DATA;" in receive_body,
    "RECEIVE_APP_DATA must identify the phase used by the update handler",
)
require(
    "prioritize_ble_over_flash_writes();" in receive_body,
    "RECEIVE_APP_DATA must explicitly enter the fast DATA phase",
)

validate = source.index("case BLE_DFU_VALIDATE:")
activate = source.index("case BLE_DFU_ACTIVATE_N_RESET:", validate)
sys_reset = source.index("case BLE_DFU_SYS_RESET:", activate)
start = source.index("case BLE_DFU_START:", sys_reset)
init = source.index("case BLE_DFU_RECEIVE_INIT_DATA:", start)
for name, body in (
    ("VALIDATE", source[validate:activate]),
    ("ACTIVATE", source[activate:sys_reset]),
    ("SYS_RESET", source[sys_reset:start]),
    ("START", source[start:init]),
):
    require(
        "restore_ble_connection_policy();" in body,
        f"{name} must leave the DATA policy",
    )

callback_start = source.index("static void dfu_cb_handler")
error_notify = source.index("static void dfu_error_notify", callback_start)
callback_body = source[callback_start:error_notify]
require(
    callback_body.count("restore_ble_connection_policy();") >= 3,
    "START completion, final DATA completion, and DATA error must restore policy",
)
error_body = source[
    error_notify:source.index("static void start_data_process", error_notify)
]
require(
    "restore_ble_connection_policy();" in error_body,
    "all reported packet errors must leave the DATA phase",
)

disconnect = source.index("case BLE_GAP_EVT_DISCONNECTED:")
conn_update = source.index("case BLE_GAP_EVT_CONN_PARAM_UPDATE:", disconnect)
require(
    "m_ble_data_policy_active = false;" in source[disconnect:conn_update],
    "disconnect must clear connection-scoped DATA policy state",
)
update_start = source.index("uint32_t dfu_transport_ble_update_start(void)")
transport_close = source.index("uint32_t dfu_transport_ble_close()", update_start)
require(
    "m_ble_data_policy_active = false;" in source[update_start:transport_close],
    "a new transport session must start outside DATA",
)
require(
    "restore_ble_connection_policy();" in source[transport_close:],
    "transport close must restore policy before disconnect",
)

print(
    "BLE connection policy OK: central owns GAP updates; "
    "DATA latency is local, fail-open, restored on every exit, and "
    "reapplied only during a live DATA phase"
)
