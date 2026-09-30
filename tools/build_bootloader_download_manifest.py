#!/usr/bin/env python3
"""Publish exact-board download metadata from actual GitHub release assets."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from build_bootloader_mota_release import QUALIFIED_BOARDS, version_from_tag

ROOT = Path(__file__).resolve().parents[1]


def build_manifest(release, mapping):
    repo = "mikecarper/Adafruit_nRF52_Bootloader_OTAFIX"
    if mapping.get("schemaVersion") != 1 or mapping.get("repository") != repo:
        raise ValueError("unsupported board mapping")
    tag = release["tag_name"]
    label, _, _ = version_from_tag(tag)
    release_url = f"https://github.com/{repo}/releases/tag/{tag}"
    if release.get("draft") or release.get("html_url") != release_url:
        raise ValueError("expected a published OTAFIX release")
    definitions = mapping["profiles"]
    if (len(definitions) != len(QUALIFIED_BOARDS) or
            {item["id"] for item in definitions} != set(QUALIFIED_BOARDS)):
        raise ValueError("mapping must cover every normal release profile exactly once")
    aliases = [name for item in definitions for name in item["meshcoreHardware"]]
    unavailable = mapping.get("unavailableProfiles", [])
    unavailable_ids = [item["id"] for item in unavailable]
    if (len(unavailable_ids) != len(set(unavailable_ids)) or
            set(unavailable_ids).intersection(QUALIFIED_BOARDS) or
            any(not item.get("reason") or not item.get("meshcoreHardware")
                for item in unavailable)):
        raise ValueError("invalid unavailable bootloader profile")
    aliases += [name for item in unavailable for name in item["meshcoreHardware"]]
    if len(aliases) != len(set(aliases)):
        raise ValueError("ambiguous hardware alias")
    profiles = []
    for definition in definitions:
        board = definition["id"]
        cmake = (ROOT / "src/boards" / board / "board.cmake").read_text(encoding="ascii")
        identity = re.search(r"set\(DEVICE_NAME\s+(\S+)\)", cmake).group(1)
        storage = "adaptive" if "set(MOTA_RAK_AUTO_STORE ON)" in cmake else next(
            kind.lower() for kind in ("INTERNAL", "QSPI", "SD")
            if f"set(MOTA_{kind}_BOOTLOADER_UPDATE ON)" in cmake)
        files = {}
        for kind in ("uf2", "zip", "hex"):
            pattern = (f"update-{board}_bootloader-{tag}_mbr.uf2" if kind == "uf2"
                       else f"{board}_bootloader-{tag}_s140_")
            matches = [asset for asset in release["assets"]
                       if (asset["name"] == pattern if kind == "uf2" else
                           asset["name"].startswith(pattern) and
                           re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\." + kind,
                                        asset["name"][len(pattern):]))]
            if len(matches) != 1:
                raise ValueError(f"{board}: expected one exact {kind} asset")
            asset = matches[0]
            url = f"https://github.com/{repo}/releases/download/{tag}/{asset['name']}"
            digest = asset.get("digest") or ""
            if (asset["browser_download_url"] != url or asset["size"] <= 0 or
                    not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
                raise ValueError(f"{board}: invalid download URL, size or SHA-256")
            files[kind] = {"name": asset["name"], "url": url,
                           "size": asset["size"], "sha256": digest[7:]}
        profiles.append({**definition, "deviceName": identity,
                         "storage": storage, "files": files})
    return {"schemaVersion": 1, "repository": repo, "tag": tag,
            "version": label, "releaseUrl": release_url,
            "prerelease": bool(release.get("prerelease")), "profiles": profiles,
            "unavailableProfiles": unavailable}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", required=True, type=Path)
    parser.add_argument("--mapping", type=Path, default=ROOT / "docs/bootloader_profiles.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_manifest(json.loads(args.release_json.read_text(encoding="ascii")),
                              json.loads(args.mapping.read_text(encoding="ascii")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    args.output.write_bytes(data)
    args.output.with_name(args.output.name + ".sha256").write_text(
        hashlib.sha256(data).hexdigest() + "  " + args.output.name + "\n", encoding="ascii")
    print(f"Wrote {len(manifest['profiles'])} profiles / {3 * len(manifest['profiles'])} direct bootloader downloads")


if __name__ == "__main__":
    main()
