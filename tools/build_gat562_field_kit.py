#!/usr/bin/env python3
"""Build a verified phone-driven GAT562 LoRa bootloader field kit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from build_bootloader_mota_release import version_from_tag


OFFICIAL_PUBLIC_KEY = (
    "272564CC588D3D122285A15E6E2566D2ABE7177BB7EA1D1E41B23B29F0F85D2D"
)
GAT562_BOARD = "gat562"
GAT562_TARGET = "0xD50D2D44"
GAT562_NAME = "GAT562_DFU"
GAT562_HARDWARE_ID = "NRF_BL_239A0029_GAT562_DFU"

MESHCORE_OPEN_REPOSITORY = "mikecarper/meshcore-open"
MESHCORE_OPEN_COMMIT = "40e440e7d5c3cbc925b7701225ea1f023b0d9ae7"
ANDROID_APK_NAME = "MeshCore-Open-9.5.1-OTAFIX-field-arm64.apk"

MESHCORE_REPOSITORY = "mikecarper/MeshCore"
MESHCORE_COMMIT = "51ce1f8f0d3cc454b02f77c1535008682e2d5831"
GAT562_RECEIVER_RELEASE_TAG = (
    "lora-ota-v1.17.1.4-halo-keymind-cascade-dev-4d5ccbdd"
)
XIAO_COMPANION_UF2 = (
    "Xiao_nrf52_companion_radio_full-v1.17.1-dev-51ce1f8f.uf2"
)
XIAO_COMPANION_ZIP = (
    "Xiao_nrf52_companion_radio_full-v1.17.1-dev-51ce1f8f.zip"
)
XIAO_COMPANION_CAPABILITIES = (
    "Xiao_nrf52_companion_radio_full-v1.17.1-dev-51ce1f8f.capabilities.json"
)
GAT562_SOURCE_UF2 = (
    "GAT562_30S_Mesh_Kit_companion_radio_full-v1.17.1-dev-51ce1f8f.uf2"
)
GAT562_SOURCE_ZIP = (
    "GAT562_30S_Mesh_Kit_companion_radio_full-v1.17.1-dev-51ce1f8f.zip"
)
GAT562_SOURCE_CAPABILITIES = (
    "GAT562_30S_Mesh_Kit_companion_radio_full-v1.17.1-dev-51ce1f8f."
    "capabilities.json"
)
GAT562_RECEIVER_UF2 = (
    "GAT562_30S_Mesh_Kit_repeater_lora_ota_no_external_sensors-ota-"
    "v1.17.1.4-halo-keymind-cascade-dev-4d5ccbdd.uf2"
)
GAT562_RECEIVER_ZIP = (
    "GAT562_30S_Mesh_Kit_repeater_lora_ota_no_external_sensors-ota-"
    "v1.17.1.4-halo-keymind-cascade-dev-4d5ccbdd.zip"
)
MESHCORE_RELEASE_ASSET_SHA256 = {
    GAT562_RECEIVER_UF2: (
        "eee459634e32973763d29962300e88d424d15d028e212995447367ca1ce48f82"
    ),
    GAT562_RECEIVER_ZIP: (
        "26c897f7837119c269bf8da8f729f246ca66c65cf507cb108720e5544e16c0e2"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--android-apk", required=True, type=Path)
    parser.add_argument("--xiao-companion-uf2", required=True, type=Path)
    parser.add_argument("--xiao-companion-zip", required=True, type=Path)
    parser.add_argument("--xiao-companion-capabilities", required=True, type=Path)
    parser.add_argument("--gat562-source-uf2", required=True, type=Path)
    parser.add_argument("--gat562-source-zip", required=True, type=Path)
    parser.add_argument("--gat562-source-capabilities", required=True, type=Path)
    parser.add_argument("--gat562-receiver-uf2", required=True, type=Path)
    parser.add_argument("--gat562-receiver-zip", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    return parser.parse_args()


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def write_zip(path: Path, files: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, blob in files:
            archive.writestr(zip_info(name), blob)


def checksum_file(files: list[tuple[str, bytes]]) -> bytes:
    return "".join(
        f"{sha256_bytes(blob)}  {name}\n" for name, blob in files
    ).encode("ascii")


def checked_release_asset(path: Path, expected_name: str) -> bytes:
    if path.name != expected_name:
        raise ValueError(f"expected {expected_name}, found {path.name}")
    blob = path.read_bytes()
    expected_hash = MESHCORE_RELEASE_ASSET_SHA256[expected_name]
    if sha256_bytes(blob) != expected_hash:
        raise ValueError(f"{expected_name} does not match its pinned SHA-256")
    return blob


def checked_full_companion(
    uf2_path: Path,
    zip_path: Path,
    capabilities_path: Path,
    *,
    uf2_name: str,
    zip_name: str,
    capabilities_name: str,
    artifact_target: str,
    application_start: int,
    softdevice_id: int,
) -> dict[str, bytes]:
    expected_paths = {
        uf2_name: uf2_path,
        zip_name: zip_path,
        capabilities_name: capabilities_path,
    }
    for expected_name, path in expected_paths.items():
        if path.name != expected_name:
            raise ValueError(f"expected {expected_name}, found {path.name}")

    capabilities_blob = capabilities_path.read_bytes()
    capabilities = json.loads(capabilities_blob.decode("ascii"))
    required_capabilities = {
        "profile.full",
        "companion.temp_radio",
        "companion.ota_cli",
        "companion.bluetooth",
        "companion.ble_mota_source",
    }
    actual_capabilities = set(capabilities.get("capabilities", []))
    if (
        capabilities.get("verified") is not True
        or capabilities.get("artifact_target")
        != artifact_target
        or not required_capabilities.issubset(actual_capabilities)
    ):
        raise ValueError(f"{artifact_target} does not permit phone mOTA")

    zip_blob = zip_path.read_bytes()
    try:
        with zipfile.ZipFile(zip_path) as archive:
            zip_names = set(archive.namelist())
            if not {"firmware.bin", "firmware.dat", "manifest.json"}.issubset(
                zip_names
            ):
                raise ValueError(f"{artifact_target} Serial DFU ZIP is incomplete")
            firmware = archive.read("firmware.bin")
            dfu_manifest = json.loads(archive.read("manifest.json"))
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"{artifact_target} Serial DFU package is not a valid ZIP"
        ) from exc

    application = dfu_manifest.get("manifest", {}).get("application", {})
    init_data = application.get("init_packet_data", {})
    if (
        application.get("bin_file") != "firmware.bin"
        or application.get("dat_file") != "firmware.dat"
        or init_data.get("softdevice_req") != [softdevice_id]
    ):
        raise ValueError(f"{artifact_target} Serial DFU manifest is unexpected")

    required_binary_markers = (
        b"v1.17.1-dev-51ce1f8f",
        b"14518fc2-7e7a-4d84-8cae-6664b0234cf2",
        b"2bfaa1ee-7030-459a-b65a-e7cfd5b09735",
        b"acf38a51-dd58-4dce-917f-0b1135e41b1a",
        b"Bluetooth mOTA source",
    )
    if any(marker not in firmware for marker in required_binary_markers):
        raise ValueError(f"{artifact_target} lacks its phone mOTA identity")

    uf2_blob = uf2_path.read_bytes()
    if len(uf2_blob) == 0 or len(uf2_blob) % 512 != 0:
        raise ValueError(f"{artifact_target} UF2 has invalid block geometry")
    payloads: list[tuple[int, bytes]] = []
    block_count = len(uf2_blob) // 512
    for index in range(block_count):
        block = uf2_blob[index * 512 : (index + 1) * 512]
        magic0, magic1, flags, address, size, number, total, family = (
            struct.unpack_from("<IIIIIIII", block)
        )
        if (
            magic0 != 0x0A324655
            or magic1 != 0x9E5D5157
            or struct.unpack_from("<I", block, 508)[0] != 0x0AB16F30
            or flags & 0x2000 == 0
            or family != 0xADA52840
            or size != 256
            or number != index
            or total != block_count
        ):
            raise ValueError(f"{artifact_target} UF2 block {index} is unexpected")
        payloads.append((address, block[32 : 32 + size]))
    payloads.sort()
    first_address = payloads[0][0]
    reconstructed = bytearray()
    for address, payload in payloads:
        if address != first_address + len(reconstructed):
            raise ValueError(f"{artifact_target} UF2 addresses are not contiguous")
        reconstructed.extend(payload)
    if (
        first_address != application_start
        or reconstructed[: len(firmware)] != firmware
        or any(byte != 0xFF for byte in reconstructed[len(firmware) :])
    ):
        raise ValueError(
            f"{artifact_target} UF2 and Serial DFU ZIP contain different images"
        )

    return {
        uf2_name: uf2_blob,
        zip_name: zip_blob,
        capabilities_name: capabilities_blob,
    }


def checked_apk(path: Path) -> bytes:
    if path.name != ANDROID_APK_NAME:
        raise ValueError(f"expected {ANDROID_APK_NAME}, found {path.name}")
    blob = path.read_bytes()
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            manifest_blob = (
                archive.read("AndroidManifest.xml")
                if "AndroidManifest.xml" in names
                else b""
            )
    except zipfile.BadZipFile as exc:
        raise ValueError("Android field APK is not a valid ZIP container") from exc
    required = {
        "AndroidManifest.xml",
        "classes.dex",
        "lib/arm64-v8a/libapp.so",
        "lib/arm64-v8a/libflutter.so",
    }
    missing = required - names
    if missing:
        raise ValueError(f"Android field APK lacks {sorted(missing)}")

    def manifest_has(value: str) -> bool:
        # Android's binary XML string pool may use either UTF-8 or UTF-16LE.
        return any(
            encoded in manifest_blob
            for encoded in (value.encode("utf-8"), value.encode("utf-16le"))
        )

    if not manifest_has(
        "com.meshcore.meshcore_open.otafixfield"
    ) or not manifest_has("MeshCore Open OTAFIX Field"):
        raise ValueError("Android field APK lacks its isolated package identity")
    if any(
        name.startswith("lib/")
        and not name.startswith("lib/arm64-v8a/")
        for name in names
    ):
        raise ValueError("Android field APK contains an unexpected ABI")
    return blob


def recipe(version: str, tag: str, package: dict[str, object]) -> str:
    package_name = str(package["file"])
    mid = str(package["merkle_root"]).upper()
    image_hash = str(package["image_sha256"])[:16].upper()
    return f"""GAT562 OTAFIX {version} bootloader update over LoRa

The topology
------------

  Android phone -- encrypted Bluetooth --> local Full Companion source
  local XIAO or second GAT562 ---- LoRa --> remote GAT562 repeater

The remote GAT562 is NOT connected by USB during this field update. The local
source may be either a XIAO nRF52840 or a second GAT562 30S Mesh Kit running
the included Full Companion firmware. The `.mota` remains on the phone: the
source requests small blocks over Bluetooth and serves them immediately over
LoRa. Neither source option stages the file in its external storage.
The XIAO's 2 MB external flash is not used by this transfer path.

What the update changes
-----------------------

The signed `{package_name}` file updates only the GAT562 OTAFIX bootloader. It
preserves the installed MeshCore application, node identity, contacts, keys,
radio settings, and other node data.

This package is for the GAT562 30S Kit, Mesh Tracker Pro, EVB Pro / 30S Pod,
and Solar Relay only when `ota bootloader` reports every value below:

  board=239A0029 target=D50D2D44 name=GAT562_DFU abi=3 caps=0A

STOP for `4631_DFU`, another target, or the GAT562 Mesh Watch 13. A legacy
`4631_DFU` installation needs a one-time local exact-board migration. The
Watch 13 has populated QSPI flash and needs a different profile.

Files in this kit
-----------------

* `android/{ANDROID_APK_NAME}`: an installable arm64 Android field build of
  MeshCore Open from commit {MESHCORE_OPEN_COMMIT}. It uses the separate app ID
  `com.meshcore.meshcore_open.otafixfield`, so it can coexist with a normal
  MeshCore Open installation. It is a CI/debug-signed field build, not a store
  release.
* `companion/{XIAO_COMPANION_ZIP}`, its `.uf2`, and the capability manifest:
  protocol-v14 nRF52 Full Companion firmware built from MeshCore commit
  {MESHCORE_COMMIT} for a Seeed XIAO nRF52840 plus Wio-SX1262 radio. The
  manifest proves that the encrypted Bluetooth mOTA source feature is present.
* `companion/{GAT562_SOURCE_ZIP}`, its `.uf2`, and the capability manifest:
  the equivalent Full Companion firmware for a second GAT562 30S Mesh Kit.
  This is a complete alternative to the XIAO source and also streams from the
  phone without using external storage. Other GAT562 hardware profiles are not
  interchangeable with this 30S source build.
* `mota/{package_name}`: the exact signed GAT562 OTAFIX {version} bootloader.
* `target-prerequisite/{GAT562_RECEIVER_ZIP}` and its `.uf2`: the GAT562 30S
  Mesh Kit LoRa-OTA receiver application, included only for initial bench
  provisioning or recovery. It is not sent during this bootloader update.
* `OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt`, `manifest.json`,
  `FIELD-COMPONENTS.json`, and `SHA256SUMS`: trust and integrity metadata.

Prepare before going into the field
-----------------------------------

1. Extract the kit and verify every file against `SHA256SUMS` (or verify the
   outer ZIP with its release `.sha256` sidecar).
2. Install `android/{ANDROID_APK_NAME}` on an arm64 Android phone. Android may
   ask you to allow installation from your file manager. The app is isolated
   from the normal app, so pair and configure it separately.
3. Prepare one local source. For a XIAO nRF52840 plus Wio-SX1262, install the
   exact XIAO Full Companion ZIP/UF2. Alternatively, install the included
   GAT562 30S Full Companion ZIP/UF2 on a second GAT562. Configure its normal
   MeshCore radio tuple and attach the antenna. USB may then be disconnected or
   used only for power; it does not carry the field update. Full Companion
   replaces that source radio's current application role. If OTAFIX 2.4.3 is
   installed on the source, do not use application-UF2 drive copy: use the
   Serial DFU ZIP or update its bootloader first.
4. The remote GAT562 must already run a MeshCore LoRa-OTA receiver application
   with the `ota` commands. If it does not, LoRa cannot bootstrap that receiver.
   Provision it locally before deployment with the exact application ZIP in
   `target-prerequisite/`. The included UF2 is also supplied for recovery, but
   DO NOT copy that application UF2 to a mounted GAT562 drive while OTAFIX 2.4.3
   is installed; update the bootloader by an allowed method first.

Field recipe: direct GAT562 example
-----------------------------------

1. Power the remote GAT562 normally. Do not attach its USB cable.
2. Power the selected local Full Companion source near the phone with its LoRa
   antenna attached: either the XIAO or the second GAT562 described above.
3. Open **MeshCore Open OTAFIX Field**, connect to that source over Bluetooth,
   and complete authenticated pairing (the included source builds use PIN
   `123456`). On **LoRa OTA**, the connection card must say **Companion
   transport: Bluetooth** and **Encrypted mOTA channel: Ready**.
4. Make sure the remote GAT562 is in the Companion's contacts. Open it in
   **Repeater Management**, log in with its admin password, and open its CLI.
5. Send `ota bootloader`. Continue only for the exact identity above. Send
   `ota key`; if the official key is not trusted, send:

     ota key add {OFFICIAL_PUBLIC_KEY}

   Re-run `ota key` and confirm the full key exactly. Never approve a shortened
   or different key.
6. Return to **Repeater Management**, open **LoRa OTA**, choose
   `mota/{package_name}` from the extracted kit, and wait for local validation.
7. For a direct link, leave both target routes at Direct and add no controlled
   intermediate. For a routed link, set the normal and temporary paths and add
   every intermediate whose radio the app must switch. Passive relays must
   already be on the chosen temporary tuple.
8. Choose a legal temporary tuple. The tested fast example is 909.950 MHz,
   BW500, SF5, CR5 with a 120-minute window; change the frequency and other
   values for local law, hardware, range, and network planning.
9. Tap **Test radios and start source**. The app first uses three-minute safety
   timers, proves the end-to-end temporary path, extends the timers, and then
   makes the phone's file available through the local source over LoRa.
10. Tap **Refresh updates** if needed, then tap **Pull** beside MID `{mid}`.
    Keep the app foregrounded, Bluetooth connected, and both radios powered.
    Wait until **Confirmed by target** is complete and status says ready.
11. Tap **Install and reboot**. For a bootloader package, the app reads the
    remote `ota bootloader` status and refuses to proceed unless it reports:

      staged:ready mid={mid} hash={image_hash}

    It then sends the exact explicit approval command
    `ota bootloader install {mid} {image_hash}`. Do not invent these values.
12. Let the GAT562 reboot and return to the mesh. The app restores radios. Log
    in again and verify `get bootloader.ver` reports OTAFIX {version}; verify
    `ota status` reports `blup:C8` and `no download`.

A direct BW500/SF5 transfer normally takes about 1m45s to 3m10s including
verification and reboot. Range, duty-cycle rules, congestion, and retries can
make it longer. The 120-minute timer is recovery margin, not expected runtime.

If something stops
------------------

Do not power-cycle during the final bootloader write. Before installation, an
interrupted transfer can be resumed; the target keeps verified staged blocks.
Use **Stop and restore controlled radios** when possible. Every app-controlled
temporary radio also has a bounded timer and returns to its saved radio. If the
target cannot run MeshCore afterward, use its exact local DFU or SWD recovery;
connecting the target by USB is a recovery path, not part of this LoRa recipe.

Release tag: {tag}
"""


def main() -> int:
    args = parse_args()
    version, _, _ = version_from_tag(args.tag)
    release_dir = args.release_dir.resolve()
    manifest_path = release_dir / "manifest.json"
    public_key_path = release_dir / "OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if manifest.get("tag") != args.tag:
        raise ValueError("release manifest tag does not match the field-kit tag")
    if str(manifest.get("signing_public_key", "")).upper() != OFFICIAL_PUBLIC_KEY:
        raise ValueError("release manifest does not use the official signing key")

    matches = [
        item
        for item in manifest.get("packages", [])
        if item.get("board") == GAT562_BOARD
    ]
    if len(matches) != 1 or str(matches[0].get("target_id")) != GAT562_TARGET:
        raise ValueError("release manifest lacks the unique exact GAT562 package")
    package = matches[0]
    if str(package.get("hardware_id", "")) != GAT562_HARDWARE_ID:
        raise ValueError("GAT562 package hardware identity is unexpected")
    package_path = release_dir / "mota" / str(package["file"])
    package_blob = package_path.read_bytes()
    if sha256_bytes(package_blob) != str(package["sha256"]):
        raise ValueError("GAT562 package does not match the release manifest")

    public_key_blob = public_key_path.read_bytes()
    if public_key_blob.decode("ascii").strip().upper() != OFFICIAL_PUBLIC_KEY:
        raise ValueError("release public key does not match the pinned key")

    apk_blob = checked_apk(args.android_apk)
    xiao_blobs = checked_full_companion(
        args.xiao_companion_uf2,
        args.xiao_companion_zip,
        args.xiao_companion_capabilities,
        uf2_name=XIAO_COMPANION_UF2,
        zip_name=XIAO_COMPANION_ZIP,
        capabilities_name=XIAO_COMPANION_CAPABILITIES,
        artifact_target="Xiao_nrf52_companion_radio_full",
        application_start=0x27000,
        softdevice_id=291,
    )
    gat562_source_blobs = checked_full_companion(
        args.gat562_source_uf2,
        args.gat562_source_zip,
        args.gat562_source_capabilities,
        uf2_name=GAT562_SOURCE_UF2,
        zip_name=GAT562_SOURCE_ZIP,
        capabilities_name=GAT562_SOURCE_CAPABILITIES,
        artifact_target="GAT562_30S_Mesh_Kit_companion_radio_full",
        application_start=0x26000,
        softdevice_id=182,
    )
    release_component_paths = {
        GAT562_RECEIVER_UF2: args.gat562_receiver_uf2,
        GAT562_RECEIVER_ZIP: args.gat562_receiver_zip,
    }
    release_component_blobs = {
        name: checked_release_asset(path, name)
        for name, path in release_component_paths.items()
    }

    field_manifest = dict(manifest)
    field_manifest["package_count"] = 1
    field_manifest["packages"] = [package]
    field_manifest_blob = (json.dumps(field_manifest, indent=2) + "\n").encode(
        "ascii"
    )
    readme_blob = recipe(version, args.tag, package).encode("ascii")
    components = {
        "field_kit": f"GAT562 OTAFIX {version} phone-driven LoRa update",
        "transfer_model": {
            "file_owner": "Android phone",
            "source_bridge_buffer_bytes": 256,
            "source_external_storage_required": False,
        },
        "meshcore_open": {
            "repository": MESHCORE_OPEN_REPOSITORY,
            "commit": MESHCORE_OPEN_COMMIT,
            "file": f"android/{ANDROID_APK_NAME}",
            "sha256": sha256_bytes(apk_blob),
            "application_id": "com.meshcore.meshcore_open.otafixfield",
        },
        "xiao_full_companion": {
            "repository": MESHCORE_REPOSITORY,
            "commit": MESHCORE_COMMIT,
            "files": {
                name: sha256_bytes(xiao_blobs[name])
                for name in (
                    XIAO_COMPANION_UF2,
                    XIAO_COMPANION_ZIP,
                    XIAO_COMPANION_CAPABILITIES,
                )
            },
        },
        "gat562_30s_full_companion_alternative": {
            "repository": MESHCORE_REPOSITORY,
            "commit": MESHCORE_COMMIT,
            "files": {
                name: sha256_bytes(gat562_source_blobs[name])
                for name in (
                    GAT562_SOURCE_UF2,
                    GAT562_SOURCE_ZIP,
                    GAT562_SOURCE_CAPABILITIES,
                )
            },
        },
        "gat562_30s_receiver_prerequisite": {
            "repository": MESHCORE_REPOSITORY,
            "release_tag": GAT562_RECEIVER_RELEASE_TAG,
            "files": {
                name: MESHCORE_RELEASE_ASSET_SHA256[name]
                for name in (GAT562_RECEIVER_UF2, GAT562_RECEIVER_ZIP)
            },
        },
        "otafix_bootloader": {
            "release_tag": args.tag,
            "file": f"mota/{package_path.name}",
            "sha256": sha256_bytes(package_blob),
            "manifest_id": str(package["merkle_root"]).upper(),
            "image_hash_prefix": str(package["image_sha256"])[:16].upper(),
        },
    }
    components_blob = (json.dumps(components, indent=2) + "\n").encode("ascii")

    local_bundle_name = f"GAT562-OTAFIX-{version}-LoRa-bundle.zip"
    local_bundle_files = [
        ("README.txt", readme_blob),
        (public_key_path.name, public_key_blob),
        ("manifest.json", field_manifest_blob),
        (f"mota/{package_path.name}", package_blob),
    ]
    local_bundle_files.append(("SHA256SUMS", checksum_file(local_bundle_files)))
    local_bundle_path = release_dir / local_bundle_name
    write_zip(local_bundle_path, local_bundle_files)
    local_bundle_checksum = (
        f"{sha256(local_bundle_path)}  {local_bundle_name}\n"
    ).encode("ascii")
    (release_dir / f"{local_bundle_name}.sha256").write_bytes(
        local_bundle_checksum
    )

    outer_files = [
        ("README.txt", readme_blob),
        ("FIELD-COMPONENTS.json", components_blob),
        (public_key_path.name, public_key_blob),
        ("manifest.json", field_manifest_blob),
        (f"mota/{package_path.name}", package_blob),
        (f"android/{ANDROID_APK_NAME}", apk_blob),
        (f"companion/{XIAO_COMPANION_UF2}", xiao_blobs[XIAO_COMPANION_UF2]),
        (f"companion/{XIAO_COMPANION_ZIP}", xiao_blobs[XIAO_COMPANION_ZIP]),
        (
            f"companion/{XIAO_COMPANION_CAPABILITIES}",
            xiao_blobs[XIAO_COMPANION_CAPABILITIES],
        ),
        (f"companion/{GAT562_SOURCE_UF2}", gat562_source_blobs[GAT562_SOURCE_UF2]),
        (f"companion/{GAT562_SOURCE_ZIP}", gat562_source_blobs[GAT562_SOURCE_ZIP]),
        (
            f"companion/{GAT562_SOURCE_CAPABILITIES}",
            gat562_source_blobs[GAT562_SOURCE_CAPABILITIES],
        ),
        (
            f"target-prerequisite/{GAT562_RECEIVER_UF2}",
            release_component_blobs[GAT562_RECEIVER_UF2],
        ),
        (
            f"target-prerequisite/{GAT562_RECEIVER_ZIP}",
            release_component_blobs[GAT562_RECEIVER_ZIP],
        ),
    ]
    outer_files.append(("SHA256SUMS", checksum_file(outer_files)))
    field_kit_name = f"GAT562-OTAFIX-{version}-LoRa-field-kit.zip"
    field_kit_path = release_dir / field_kit_name
    field_directory = field_kit_name.removesuffix(".zip")
    write_zip(
        field_kit_path,
        [(f"{field_directory}/{name}", blob) for name, blob in outer_files],
    )
    (release_dir / f"{field_kit_name}.sha256").write_text(
        f"{sha256(field_kit_path)}  {field_kit_name}\n", encoding="ascii"
    )
    (release_dir / f"GAT562-OTAFIX-{version}-LoRa-README.txt").write_bytes(
        readme_blob
    )
    print(f"Built verified phone-driven GAT562 field kit: {field_kit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
