#!/usr/bin/env python3
"""Label RAK4631 release assets by application and storage profile."""

import argparse
import itertools
import json
import re
import subprocess


def api(*args):
    result = subprocess.run(
        ["gh", "api", *args], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def asset_labels(assets, tag):
    labels = {}
    seen = set()
    available = assets_by_name(assets)
    # Preserve truthful labels when maintaining historical two-profile releases.
    historical = any(asset["name"].startswith(f"wiscore_rak4631_board_bootloader-{tag}_")
                     for asset in assets)
    profiles = (
        ("auto", "unified app, adaptive storage", "4631_AUTO_DFU"),
        ("board", "internal-only storage", "4631_DFU"),
    ) if historical else (("auto", "compatible adaptive storage", "4631_DFU"),)
    for profile, description, identity in profiles:
        base = f"wiscore_rak4631_{profile}_bootloader-{tag}"
        types = {
            f"update-{base}_mbr.uf2": "bootloader UF2",
        }
        for asset in assets:
            name = asset["name"]
            if re.fullmatch(re.escape(base) + r"_s[0-9]+_[0-9.]+\.zip", name):
                types[name] = "local DFU ZIP"
            if re.fullmatch(re.escape(base) + r"_s[0-9]+_[0-9.]+\.hex", name):
                types[name] = "SWD HEX"
        for name, kind in types.items():
            if name not in available:
                raise ValueError(f"missing RAK4631 release asset: {name}")
            key = (profile, kind)
            if key in seen:
                raise ValueError(f"duplicate RAK4631 release asset: {key}")
            seen.add(key)
            labels[name] = f"RAK4631 {description} - {kind} ({identity})"
    if len(labels) != 3 * len(profiles):
        raise ValueError("expected three RAK4631 release assets per profile")
    return labels


def assets_by_name(assets):
    return {asset["name"]: asset for asset in assets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    release = api(f"repos/{args.repo}/releases/tags/{args.tag}")
    release_assets = []
    for page in itertools.count(1):
        batch = api(f"repos/{args.repo}/releases/{release['id']}/assets"
                    f"?per_page=100&page={page}")
        release_assets.extend(batch)
        if len(batch) < 100:
            break
    assets = assets_by_name(release_assets)
    labels = asset_labels(release_assets, args.tag)
    for name, label in sorted(labels.items()):
        asset = assets[name]
        if asset.get("label") != label and not args.dry_run:
            api("--method", "PATCH", f"repos/{args.repo}/releases/assets/{asset['id']}",
                "-f", f"label={label}")
        print(f"{name}: {label}")


if __name__ == "__main__":
    main()
