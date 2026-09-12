#!/usr/bin/env python3
"""Verify exact-tag recovery artifacts and bundle them separately from mOTA."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

from intelhex import IntelHex

from build_bootloader_mota_release import add_to_zip, sha256, version_from_tag
from patch_bootloader_manifest import find_manifest, verify_manifest

ROOT = Path(__file__).resolve().parents[1]


def inspect_profile(artifacts, board, tag, packed):
    """Require one consistent HEX / Legacy ZIP / bootloader-family UF2 set."""
    prefix = f"R_{board}_bootloader-{tag}"
    files = []
    for pattern in (prefix + "_s*.hex", prefix + "_s*.zip",
                    "update-" + prefix + "_mbr.uf2"):
        matches = sorted(artifacts.glob(pattern))
        if len(matches) != 1 or matches[0].is_symlink():
            raise ValueError(f"{board}: expected one regular {pattern}")
        files.append(matches[0])
    hex_path, zip_path, uf2_path = files
    image = IntelHex(str(hex_path))
    _, start, size, name, extension = find_manifest(image)
    cmake = (ROOT / "src/boards" / board / "board.cmake").read_text()
    expected_name = re.search(r"set\(DEVICE_NAME\s+(\S+)\)", cmake).group(1)
    if (start, size, name, extension[4]) != (0xF4000, 0xA000, expected_name, packed):
        raise ValueError(f"{board}: bootloader identity/version/layout mismatch")
    verify_manifest(str(hex_path))
    raw = bytes(image.tobinarray(start=start, size=size))
    if f"R_0x{packed:08X}\0".encode() not in raw:
        raise ValueError(f"{board}: missing recovery firmware marker")
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"{board}: damaged Legacy ZIP")
        manifest = json.loads(archive.read("manifest.json"))["manifest"]
        if set(manifest) - {"dfu_version", "softdevice_bootloader"}:
            raise ValueError(f"{board}: unexpected DFU section")
        item = manifest["softdevice_bootloader"]
        payload = archive.read(item["bin_file"])
        if (item["bl_size"] != size or item["sd_size"] + size != len(payload)
                or payload[-size:] != raw or not archive.read(item["dat_file"])):
            raise ValueError(f"{board}: Legacy ZIP differs from HEX")
        sd = bytes(image.tobinarray(start=0x1000, size=item["sd_size"]))
        if payload[:item["sd_size"]] != sd:
            raise ValueError(f"{board}: SoftDevice differs between ZIP and HEX")
    uf2 = uf2_path.read_bytes()
    blocks = {}
    if not uf2 or len(uf2) % 512:
        raise ValueError(f"{board}: invalid UF2 length")
    for offset in range(0, len(uf2), 512):
        block = uf2[offset:offset + 512]
        m0, m1, flags, addr, length, index, count, family = struct.unpack_from("<8I", block)
        if ((m0, m1, flags, length, index, count, family) !=
                (0x0A324655, 0x9E5D5157, 0x2000, 256, offset // 512,
                 len(uf2) // 512, 0xD663823C)
                or struct.unpack_from("<I", block, 508)[0] != 0x0AB16F30
                or addr % 256 or addr in blocks
                or not (addr < 0x1000 or start <= addr < start + size or addr == 0x10001000)):
            raise ValueError(f"{board}: invalid UF2 framing/address")
        blocks[addr] = block[32:288]
    rebuilt = b"".join(blocks.get(addr, b"\xff" * 256)
                       for addr in range(start, start + size, 256))
    if rebuilt != raw or 0x10001000 not in blocks:
        raise ValueError(f"{board}: UF2 differs from HEX or lacks UICR")
    if struct.unpack_from("<II", blocks[0x10001000], 0x14) != (start, 0xFE000):
        raise ValueError(f"{board}: UF2 UICR layout mismatch")
    return files, {"board": board, "device_name": name,
                   "bootloader_sha256": hashlib.sha256(raw).hexdigest(),
                   "files": {path.name: sha256(path) for path in files}}


def build(artifacts, output, tag):
    label, _, packed = version_from_tag(tag)
    boards = sorted(path.name for path in (ROOT / "src/boards").iterdir() if path.is_dir())
    inventory, entries = [], []
    for board in boards:
        files, item = inspect_profile(artifacts, board, tag, packed)
        inventory.append(item)
        entries.extend((path, f"boards/{board}/{path.name}") for path in files)
    actual = {path for path in artifacts.iterdir() if path.is_file()}
    if actual != {path for path, _ in entries}:
        raise ValueError("unexpected or stale artifacts in recovery input directory")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("recovery output directory must be empty")
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({"tag": tag, "recovery_only": True,
        "packed_bootloader_version": f"0x{packed:08X}", "board_count": len(boards),
        "boards": inventory}, indent=2) + "\n", encoding="ascii")
    entries += [(manifest, manifest.name),
        (ROOT / "docs/recovery-allow-all.md", "RECOVERY-README.md"),
        (ROOT / "docs/recovery-rak3401-hardware-20260912.md", "recovery-rak3401-hardware-20260912.md")]
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(path)}  {name}\n" for path, name in entries), encoding="ascii")
    entries.append((checksums, checksums.name))
    bundle = output / f"OTAFIX-{label}-R_recovery.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for path, name in entries:
            add_to_zip(archive, path, name)
    (output / (bundle.name + ".sha256")).write_text(f"{sha256(bundle)}  {bundle.name}\n", encoding="ascii")
    print(f"Verified {len(boards)} recovery profiles in {bundle}")
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    build(args.artifacts_dir, args.output_dir, args.tag)
