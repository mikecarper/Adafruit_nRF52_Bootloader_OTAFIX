#!/usr/bin/env python3
"""Build and verify the qualified OTAFIX bootloader mOTA release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile


QUALIFIED_BOARDS = (
    "gat562",
    "heltec_mesh_pocket",
    "heltec_mesh_tower_v2",
    "heltec_mesh_tower_v2_sdcard",
    "heltec_t096",
    "heltec_t1",
    "heltec_t114",
    "keepteen_lt1",
    "minewsemi_mx25le01",
    "promicro_nrf52840",
    "t1000_e",
    "thinknode_m3",
    "wiscore_rak3401",
    "wiscore_rak4631_board",
    "wismesh_tag",
    "xiao_nrf52840_ble",
    "xiao_nrf52840_ble_sense",
)

TAG_PATTERN = re.compile(
    r"^(?:v?[0-9]+\.[0-9]+\.[0-9]+-)?"
    r"OTAFIX(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?:-preview\.(?P<preview>[0-9]+))?$"
)

MOTA_SIZE = 41330
MOTA_MAGIC = b"mOTA"
MOTA_FORMAT_BOOTLOADER = 3
MOTA_FLAGS_BOOTLOADER = 0x07
MOTA_CODEC_FULL = 0
MOTA_HEADER_SIZE = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--motatool", required=True, type=Path)
    parser.add_argument("--sign-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    return parser.parse_args()


def version_from_tag(tag: str) -> tuple[str, str, int]:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"not a canonical OTAFIX release tag: {tag!r}")

    major, minor, patch = (
        int(match.group(name)) for name in ("major", "minor", "patch")
    )
    preview_text = match.group("preview")
    channel = 0xFF if preview_text is None else int(preview_text)
    if any(value > 0xFF for value in (major, minor, patch, channel)):
        raise ValueError("OTAFIX version components must fit one byte")
    if preview_text is not None and not 1 <= channel <= 0xFE:
        raise ValueError("preview channel must be in 1..254")

    packed = (major << 24) | (minor << 16) | (patch << 8) | channel
    label = f"{major}.{minor}.{patch}"
    if preview_text is not None:
        label += f"-preview.{channel}"
    assertion = f"{major}.{minor}.{patch}.{channel}"
    return label, assertion, packed


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_package(path: Path, board: str, expected_version: int,
                  expected_signer: bytes) -> dict[str, object]:
    blob = path.read_bytes()
    if len(blob) != MOTA_SIZE:
        raise ValueError(f"{path.name}: expected {MOTA_SIZE} bytes, got {len(blob)}")
    if blob[:4] != MOTA_MAGIC or struct.unpack_from("<I", blob, 4)[0] != len(blob):
        raise ValueError(f"{path.name}: invalid mOTA header")

    manifest = memoryview(blob)[MOTA_HEADER_SIZE:]
    format_ver, flags, hash_algo = manifest[0], manifest[1], manifest[2]
    target_id, fw_version, image_size, payload_size = struct.unpack_from(
        "<IIII", manifest, 3
    )
    block_size_log2 = manifest[19]
    merkle_root = bytes(manifest[20:24])
    image_hash = bytes(manifest[24:56])
    codec = manifest[56]
    hw_id = bytes(manifest[57:89]).rstrip(b"\0").decode("ascii")
    base_hash = bytes(manifest[89:97])
    signer = bytes(manifest[97:129])

    expected = (
        format_ver == MOTA_FORMAT_BOOTLOADER
        and flags == MOTA_FLAGS_BOOTLOADER
        and hash_algo == 0x12
        and fw_version == expected_version
        and image_size == 0xA000
        and payload_size == 0xA000
        and block_size_log2 == 10
        and codec == MOTA_CODEC_FULL
        and base_hash == bytes(8)
        and signer == expected_signer
    )
    if not expected:
        raise ValueError(f"{path.name}: bootloader package contract mismatch")

    return {
        "board": board,
        "file": path.name,
        "size": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "target_id": f"0x{target_id:08X}",
        "firmware_version": f"0x{fw_version:08X}",
        "hardware_id": hw_id,
        "merkle_root": merkle_root.hex().upper(),
        "image_sha256": image_hash.hex(),
        "codec": "full",
    }


def add_to_zip(archive: zipfile.ZipFile, path: Path, name: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, path.read_bytes())


def main() -> int:
    args = parse_args()
    version_label, version_assertion, packed_version = version_from_tag(args.tag)
    public_text = args.public_key.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", public_text):
        raise ValueError("public key must be exactly 32 bytes of hexadecimal")
    public_bytes = bytes.fromhex(public_text)

    if not args.motatool.is_file() or not args.sign_key.is_file():
        raise FileNotFoundError("motatool or signing key is missing")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    package_dir = args.output_dir / "mota"
    package_dir.mkdir(exist_ok=True)
    if any(package_dir.iterdir()):
        raise ValueError(f"package directory is not empty: {package_dir}")

    packages: list[Path] = []
    for board in QUALIFIED_BOARDS:
        matches = sorted(args.artifacts_dir.glob(f"{board}_bootloader-{args.tag}_s140_*.hex"))
        if len(matches) != 1:
            raise ValueError(
                f"{board}: expected one exact-tag bootloader HEX, found {len(matches)}"
            )
        output = package_dir / f"update-{board}_bootloader-{args.tag}.mota"
        run([
            str(args.motatool),
            "build-bootloader",
            "--fw", str(matches[0]),
            "--board", board,
            "--sign", str(args.sign_key),
            "--fw-version", version_assertion,
            "--out", str(output),
        ])
        packages.append(output)

    run([
        str(args.motatool),
        "verify",
        *map(str, packages),
        "--pub", str(args.public_key),
    ])

    inventory = [
        parse_package(path, board, packed_version, public_bytes)
        for board, path in zip(QUALIFIED_BOARDS, packages)
    ]
    inventory_path = args.output_dir / "manifest.json"
    inventory_path.write_text(
        json.dumps(
            {
                "release": f"OTAFIX {version_label}",
                "tag": args.tag,
                "packed_bootloader_version": f"0x{packed_version:08X}",
                "signing_public_key": public_text.upper(),
                "package_format": 3,
                "package_count": len(inventory),
                "packages": inventory,
            },
            indent=2,
        ) + "\n",
        encoding="ascii",
    )

    checksums_path = args.output_dir / "SHA256SUMS"
    checksums_path.write_text(
        "".join(f"{sha256(path)}  mota/{path.name}\n" for path in packages),
        encoding="ascii",
    )

    public_output = args.output_dir / "OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt"
    public_output.write_text(public_text.upper() + "\n", encoding="ascii")
    readme_path = args.output_dir / "README.txt"
    readme_path.write_text(
        f"""OTAFIX {version_label} signed bootloader mOTA packages

These are full, exact-board, format-3 bootloader packages. They update any
compatible older self-update-capable bootloader to {version_label}; the package
does not contain or require a source-version delta.

Official signing public key:
{public_text.upper()}

Trust the key once on the device console:
ota key add {public_text.upper()}

Then follow the explicit bootloader installation workflow. Always select the
exact board and storage profile. In particular, heltec_mesh_tower_v2 and
heltec_mesh_tower_v2_sdcard are not interchangeable even though they share a
wire target ID.

The gat562 profile covers the GAT562 30S Kit, Mesh Tracker Pro, EVB Pro / 30S
Pod, and Solar Relay carriers. It does not cover the GAT562 Mesh Watch 13,
which has populated QSPI flash and requires a separate exact storage profile.
An older GAT562 bootloader reporting legacy 4631_DFU needs a one-time local
USB/BLE DFU or SWD migration to the exact GAT562 bootloader before it can use
remote gat562 packages; exact identity matching cannot perform that migration.

Every package is exactly {MOTA_SIZE} bytes, signed, board-bound, and verified
against the public key. See manifest.json and SHA256SUMS for the inventory.
Never install a bootloader package on a similarly named board.
""",
        encoding="ascii",
    )

    bundle = args.output_dir / f"OTAFIX-{version_label}-bootloader-mota.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for path in (readme_path, public_output, inventory_path, checksums_path):
            add_to_zip(archive, path, path.name)
        for path in packages:
            add_to_zip(archive, path, f"mota/{path.name}")

    bundle_checksum = args.output_dir / f"{bundle.name}.sha256"
    bundle_checksum.write_text(f"{sha256(bundle)}  {bundle.name}\n", encoding="ascii")
    print(f"Built and verified {len(packages)} packages in {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
