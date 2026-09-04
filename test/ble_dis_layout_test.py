#!/usr/bin/env python3
"""Keep the Legacy DFU Device Information attribute handles cache-compatible."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


source = (
    ROOT / "lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c"
).read_text(encoding="utf-8")

helper = function_body(source, "static void dis_string_add(")
assert "attr_md.vloc = BLE_GATTS_VLOC_STACK" in helper, (
    "DIS values must be copied into SoftDevice-owned storage"
)
assert "sd_ble_gatts_characteristic_add" in helper

device_information = function_body(source, "static void device_information_init(void)")
expected = (
    "BLE_UUID_MANUFACTURER_NAME_STRING_CHAR",
    "BLE_UUID_MODEL_NUMBER_STRING_CHAR",
    "BLE_UUID_FIRMWARE_REVISION_STRING_CHAR",
)
positions = [device_information.index(uuid) for uuid in expected]
assert positions == sorted(positions), (
    "DIS characteristics must remain manufacturer, model, firmware so cached "
    "value handles stay at 0x0018, 0x001A, and 0x001C"
)
for value in ("BLEDIS_MANUFACTURER", "BLEDIS_MODEL", "BLEDIS_FW_VERSION"):
    assert value in device_information, f"DIS value omitted: {value}"
assert device_information.count("dis_string_add(") == 3, (
    "adding or removing an earlier DIS characteristic changes cached handles"
)

services = function_body(source, "static void services_init(void)")
assert services.index("ble_dfu_init(") < services.index("device_information_init();"), (
    "DFU must remain the first user service so DIS handles stay stable"
)

print("BLE DIS layout: legacy manufacturer/model/firmware handles preserved")
