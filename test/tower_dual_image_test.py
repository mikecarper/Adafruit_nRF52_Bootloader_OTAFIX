"""Qualify a real combined Tower BIN with MeshCore's signer and both SD validators.

Usage: python3 tower_dual_image_test.py --meshcore PATH --image bootloader.bin
The ephemeral signing key exists only in memory; no production key is used.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meshcore", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.meshcore / "tools/mota"))
    import motalib as ml
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    image = args.image.read_bytes()
    identity = ml.validate_bootloader_image(image)
    assert (identity.board_id, identity.device_name) == (0x239A0071, "TOWER_V2_OTA")
    assert ml.bootloader_caps_storage(image) == 0x09
    assert ml.bootloader_optional_app_storage(image) == 0x02
    private = Ed25519PrivateKey.generate()
    manifest = ml.build_manifest(
        target_id=ml.bootloader_target_id(identity.board_id, identity.device_name),
        fw_version=identity.boot_version, image_size=len(image), payload=image,
        block_size=1024, image_hash=ml.mh32(image), codec_id=ml.CODEC_FULL,
        is_full=True, sign_priv=private, bootloader=True)
    package = ml.build_container(manifest, image)
    assert ml.verify(ml.parse_container(package), expect_pub=ml.ed25519_public_bytes(private)) == []
    test_dir = Path(__file__).resolve().parent
    subprocess.run(["make", "bootloader_mota_sd_test", "tower_dual_boot_sd_test"], cwd=test_dir, check=True)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "combined.mota"
        path.write_bytes(package)
        for name in ("bootloader_mota_sd_test", "tower_dual_boot_sd_test"):
            result = subprocess.run([str(test_dir / name)], cwd=test_dir, check=True,
                                    env={**os.environ, "MOTA_EXACT_PACKAGE": str(path)},
                                    text=True, capture_output=True)
            for line in result.stdout.splitlines():
                if "exact +365" in line or "SUITE" in line:
                    print(name + ": " + line)
    print("Real combined image: signer verification and existing SD -> combined OTA acceptance PASS")


if __name__ == "__main__":
    main()
