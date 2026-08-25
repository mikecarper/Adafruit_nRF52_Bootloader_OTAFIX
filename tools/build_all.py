#!/usr/bin/env python3
"""Build every board with a bounded amount of parallelism."""

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


SUCCEEDED = "\033[32msucceeded\033[0m"
FAILED = "\033[31mfailed\033[0m"
BUILD_FORMAT = "| {:32} | {:18} | {:7} | {:7} | {:7} |"
BUILD_SEPARATOR = "-" * 82
REPO_ROOT = Path(__file__).resolve().parents[1]


def packed_version(value):
    try:
        parsed = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a packed integer such as 0x02040302") from error

    channel = parsed & 0xFF
    if parsed <= 0 or parsed >= 0xFFFFFFFF or channel == 0:
        raise argparse.ArgumentTypeError("packed version and release channel must be nonzero")
    return f"0x{parsed:08X}"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, os.cpu_count() or 1),
        help="number of boards to build concurrently (default: CPU count)",
    )
    parser.add_argument(
        "--make-jobs",
        type=int,
        default=1,
        help="parallel jobs inside each board build (default: 1)",
    )
    parser.add_argument(
        "--test-version",
        type=packed_version,
        help="packed test-only version for a dirty qualification tree",
    )
    parser.add_argument(
        "--keep-build",
        action="store_true",
        help="keep existing per-board build directories",
    )
    args = parser.parse_args()
    if args.jobs < 1 or args.make_jobs < 1:
        parser.error("--jobs and --make-jobs must be positive")
    return args


def require_toolchain():
    compiler = shutil.which("arm-none-eabi-gcc")
    size_tool = shutil.which("arm-none-eabi-size")
    if compiler is None or size_tool is None:
        raise RuntimeError("Arm GNU Toolchain is missing from PATH")

    result = subprocess.run(
        [compiler, "-dumpfullversion", "-dumpversion"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    match = re.match(r"(\d+)\.(\d+)", result.stdout.strip())
    if match is None or tuple(map(int, match.groups())) < (14, 2):
        raise RuntimeError(
            f"Arm GNU Toolchain 14.2.Rel1 or newer is required; found {result.stdout.strip()}"
        )
    return size_tool, result.stdout.strip()


def image_sizes(size_tool, image):
    result = subprocess.run(
        [size_tool, str(image)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    fields = result.stdout.splitlines()[1].split()
    text_size, data_size, bss_size = (int(value) for value in fields[:3])
    return text_size + data_size, data_size + bss_size


def build_board(board, make_jobs, test_version, size_tool):
    command = ["make", f"-j{make_jobs}", f"BOARD={board}"]
    if test_version is not None:
        command.extend(
            [
                "MOTA_BOOTLOADER_TEST_BUILD=1",
                f"MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE={test_version}",
            ]
        )
    command.append("all")

    start_time = time.monotonic()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    duration = time.monotonic() - start_time

    if result.returncode != 0:
        return board, False, duration, "-", "-", result.stdout

    images = sorted((REPO_ROOT / "_build" / f"build-{board}").glob("*.out"))
    if len(images) != 1:
        detail = f"expected one .out image, found {len(images)}\n{result.stdout}"
        return board, False, duration, "-", "-", detail

    try:
        flash_size, sram_size = image_sizes(size_tool, images[0])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return board, False, duration, "-", "-", f"size failed: {error}\n{result.stdout}"

    return board, True, duration, flash_size, sram_size, ""


def main():
    args = parse_args()
    try:
        size_tool, compiler_version = require_toolchain()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    build_root = REPO_ROOT / "_build"
    if not args.keep_build:
        shutil.rmtree(build_root, ignore_errors=True)

    boards = sorted(entry.name for entry in (REPO_ROOT / "src" / "boards").iterdir() if entry.is_dir())
    worker_count = min(args.jobs, len(boards))

    print(f"Arm GNU Toolchain {compiler_version}; {worker_count} board workers")
    if args.test_version is not None:
        print(f"Qualification build version: {args.test_version} (test-only)")
    print(BUILD_SEPARATOR)
    print(BUILD_FORMAT.format("Board", "\033[39mResult\033[0m", "Time", "Flash", "SRAM"))
    print(BUILD_SEPARATOR)

    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                build_board, board, args.make_jobs, args.test_version, size_tool
            ): board
            for board in boards
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            board, succeeded, duration, flash_size, sram_size, detail = result
            print(
                BUILD_FORMAT.format(
                    board,
                    SUCCEEDED if succeeded else FAILED,
                    f"{duration:.2f}s",
                    flash_size,
                    sram_size,
                ),
                flush=True,
            )
            if detail:
                print(detail, flush=True)

    success_count = sum(1 for result in results if result[1])
    fail_count = len(boards) - success_count
    duration = time.monotonic() - started
    print(BUILD_SEPARATOR)
    print(
        f"Build Summary: {success_count} {SUCCEEDED}, {fail_count} {FAILED} "
        f"and took {duration:.2f}s"
    )
    print(BUILD_SEPARATOR)
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
