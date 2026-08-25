#!/usr/bin/env python3
"""Guard the Legacy DFU advertising layout against silent UUID loss."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c"
ADV_MAX = 31


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


source = SOURCE.read_text(encoding="utf-8")
start = source.index("static void advertising_init(")
end = source.index("/**@brief Function for starting advertising.", start)
body = source[start:end]

flags_at = body.index("BLE_GAP_AD_TYPE_FLAGS")
uuid_at = body.index("BLE_GAP_AD_TYPE_128BIT_SERVICE_UUID_MORE_AVAILABLE")
complete_name_at = body.index("BLE_GAP_AD_TYPE_COMPLETE_LOCAL_NAME")
short_name_at = body.index("BLE_GAP_AD_TYPE_SHORT_LOCAL_NAME")

require(flags_at < uuid_at, "advertising flags must precede the DFU UUID")
require(uuid_at < complete_name_at, "DFU UUID must be reserved before the local name")
require(uuid_at < short_name_at, "short-name selection must occur after the DFU UUID")
require(
    "BLE_GAP_ADV_SET_DATA_SIZE_MAX - adv_data->len - 2" in body,
    "local-name length must be derived from the remaining advertising payload",
)

# Flags consume 3 bytes and the 128-bit UUID consumes 18. The name field has
# two bytes of AD overhead, leaving eight name bytes in a 31-byte legacy ad.
base_len = (1 + 1 + 1) + (1 + 1 + 16)
name_capacity = ADV_MAX - base_len - 2
require(name_capacity == 8, "unexpected Legacy DFU name capacity")

for name_len in (0, 6, 8, 9, 23, 255):
    advertised = min(name_len, name_capacity)
    total = base_len + 2 + advertised
    require(total <= ADV_MAX, f"{name_len}-byte name overflows advertising data")
    is_complete = advertised == name_len
    require(is_complete == (name_len <= name_capacity), "wrong complete/short name choice")

tower_make = ROOT / "src/boards/heltec_mesh_tower_v2/board.mk"
tower_name = re.search(
    r"-DDEVICE_NAME='\"([^\"]*)\"'", tower_make.read_text(encoding="utf-8")
)
require(tower_name is not None and tower_name.group(1) == "TOWER_V2_OTA",
        "MeshTower V2 regression fixture changed")
require(len(tower_name.group(1)) > name_capacity,
        "MeshTower V2 must exercise shortened-name advertising")

print(
    "BLE advertising layout OK: flags + UUID are fixed; "
    f"names longer than {name_capacity} bytes are shortened"
)
