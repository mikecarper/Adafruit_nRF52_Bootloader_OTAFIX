#!/usr/bin/env python3
"""Build exact-board, hardware-untested OTAFIX preview images.

The regular release inventory deliberately remains unchanged. These images
are candidates for the corresponding MeshCore with-bootloader builds, not
evidence that a device has been physically tested.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

from intelhex import IntelHex

from derive_otafix_version import derive
from patch_bootloader_manifest import HEADER_FORMAT, find_manifest, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
BOOT_BASE, BOOT_SIZE = 0xF4000, 0xA000
# ID and name are jointly checked: several real boards share a USB VID/PID.
PROFILES = {
    "heltec_mesh_solar": (0x239A0071, "SOLARINT_DFU", 0xB6, 0x26000, "6.1.1"),
    "lilygo_techo_card": (0x239A00DA, "LTECARD_DFU", 0xB6, 0x26000, "6.1.1"),
    "lilygo_t_impulse_plus": (0x239A00DA, "LTIMP_DFU", 0xB6, 0x26000, "6.1.1"),
    "meshtracker_x1": (0x28860057, "X1INT_DFU", 0x123, 0x27000, "7.3.0"),
    "muzi_base": (0x239A0081, "MUZIB_DFU", 0xB6, 0x26000, "6.1.1"),
    "nano_g2_ultra": (0x42518695, "NANOG2_DFU", 0xB6, 0x26000, "6.1.1"),
}


def exact_preview_tag() -> tuple[str, int]:
    tag = subprocess.check_output(
        ["git", "describe", "--exact-match", "--dirty", "--tags"],
        cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    return tag, derive(tag, preview_only=True)


def verify_board(board: str, tag: str, version: int, build: Path, output: Path) -> dict:
    board_id, device, fwid, app_base, sd = PROFILES[board]
    prefix = f"{board}_bootloader-{tag}"
    hex_path = build / (prefix + ".hex")
    verify_manifest(str(hex_path))
    image = IntelHex(str(hex_path))
    address, start, size, name, extension = find_manifest(image)
    raw = bytes(image.tobinarray(start=start, size=size))
    fields = struct.unpack(HEADER_FORMAT, bytes(image[address + i] for i in range(struct.calcsize(HEADER_FORMAT))))
    if (start, size, fields[6], name, extension[4:9]) != (
            BOOT_BASE, BOOT_SIZE, board_id, device, (version, 140, fwid, app_base, 1)):
        raise ValueError(f"{board}: bootloader identity or flash layout mismatch")
    sp, reset = struct.unpack_from("<II", raw)
    if not (0x20000000 <= sp <= 0x20040000 and sp % 8 == 0 and reset & 1
            and start <= (reset & ~1) < start + size):
        raise ValueError(f"{board}: invalid bootloader vectors")
    expected_storage = 0x0A if board in ("heltec_mesh_solar", "meshtracker_x1") else 0x0E
    markers = [offset for offset in range(0, len(raw) - 15, 4)
               if raw[offset:offset + 8] == b"MOTABLDR"]
    if len(markers) != 1:
        raise ValueError(f"{board}: missing or duplicate OTA capability marker")
    abi, codecs, storage, r0, r1, r2 = struct.unpack_from("<HHBBBB", raw, markers[0] + 8)
    if abi < 1 or not codecs & 4 or storage != expected_storage or (r0, r1, r2) != (0, 0, 0):
        raise ValueError(f"{board}: unexpected OTA storage capability")
    if b"UF2 Bootloader " + tag.encode("ascii") + b"\r\n" not in raw:
        raise ValueError(f"{board}: bootloader is not labelled with its preview version")
    zip_path = output / f"{prefix}_s140_{sd}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))["manifest"]["softdevice_bootloader"]
        firmware = archive.read(manifest["bin_file"])
        if (manifest["bl_size"] != size or len(firmware) != manifest["sd_size"] + size
                or firmware[manifest["sd_size"]:] != raw
                or manifest["init_packet_data"]["firmware_crc16"] != binascii.crc_hqx(firmware, 0xFFFF)):
            raise ValueError(f"{board}: DFU ZIP differs from the verified bootloader")
    binary = output / f"{prefix}.bin"
    binary.write_bytes(raw)
    files = {}
    for path in sorted(output.glob(prefix + "*")):
        if path.is_file():
            files[path.name] = {"size": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    uf2 = output / f"update-{prefix}_mbr.uf2"
    if not uf2.is_file():
        raise ValueError(f"{board}: missing exact-board bootloader UF2")
    files[uf2.name] = {"size": uf2.stat().st_size,
                       "sha256": hashlib.sha256(uf2.read_bytes()).hexdigest()}
    return {"board_id": f"0x{board_id:08X}", "device_name": device,
            "app_base": f"0x{app_base:08X}", "softdevice_fwid": f"0x{fwid:04X}",
            "storage": "internal" if expected_storage == 0x0A else "qspi",
            "hardware_tested": False, "files": files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new or empty output directory outside the checkout")
    parser.add_argument("--board", action="append", choices=sorted(PROFILES),
                        help="board to build; repeat, or omit for all supported previews")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("output must be outside the source checkout")
    if output.exists() and any(output.iterdir()):
        parser.error("output directory must be empty")
    tag, version = exact_preview_tag()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    epoch = subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"],
                                    cwd=ROOT, text=True).strip()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH=epoch)
    profiles = {}
    for board in sorted(set(args.board or PROFILES)):
        build, published = output / "build" / board, output / "images" / board
        command = ["make", f"-j{args.jobs}", f"BOARD={board}", f"BUILD={build}", f"BIN={published}"]
        if board == "heltec_mesh_solar":
            command += ["MOTA_BOOTLOADER_TEST_BUILD=1", "OTAFIX_EXPERIMENTAL_PORT_PREVIEW=1"]
        subprocess.run(command + ["all", "copy-artifact"], cwd=ROOT, env=env, check=True)
        profiles[board] = verify_board(board, tag, version, build, published)
    result = {"schema": 1, "version_tag": tag, "source_commit": commit,
              "physical_tests": "not performed", "profiles": profiles}
    (output / "preview-manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    (output / "README.txt").write_text(
        "Experimental OTAFIX board previews\n\n"
        "These images were compiled and checked in software. They were not tested on the boards.\n"
        "Use only the exact board image. A bootloader update can require hardware recovery.\n"
        "These files are not yet bundled into the MeshCore 1.18.0.2 firmware.\n"
        "The ZIP includes a SoftDevice and is not a LoRa mOTA package.\n"
        "See preview-manifest.json for identities and SHA-256 hashes.\n", encoding="ascii")
    print(f"Built {len(profiles)} exact-board previews in {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"preview build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
