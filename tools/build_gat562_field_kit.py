#!/usr/bin/env python3
"""Build a verified, offline-capable GAT562 LoRa bootloader field kit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

from build_bootloader_mota_release import version_from_tag


OFFICIAL_PUBLIC_KEY = (
    "272564CC588D3D122285A15E6E2566D2ABE7177BB7EA1D1E41B23B29F0F85D2D"
)
PYSERIAL_35_SHA256 = (
    "c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0"
)
GAT562_BOARD = "gat562"
GAT562_TARGET = "0xD50D2D44"
GAT562_NAME = "GAT562_DFU"
GAT562_HARDWARE_ID = "NRF_BL_239A0029_GAT562_DFU"
ELF_MACHINE_X86_64 = 62
ELF_MACHINE_AARCH64 = 183


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--motatool-x86-64", required=True, type=Path)
    parser.add_argument("--motatool-aarch64", required=True, type=Path)
    parser.add_argument("--pyserial-wheel", required=True, type=Path)
    parser.add_argument("--updater", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    return parser.parse_args()


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def zip_info(name: str, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    return info


def write_zip(path: Path, files: list[tuple[str, bytes, bool]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, blob, executable in files:
            archive.writestr(zip_info(name, executable), blob)


def validate_elf(path: Path, expected_machine: int) -> bytes:
    blob = path.read_bytes()
    if (
        len(blob) < 20
        or blob[:4] != b"\x7fELF"
        or blob[4] != 2
        or blob[5] != 1
        or struct.unpack_from("<H", blob, 18)[0] != expected_machine
    ):
        raise ValueError(f"{path}: wrong or invalid 64-bit little-endian ELF")
    return blob


def checksum_file(files: list[tuple[str, bytes, bool]]) -> bytes:
    return "".join(
        f"{sha256_bytes(blob)}  {name}\n" for name, blob, _ in files
    ).encode("ascii")


def recipe(
    version: str,
    tag: str,
    package: dict[str, object],
    local_bundle_name: str,
) -> str:
    package_name = str(package["file"])
    mid = str(package["merkle_root"]).upper()
    image_hash = str(package["image_sha256"])[:16].upper()
    return f"""GAT562 OTAFIX {version} LoRa bootloader field update

Purpose
-------

This kit updates only the OTAFIX bootloader over MeshCore LoRa. It preserves
the installed MeshCore application and node data. It is usable without
downloading release files after the kit has been obtained.

This exact package is for GAT562 30S Kit, Mesh Tracker Pro, EVB Pro / 30S Pod,
and Solar Relay carriers that report all of these values:

  board=239A0029
  target=D50D2D44
  name=GAT562_DFU
  ABI=3
  caps=0A

STOP if the target reports 4631_DFU, a different target, or is a GAT562 Mesh
Watch 13. The watch has populated QSPI storage and needs its own exact profile.
A legacy 4631_DFU installation needs a one-time local exact-board migration;
the LoRa updater deliberately cannot change bootloader identity.

What to bring
-------------

1. A 64-bit Raspberry Pi/Linux host (aarch64) or 64-bit Linux laptop (x86_64)
   with Python 3.
2. The USB-connected GAT562 target running a MeshCore application that exposes
   the text console and `ota` commands.
3. A second USB-connected MeshCore radio to seed the LoRa file. It may be a
   Full Companion or a raw CLI repeater.
4. This extracted field-kit directory. It contains both motatool binaries,
   PySerial 3.5, the updater, public key, manifest, checksums, and the exact
   signed `{package_name}` payload.

Easy automated recipe
---------------------

1. Back up the node when practical, connect the GAT562 and source radio, then
   verify the release sidecar and extract this ZIP on the Linux host:

     sha256sum -c GAT562-OTAFIX-{version}-LoRa-field-kit.zip.sha256
2. In the extracted directory run:

     chmod +x run-gat562-lora-update.sh
     ./run-gat562-lora-update.sh

   If the serial paths are known, they may be pinned:

     ./run-gat562-lora-update.sh \\
       --target-serial /dev/serial/by-id/GAT562_TARGET \\
       --source-serial /dev/serial/by-id/LORA_SOURCE \\
       --source-mode auto --hops 1 --bandwidth 500

3. Select the entry showing `GAT562_DFU` and target `D50D2D44`. Never select by
   a similar product name alone.
4. Select "Download, verify, and install" and then the separate source radio.
5. For a direct link, choose 1 hop and BW500. The default example frequency is
   909.950 MHz/SF5; override `--frequency` when required and use only settings
   legal at the field location. Every intermediate relay must use the same
   temporary radio tuple.
6. The updater verifies the local bundle, official signer, package hash, exact
   target identity, and staged MID/hash. Approve the official public key only
   when this fingerprint is displayed:

     {OFFICIAL_PUBLIC_KEY}

7. Approve the final install only after the node reports this exact staged
   identity:

     MID {mid}
     image hash prefix {image_hash}

8. Leave both radios powered. A direct BW500/SF5 transfer normally takes about
   1m45s to 3m10s including verification and reboot. Success requires OTAFIX
   {version}, unchanged target D50D2D44, `blup:C8`, and `no download`.

The wrapper uses `{local_bundle_name}` and never queries GitHub. It restores
normal radio settings on ordinary success or failure. If the host loses power,
open each radio's MeshCore console and issue `normalradio` before retrying.

Manual fallback
---------------

Choose the bundled binary for the host architecture and verify the package:

  bin/linux-x86_64/motatool verify mota/{package_name} \\
    --pub OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt

Use `bin/linux-aarch64/motatool` on a 64-bit Raspberry Pi. Put the target,
source, and any relays on one legal temporary tuple, for example:

  tempradio 909.950,500,5,5,120

Start the source seeder (add `--companion-terminal` for a Full Companion):

  bin/linux-aarch64/motatool serve --dir mota \\
    --serial /dev/serial/by-id/LORA_SOURCE -v --companion-terminal

On the GAT562 target console run:

  ota key
  ota key add {OFFICIAL_PUBLIC_KEY}
  ota ls
  ota pull {mid} flash
  ota status

Repeat `ota status` until it says ready to install. Then require:

  ota bootloader

to report `staged:ready mid={mid} hash={image_hash}` before issuing:

  ota bootloader install {mid} {image_hash}

Do not invent either confirmation value. After reboot, verify
`get bootloader.ver` reports OTAFIX {version}; verify `ota status` contains
`blup:C8` and `no download`; then issue `normalradio` on the source and target.

Release tag: {tag}
"""


def wrapper(local_bundle_name: str, wheel_name: str) -> bytes:
    return f"""#!/usr/bin/env bash
set -eu

field_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(uname -m)" in
  x86_64|amd64)
    motatool_bin="$field_root/bin/linux-x86_64/motatool"
    ;;
  aarch64|arm64)
    motatool_bin="$field_root/bin/linux-aarch64/motatool"
    ;;
  *)
    echo "Unsupported host architecture: $(uname -m)" >&2
    exit 2
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required." >&2
  exit 2
fi

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required to verify the field kit." >&2
  exit 2
fi
(cd "$field_root" && sha256sum -c SHA256SUMS)

wheel="$field_root/vendor/{wheel_name}"
if [ -n "${{PYTHONPATH:-}}" ]; then
  field_pythonpath="$wheel:$PYTHONPATH"
else
  field_pythonpath="$wheel"
fi

PYTHONPATH="$field_pythonpath" exec python3 \
  "$field_root/otafix_mota_update.py" \
  --direct-serial \
  --require-identity 239A0029,D50D2D44,GAT562_DFU,3,0A \
  --release-bundle "$field_root/{local_bundle_name}" \
  --motatool "$motatool_bin" "$@"
""".encode("ascii")


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
        item for item in manifest.get("packages", [])
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
    updater_blob = args.updater.read_bytes()
    if b"--release-bundle" not in updater_blob or b"--direct-serial" not in updater_blob:
        raise ValueError("field updater lacks offline/direct-serial support")

    x86_blob = validate_elf(args.motatool_x86_64, ELF_MACHINE_X86_64)
    arm_blob = validate_elf(args.motatool_aarch64, ELF_MACHINE_AARCH64)
    wheel_blob = args.pyserial_wheel.read_bytes()
    if (
        not re.fullmatch(r"pyserial-3\.5-py2\.py3-none-any\.whl", args.pyserial_wheel.name)
        or sha256_bytes(wheel_blob) != PYSERIAL_35_SHA256
    ):
        raise ValueError("field kit requires the pinned PySerial 3.5 wheel")

    field_manifest = dict(manifest)
    field_manifest["package_count"] = 1
    field_manifest["packages"] = [package]
    field_manifest_blob = (
        json.dumps(field_manifest, indent=2) + "\n"
    ).encode("ascii")
    package_checksum = (
        f"{sha256_bytes(package_blob)}  mota/{package_path.name}\n"
    ).encode("ascii")

    local_bundle_name = f"GAT562-OTAFIX-{version}-LoRa-bundle.zip"
    readme_blob = recipe(version, args.tag, package, local_bundle_name).encode("ascii")
    local_bundle_files = [
        ("README.txt", readme_blob, False),
        (public_key_path.name, public_key_blob, False),
        ("manifest.json", field_manifest_blob, False),
        ("SHA256SUMS", package_checksum, False),
        (f"mota/{package_path.name}", package_blob, False),
    ]
    local_bundle_path = release_dir / local_bundle_name
    write_zip(local_bundle_path, local_bundle_files)
    local_bundle_blob = local_bundle_path.read_bytes()
    local_bundle_checksum = (
        f"{sha256_bytes(local_bundle_blob)}  {local_bundle_name}\n"
    ).encode("ascii")
    (release_dir / f"{local_bundle_name}.sha256").write_bytes(local_bundle_checksum)

    wheel_name = args.pyserial_wheel.name
    updater_checksum = (
        f"{sha256_bytes(updater_blob)}  otafix_mota_update.py\n"
    ).encode("ascii")
    outer_files = [
        ("README.txt", readme_blob, False),
        ("run-gat562-lora-update.sh", wrapper(local_bundle_name, wheel_name), True),
        ("otafix_mota_update.py", updater_blob, True),
        ("otafix_mota_update.py.sha256", updater_checksum, False),
        (local_bundle_name, local_bundle_blob, False),
        (f"{local_bundle_name}.sha256", local_bundle_checksum, False),
        (public_key_path.name, public_key_blob, False),
        ("manifest.json", field_manifest_blob, False),
        (f"mota/{package_path.name}", package_blob, False),
        ("bin/linux-x86_64/motatool", x86_blob, True),
        ("bin/linux-aarch64/motatool", arm_blob, True),
        (f"vendor/{wheel_name}", wheel_blob, False),
    ]
    outer_files.append(("SHA256SUMS", checksum_file(outer_files), False))
    field_kit_name = f"GAT562-OTAFIX-{version}-LoRa-field-kit.zip"
    field_kit_path = release_dir / field_kit_name
    field_directory = field_kit_name.removesuffix(".zip")
    write_zip(
        field_kit_path,
        [
            (f"{field_directory}/{name}", blob, executable)
            for name, blob, executable in outer_files
        ],
    )
    (release_dir / f"{field_kit_name}.sha256").write_text(
        f"{sha256(field_kit_path)}  {field_kit_name}\n", encoding="ascii"
    )
    (release_dir / f"GAT562-OTAFIX-{version}-LoRa-README.txt").write_bytes(
        readme_blob
    )
    print(f"Built verified GAT562 field kit: {field_kit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
