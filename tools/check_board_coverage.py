#!/usr/bin/env python3
"""Validate source/qualification coverage without turning candidates into downloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from build_bootloader_mota_release import (
    PENDING_BOARDS, QUALIFIED_BOARDS, RETIRED_NORMAL_PROFILES,
)

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / "src/boards"


def validate_coverage(mapping: dict) -> dict[str, int]:
    """Fail closed on omitted candidates, invented ports, or qualification drift.

    Qualification metadata describes unavailable profiles only. It never
    authorizes a build, flash operation, identity alias or release promotion.
    Existing release policy is still derived from the actual board sources.
    """
    available = mapping.get("profiles", [])
    unavailable = mapping.get("unavailableProfiles", [])
    if (len(available) != len(QUALIFIED_BOARDS) or
            {item.get("id") for item in available} != set(QUALIFIED_BOARDS)):
        raise ValueError("mapping must cover every normal release profile exactly once")
    hardware = [name for item in available + unavailable
                for name in item.get("meshcoreHardware", [])]
    if (not hardware or any(not isinstance(name, str) or not name for name in hardware) or
            len(hardware) != len(set(hardware))):
        raise ValueError("ambiguous or invalid hardware alias")
    ids = [item.get("id") for item in unavailable]
    if len(ids) != len(set(ids)) or set(ids).intersection(QUALIFIED_BOARDS):
        raise ValueError("invalid unavailable bootloader profile")

    pending = set()
    retired = set()
    counts = {"releasedProfiles": len(available), "releasedHardware":
              sum(len(item["meshcoreHardware"]) for item in available),
              "pendingProfiles": 0, "pendingHardware": 0,
              "blockedProfiles": 0, "blockedHardware": 0,
              "retiredProfiles": 0, "retiredHardware": 0}
    for item in unavailable:
        board = item.get("id")
        q = item.get("qualification")
        if (not isinstance(board, str) or not re.fullmatch(r"[a-z0-9_]+", board) or
                not item.get("reason") or not item.get("meshcoreHardware") or
                not isinstance(q, dict)):
            raise ValueError(f"{board}: missing qualification metadata")
        if "files" in item or q.get("hardwareQualified") is not False:
            raise ValueError(f"{board}: unavailable profile cannot claim qualified downloads")
        if (q.get("factoryIdentity") not in {"verified", "unverified"} or
                not isinstance(q.get("blockers"), list) or not q["blockers"] or
                any(not isinstance(value, str) or not value.strip() for value in q["blockers"]) or
                not isinstance(q.get("evidence"), list) or not q["evidence"] or
                any(not isinstance(url, str) or not url.startswith("https://")
                    for url in q["evidence"])):
            raise ValueError(f"{board}: qualification requires explicit blockers and primary evidence")
        status = q.get("status")
        directory = BOARDS / board
        if status == "source-blocked":
            if q.get("sourceBoard") is not None or q.get("storage") != "unknown" or directory.exists():
                raise ValueError(f"{board}: blocked metadata disagrees with source inventory")
            category = "blocked"
        elif status in {"source-pending", "retired"}:
            if q.get("sourceBoard") != board:
                raise ValueError(f"{board}: qualification may not substitute another source board")
            for filename in ("board.h", "board.mk", "board.cmake", "pinconfig.c"):
                if not (directory / filename).is_file():
                    raise ValueError(f"{board}: incomplete source port")
            cmake = (directory / "board.cmake").read_text(encoding="ascii")
            make = (directory / "board.mk").read_text(encoding="ascii")
            header = (directory / "board.h").read_text(encoding="ascii")
            storage = q.get("storage")
            if storage not in {"internal", "qspi", "sd"}:
                raise ValueError(f"{board}: unknown source storage")
            backend = storage.upper()
            if (f"set(MOTA_{backend}_BOOTLOADER_UPDATE ON)" not in cmake or
                    f"-DMOTA_{backend}_BOOTLOADER_UPDATE=1" not in make):
                raise ValueError(f"{board}: qualification storage disagrees with Make/CMake")
            if status == "source-pending":
                if "set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)" not in cmake:
                    raise ValueError(f"{board}: missing pending release exclusion")
                pending.add(board)
                category = "pending"
                if q["factoryIdentity"] == "unverified":
                    # Unknown USB identity must remain an invalid compiler
                    # fixture, with explicit test-build guards in both systems.
                    for key in ("USB_DESC_VID", "USB_DESC_UF2_PID", "USB_DESC_CDC_ONLY_PID"):
                        if not re.search(rf"^#define\s+{key}\s+0x0000\s*$", header, re.M):
                            raise ValueError(f"{board}: unverified identity is not an invalid compiler fixture")
                    if ("MOTA_BOOTLOADER_TEST_BUILD" not in cmake or
                            "MOTA_BOOTLOADER_TEST_BUILD" not in make or
                            "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE" not in cmake or
                            "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE" not in make or
                            "#error" not in header):
                        raise ValueError(f"{board}: unverified identity requires compile-only guards")
                else:
                    for key in ("USB_DESC_VID", "USB_DESC_UF2_PID"):
                        match = re.search(rf"^#define\s+{key}\s+(0x[0-9A-Fa-f]+)\s*$", header, re.M)
                        if not match or int(match[1], 16) in (0, 0xffff):
                            raise ValueError(f"{board}: verified identity is invalid")
            else:
                if (board not in RETIRED_NORMAL_PROFILES or q.get("localMigrationOnly") is not True or
                        q.get("replacementProfile") not in QUALIFIED_BOARDS):
                    raise ValueError(f"{board}: retired profile requires exact local-only replacement")
                retired.add(board)
                category = "retired"
        else:
            raise ValueError(f"{board}: unknown qualification status")
        counts[category + "Profiles"] += 1
        counts[category + "Hardware"] += len(item["meshcoreHardware"])
    if pending != PENDING_BOARDS:
        raise ValueError("qualification mapping must cover every pending source port exactly once")
    if retired != RETIRED_NORMAL_PROFILES:
        raise ValueError("qualification mapping must cover every retired normal profile exactly once")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=ROOT / "docs/bootloader_profiles.json")
    parser.add_argument("--hardware-json", type=Path,
                        help="optional JSON list of MeshCore hardware names that must all be classified")
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="ascii"))
    counts = validate_coverage(mapping)
    if args.hardware_json:
        hardware = json.loads(args.hardware_json.read_text(encoding="ascii"))
        if not isinstance(hardware, list) or any(not isinstance(name, str) for name in hardware):
            raise ValueError("--hardware-json must contain a JSON list of hardware names")
        classified = {name for section in ("profiles", "unavailableProfiles")
                      for item in mapping[section] for name in item["meshcoreHardware"]}
        missing = sorted(set(hardware) - classified)
        if missing:
            raise ValueError("unclassified MeshCore hardware: " + ", ".join(missing))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
