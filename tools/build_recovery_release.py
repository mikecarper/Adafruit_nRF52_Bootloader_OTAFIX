#!/usr/bin/env python3
"""Verify exact-tag recovery artifacts and bundle them separately from mOTA."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zipfile

from intelhex import IntelHex

from build_bootloader_mota_release import add_to_zip, parse_package, pending_boards, sha256, version_from_tag
from patch_bootloader_manifest import find_manifest, verify_manifest
from recovery_release_provenance import validate as validate_provenance

ROOT = Path(__file__).resolve().parents[1]
RAK_RECOVERY_BOARDS = ("wiscore_rak3401_auto", "wiscore_rak4631_auto")
RELEASE_BLOCKED_BOARDS = {
    "thinknode_m8": "Compile-only: factory USB identity is not verified.",
}


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
    if board in ("wiscore_rak3401_auto", "wiscore_rak4631_auto"):
        expected_name = expected_name.replace("_DFU", "_AUTO_DFU")
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


def alias_plan(paths, source_tag, distribution_tag):
    """Plan external filename aliases; never rewrite verified payload bytes."""
    aliases = {}
    for path in paths:
        marker = "_bootloader-" + source_tag
        if path.name.count(marker) != 1:
            raise ValueError("unexpected recovery source artifact filename")
        target = path.with_name(path.name.replace(marker, "_bootloader-" + distribution_tag, 1))
        if target != path and target.exists():
            raise ValueError("recovery filename alias would overwrite an existing artifact")
        if target in aliases.values():
            raise ValueError("duplicate recovery filename alias")
        aliases[path] = target
    return aliases


def build(artifacts, output, tag, recovery_mota_dir=None, source_tag=None,
          motatool=None, public_key=None, include_pending=False, release_tag=None):
    label, _, packed = version_from_tag(tag)
    provenance = {}
    artifact_tag = tag
    if release_tag is not None:
        if release_tag != "R_" + tag:
            raise ValueError("distribution tag must match the external recovery filename version")
        provenance = validate_provenance(ROOT, source_tag, release_tag)
        artifact_tag = source_tag.removeprefix("R_")
    pending = pending_boards(ROOT / "src/boards")
    boards = sorted(path.name for path in (ROOT / "src/boards").iterdir()
                    if path.is_dir() and path.name not in RELEASE_BLOCKED_BOARDS
                    and (include_pending or path.name not in pending))
    inventory, entries = [], []
    for board in boards:
        files, item = inspect_profile(artifacts, board, artifact_tag, packed)
        inventory.append(item)
        entries.extend((path, f"boards/{board}/{path.name}") for path in files)
    board_paths = {path for path, _ in entries}
    recovery_mota = []
    if recovery_mota_dir is not None:
        if source_tag != "R_" + tag or motatool is None or public_key is None:
            raise ValueError("repaired recovery bundle requires its exact R_ source tag, motatool and public key")
        public_text = public_key.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", public_text):
            raise ValueError("recovery signing public key must be 32 hex bytes")
        expected_signer = bytes.fromhex(public_text)
        expected_files = {
            recovery_mota_dir / f"update-R_{board}_bootloader-{tag}.mota"
            for board in RAK_RECOVERY_BOARDS
        }
        if {path for path in recovery_mota_dir.iterdir() if path.is_file()} != expected_files:
            raise ValueError("recovery mOTA directory must contain exactly the two RAK packages")
        for board in RAK_RECOVERY_BOARDS:
            path = recovery_mota_dir / f"update-R_{board}_bootloader-{tag}.mota"
            item = next(item for item in inventory if item["board"] == board)
            package = parse_package(path, board, packed, expected_signer)
            hw_id = f"NRF_BL_239A0029_{item['device_name']}"
            wire = hw_id.encode("ascii").ljust(32, b"\0")
            target_id = int.from_bytes(hashlib.sha256(wire).digest()[:4], "little")
            if (package["hardware_id"] != hw_id or
                    package["target_id"] != f"0x{target_id:08X}" or
                    package["image_sha256"] != item["bootloader_sha256"]):
                raise ValueError(f"{board}: recovery package does not match the rebuilt image")
            recovery_mota.append(package)
            entries.append((path, f"mota/{path.name}"))
        subprocess.run([str(motatool), "verify",
                        *(str(path) for path in sorted(expected_files)),
                        "--pub", str(public_key)], check=True)
    actual = {path for path in artifacts.iterdir() if path.is_file()}
    if actual != board_paths:
        raise ValueError("unexpected or stale artifacts in recovery input directory")
    aliases = alias_plan(board_paths, artifact_tag, tag)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("recovery output directory must be empty")
    for path, target in aliases.items():
        if path != target:
            path.rename(target)
    for item in inventory:
        item["files"] = {aliases[artifacts / name].name: digest
                         for name, digest in item["files"].items()}
    entries = [(aliases[path], name.rsplit("/", 1)[0] + "/" + aliases[path].name)
               if path in aliases else (path, name) for path, name in entries]
    manifest = output / "manifest.json"
    manifest_data = {"tag": tag, "recovery_only": True,
        "packed_bootloader_version": f"0x{packed:08X}", "board_count": len(boards),
        "boards": inventory}
    manifest_data.update(provenance)
    if include_pending:
        manifest_data["qualification_pending_boards"] = sorted(set(boards) & set(pending))
    excluded = {board: reason for board, reason in RELEASE_BLOCKED_BOARDS.items()
                if (ROOT / "src/boards" / board).is_dir()}
    if excluded:
        manifest_data["excluded_boards"] = excluded
    if recovery_mota:
        manifest_data.update(source_tag=source_tag, recovery_mota=recovery_mota)
    manifest.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="ascii")
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
    parser.add_argument("--recovery-mota-dir", type=Path)
    parser.add_argument("--source-tag")
    parser.add_argument("--release-tag", help="existing distribution tag; preserve filenames and record source provenance")
    parser.add_argument("--motatool", type=Path)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--include-pending", action="store_true",
                        help="include unqualified source ports and identify them in the inventory")
    args = parser.parse_args()
    build(args.artifacts_dir, args.output_dir, args.tag, args.recovery_mota_dir,
          args.source_tag, args.motatool, args.public_key, args.include_pending, args.release_tag)
