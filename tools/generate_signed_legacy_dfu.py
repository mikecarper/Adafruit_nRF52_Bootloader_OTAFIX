#!/usr/bin/env python3
"""Generate a standard Nordic Legacy DFU 0.8 package on modern Python.

adafruit-nrfutil's unsigned 0.5 package generator remains the source of truth
for Intel HEX normalization and SD/bootloader split sizes. Its historical
signing helper is Python-2-specific, so this tool upgrades that temporary
package to the wire-compatible signed format using ``cryptography``.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


class PackageError(RuntimeError):
    pass


def parse_public_coordinate(value: str, label: str) -> bytes:
    try:
        coordinate = bytes(int(part.strip(), 0) for part in value.split(","))
    except (TypeError, ValueError) as exc:
        raise PackageError(f"{label} must be 32 comma-separated bytes") from exc
    if len(coordinate) != 32:
        raise PackageError(f"{label} must contain exactly 32 bytes")
    return coordinate


def load_signing_key(path: Path, expected_qx: bytes, expected_qy: bytes):
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise PackageError(f"cannot load unencrypted PEM signing key: {exc}") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise PackageError("signing key must use the NIST P-256 (prime256v1) curve")
    public = key.public_key().public_numbers()
    if public.x.to_bytes(32, "big") != expected_qx or public.y.to_bytes(
        32, "big"
    ) != expected_qy:
        raise PackageError("signing key does not match SIGNED_FW_QX/SIGNED_FW_QY")
    return key


def strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackageError(f"duplicate manifest key {key!r}")
        result[key] = value
    return result


def upgrade_package(unsigned_zip: Path, output: Path, signing_key) -> None:
    try:
        with zipfile.ZipFile(unsigned_zip) as archive:
            infos = archive.infolist()
            if len(infos) != 3 or any(
                info.is_dir()
                or info.flag_bits & 1
                or Path(info.filename).name != info.filename
                for info in infos
            ):
                raise PackageError("nrfutil produced an unexpected archive layout")
            members = {info.filename: archive.read(info) for info in infos}
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError(f"cannot read temporary nrfutil package: {exc}") from exc

    if "manifest.json" not in members:
        raise PackageError("nrfutil package has no manifest.json")
    try:
        root = json.loads(
            members["manifest.json"].decode("utf-8"),
            object_pairs_hook=strict_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("nrfutil package manifest is invalid") from exc
    if not isinstance(root, dict) or set(root) != {"manifest"}:
        raise PackageError("nrfutil package manifest has an unexpected shape")
    manifest = root["manifest"]
    kinds = [
        kind
        for kind in ("application", "bootloader", "softdevice", "softdevice_bootloader")
        if kind in manifest
    ]
    if len(kinds) != 1 or set(manifest) != {"dfu_version", kinds[0]}:
        raise PackageError("nrfutil package must contain exactly one firmware image")
    kind = kinds[0]
    item = manifest[kind]
    if manifest["dfu_version"] != 0.5 or not isinstance(item, dict):
        raise PackageError("nrfutil package is not Legacy DFU 0.5")
    bin_name = item.get("bin_file")
    dat_name = item.get("dat_file")
    if (
        not isinstance(bin_name, str)
        or not isinstance(dat_name, str)
        or bin_name not in members
        or dat_name not in members
        or set(members) != {"manifest.json", bin_name, dat_name}
    ):
        raise PackageError("nrfutil package members do not match its manifest")

    firmware = members[bin_name]
    init_packet = members[dat_name]
    if len(init_packet) < 14:
        raise PackageError("nrfutil init packet is too short")
    softdevice_count = struct.unpack_from("<H", init_packet, 8)[0]
    base_length = 10 + 2 * softdevice_count
    if softdevice_count == 0 or len(init_packet) != base_length + 2:
        raise PackageError("nrfutil init packet has invalid SoftDevice requirements")
    received_crc = struct.unpack_from("<H", init_packet, base_length)[0]
    if received_crc != binascii.crc_hqx(firmware, 0xFFFF):
        raise PackageError("nrfutil init packet CRC does not match its firmware")

    firmware_hash = hashlib.sha256(firmware).digest()
    signed_prefix = init_packet[:base_length] + struct.pack(
        "<II32s", 2, len(firmware), firmware_hash
    )
    der_signature = signing_key.sign(signed_prefix, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    signed_init = signed_prefix + signature
    if len(signed_init) > 128:
        raise PackageError("signed init packet exceeds the bootloader's 128-byte buffer")

    metadata = item.get("init_packet_data")
    expected_unsigned = {
        "application_version",
        "device_revision",
        "device_type",
        "firmware_crc16",
        "softdevice_req",
    }
    if not isinstance(metadata, dict) or set(metadata) != expected_unsigned:
        raise PackageError("nrfutil init metadata has an unexpected shape")
    item["init_packet_data"] = {
        "application_version": metadata["application_version"],
        "device_revision": metadata["device_revision"],
        "device_type": metadata["device_type"],
        "ext_packet_id": 2,
        "firmware_hash": firmware_hash.hex(),
        "firmware_length": len(firmware),
        "init_packet_ecds": signature.hex(),
        "softdevice_req": metadata["softdevice_req"],
    }
    manifest["dfu_version"] = 0.8
    members[dat_name] = signed_init
    members["manifest.json"] = (
        json.dumps(root, sort_keys=True, indent=4, separators=(",", ": ")) + "\n"
    ).encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in (dat_name, "manifest.json", bin_name):
                archive.writestr(name, members[name])
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nrfutil", default="adafruit-nrfutil")
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--expected-qx", required=True)
    parser.add_argument("--expected-qy", required=True)
    parser.add_argument("--dev-type", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--dev-revision", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--bootloader", required=True, type=Path)
    parser.add_argument("--softdevice", required=True, type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        qx = parse_public_coordinate(args.expected_qx, "SIGNED_FW_QX")
        qy = parse_public_coordinate(args.expected_qy, "SIGNED_FW_QY")
        key = load_signing_key(args.key_file, qx, qy)
        with tempfile.TemporaryDirectory(prefix="otafix_signed_dfu_") as directory:
            unsigned_zip = Path(directory) / "unsigned.zip"
            subprocess.run(
                [
                    args.nrfutil,
                    "dfu",
                    "genpkg",
                    "--dfu-ver",
                    "0.5",
                    "--dev-type",
                    str(args.dev_type),
                    "--dev-revision",
                    str(args.dev_revision),
                    "--bootloader",
                    str(args.bootloader),
                    "--softdevice",
                    str(args.softdevice),
                    str(unsigned_zip),
                ],
                check=True,
            )
            upgrade_package(unsigned_zip, args.output, key)
    except (OSError, PackageError, subprocess.CalledProcessError) as exc:
        print(f"signed Legacy DFU package generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Created signed Nordic Legacy DFU package: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
