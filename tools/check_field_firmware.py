#!/usr/bin/env python3
"""Validate the pinned field radios and record the exact CI-built checksums."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_gat562_field_kit as field


def check(directory: Path, *, verify: bool = False) -> None:
    blobs: dict[str, bytes] = {}
    for names, target, start, sd in (
        ((field.XIAO_COMPANION_UF2, field.XIAO_COMPANION_ZIP,
          field.XIAO_COMPANION_CAPABILITIES),
         "Xiao_nrf52_companion_radio_full", 0x27000, 291),
        ((field.GAT562_SOURCE_UF2, field.GAT562_SOURCE_ZIP,
          field.GAT562_SOURCE_CAPABILITIES),
         "GAT562_30S_Mesh_Kit_companion_radio_full", 0x26000, 182),
    ):
        uf2, package, capabilities = names
        blobs.update(field.checked_firmware(
            directory / uf2, directory / package, directory / capabilities,
            uf2_name=uf2, zip_name=package, capabilities_name=capabilities,
            artifact_target=target, application_start=start, softdevice_id=sd,
        ))
    blobs.update(field.checked_receiver(
        directory / field.GAT562_RECEIVER_UF2,
        directory / field.GAT562_RECEIVER_ZIP,
        directory / field.GAT562_RECEIVER_CAPABILITIES,
    ))
    manifest = {
        "repository": field.MESHCORE_REPOSITORY,
        "commit": field.MESHCORE_COMMIT,
        "firmware_version": field.MESHCORE_BUILD_VERSION,
        "files": {name: field.sha256_bytes(blob)
                  for name, blob in sorted(blobs.items())},
    }
    metadata = {
        "FIELD-FIRMWARE.json": (json.dumps(manifest, indent=2) + "\n").encode("ascii"),
        "FIELD-FIRMWARE.SHA256SUMS": field.checksum_file(sorted(blobs.items())),
    }
    for name, blob in metadata.items():
        path = directory / name
        if verify:
            if path.read_bytes() != blob:
                raise ValueError(f"{name} does not match the pinned field firmware")
        else:
            path.write_bytes(blob)
    print(f"Validated three field radios at {field.MESHCORE_COMMIT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--verify", action="store_true",
                        help="require existing provenance and checksums to match")
    args = parser.parse_args()
    check(args.artifacts_dir, verify=args.verify)


if __name__ == "__main__":
    main()
