#!/usr/bin/env python3
"""Select the board-qualified Arm GNU release for every build frontend."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path(__file__).with_suffix(".json")
POLICY = json.loads(POLICY_PATH.read_text(encoding="ascii"))


def preferred_release(board):
    if not (REPO_ROOT / "src" / "boards" / board / "board.mk").is_file():
        raise ValueError(f"unknown board: {board}")
    return POLICY["board_releases"].get(board, POLICY["default_release"])


def release_version(release):
    match = re.fullmatch(r"(\d+)\.(\d+)\.Rel1", release)
    if match is None:
        raise ValueError(f"invalid Arm GNU release: {release}")
    return tuple(map(int, match.groups()))


def compiler_version(compiler):
    result = subprocess.run([str(compiler), "-dumpfullversion", "-dumpversion"],
                            check=True, capture_output=True, text=True)
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)*", result.stdout.strip())
    if match is None:
        raise RuntimeError(f"cannot determine Arm GNU compiler version: {result.stdout.strip()}")
    return tuple(map(int, match.groups())), result.stdout.strip()


def toolchain_prefix(board, release=None):
    release = release or preferred_release(board)
    version = release_version(release)
    variable = "ARM_GNU_TOOLCHAIN_" + "_".join(map(str, version))
    root = os.environ.get(variable)
    if root:
        directory = Path(root).expanduser()
        if (directory / "bin").is_dir():
            directory /= "bin"
        compiler = shutil.which("arm-none-eabi-gcc", path=str(directory))
    else:
        compiler = shutil.which("arm-none-eabi-gcc")
    if compiler is None:
        compiler = shutil.which("arm-none-eabi-gcc")
    found = "missing"
    if compiler:
        actual, found = compiler_version(compiler)
        if actual == version:
            return re.sub(r"gcc(?:\.exe)?$", "", compiler, flags=re.IGNORECASE)
    raise RuntimeError(
        f"{board} selects Arm GNU {release}; found {found}. "
        f"Set {variable} to its installation directory or put it on PATH "
        f"(Docker: --build-arg ARM_GNU_RELEASE={release.lower()}). "
        "Use an explicit CROSS_COMPILE (Make) or ARM_GNU_PREFIX (CMake) only for compiler qualification."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True)
    parser.add_argument("--field", choices=("release", "prefix"), default="release")
    parser.add_argument("--release", help="explicit release override for compiler qualification")
    args = parser.parse_args()
    try:
        selected = args.release or preferred_release(args.board)
        release_version(selected)
        print(toolchain_prefix(args.board, selected) if args.field == "prefix" else selected)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
