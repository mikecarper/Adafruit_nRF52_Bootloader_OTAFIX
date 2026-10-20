#!/usr/bin/env python3
"""Measure experimental dual-BLE fit without relaxing the linker envelope.

This is a CMake-only, compile/link size experiment, not release or hardware
qualification. Failed links retain their map/log but must never be flashed.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 40784


def measure(board, mode, output, options="", trial=None, sharing="all"):
    folder = output / mode / board
    folder.mkdir(parents=True, exist_ok=True)
    command = [
        "cmake", "-S", str(ROOT), "-B", str(folder), "-DBOARD=" + board,
        "-DMOTA_BOOTLOADER_TEST_BUILD=ON",
        "-DMOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040B80",
        "-DDUAL_BLE_DFU_TEST=" + ("ON" if mode == "dual" else "OFF"),
        "-DDUAL_BLE_FIT_FLAGS=" + options,
        "-DCMAKE_EXE_LINKER_FLAGS=-Wl,--print-memory-usage -Wl,--gc-sections -Wl,-Map=fit.map",
    ]
    for feature in ("characteristics", "services", "notifications", "information", "stack_config"):
        enabled = sharing == "all" or feature in sharing.split("+")
        command.append("-DDUAL_BLE_SHARE_" + feature.upper() + "=" + ("ON" if enabled else "OFF"))
    configure = subprocess.run(command, text=True, capture_output=True)
    log = configure.stdout + configure.stderr
    result = configure
    if configure.returncode == 0:
        result = subprocess.run(["cmake", "--build", str(folder), "-j2"],
                                text=True, capture_output=True)
        log += result.stdout + result.stderr
    (folder / "build.log").write_text(log, encoding="ascii", errors="backslashreplace")
    map_file = folder / "fit.map"
    symbols = map_file.read_text(errors="replace") if map_file.exists() else ""
    match = re.search(r"^\s*0x([0-9a-fA-F]+)\s+TotalFlashUsed\s*=", symbols, re.M)
    used = int(match[1], 16) if match else None
    fits = result.returncode == 0 and used is not None and used <= LIMIT
    overflow = result.returncode != 0 and used is not None and used > LIMIT
    row = dict(board=board, mode=mode, status="fits" if fits else "overflow" if overflow else "error",
               flash=used, free=LIMIT - used if used is not None else None,
               linker_limit=LIMIT, returncode=result.returncode, sharing=sharing)
    if options:
        row["extra_flags"] = options
    if trial:
        row["trial"] = trial
    print(json.dumps(row), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--boards", nargs="+")
    parser.add_argument("--mode", choices=("dual", "legacy", "both"), default="both")
    parser.add_argument("--tuning", action="store_true", help="try size-only compiler settings on dual builds")
    parser.add_argument("--fit-flags", default="", help="one additional compiler/linker setting, dual builds only")
    parser.add_argument("--sharing", default="all",
                        choices=("none", "characteristics", "services", "notifications", "all",
                                 "characteristics+services", "characteristics+notifications", "services+notifications",
                                 "characteristics+notifications+information", "information"))
    parser.add_argument("--sharing-sweep", action="store_true", help="measure every combination of shared helpers")
    parser.add_argument("--fine-tuning", action="store_true", help="vary the size-policy switches individually")
    parser.add_argument("--inline-tuning", action="store_true", help="test outlining and inlining on the shared profile")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    boards = sorted(path.name for path in (ROOT / "src/boards").iterdir()
                    if (path / "board.cmake").is_file())
    if args.boards:
        if not set(args.boards) <= set(boards):
            parser.error("unknown board")
        boards = sorted(set(args.boards))
    modes = ("legacy", "dual") if args.mode == "both" else (args.mode,)
    trials = {None: ""}
    sharing_modes = (args.sharing,)
    if args.sharing_sweep:
        if args.tuning:
            parser.error("run compiler tuning and sharing sweeps separately")
        modes = ("dual",)
        sharing_modes = ("none", "characteristics", "services", "notifications", "all",
                         "characteristics+services", "characteristics+notifications", "services+notifications",
                         "characteristics+notifications+information", "information")
    if args.fit_flags:
        modes = ("dual",)
        trials = {None: args.fit_flags}
    if args.tuning:
        modes = ("dual",)
        trials = {
            "no-single-inline": "-fno-inline-functions-called-once",
            "no-small-inline": "-fno-inline-small-functions",
            "small-inline": "--param=max-inline-insns-auto=6 --param=max-inline-insns-single=20 --param=inline-unit-growth=0",
            "no-ipa-sra": "-fno-ipa-sra",
            "no-ipa-clone": "-fno-ipa-cp-clone",
            "no-early-inline": "-fno-early-inlining",
            "outline-all": "-fno-inline-small-functions -fno-inline-functions-called-once -fno-ipa-cp-clone",
            "rak-size-policy": "-fno-schedule-insns -fno-schedule-insns2 -fno-code-hoisting -fno-tree-ter "
                               "-fno-tree-dominator-opts -fno-tree-tail-merge -fno-optimize-sibling-calls "
                               "-fno-if-conversion -mbranch-cost=3 -fno-tree-loop-im -fno-early-inlining",
        }
    if args.fine_tuning:
        if args.tuning or args.sharing_sweep:
            parser.error("run fine tuning separately from other sweeps")
        modes = ("dual",)
        base_flags = ("-fno-schedule-insns -fno-schedule-insns2 -fno-code-hoisting -fno-tree-ter "
                      "-fno-tree-dominator-opts -fno-tree-tail-merge -fno-optimize-sibling-calls "
                      "-fno-if-conversion -mbranch-cost=3 -fno-tree-loop-im -fno-early-inlining").split()
        trials = {"restore-" + flag.removeprefix("-fno-").removeprefix("-").replace("=", "-"):
                  " ".join(item for item in base_flags if item != flag) for flag in base_flags}
        for cost in (1, 2, 4):
            trials[f"branch-cost-{cost}"] = " ".join(base_flags).replace("-mbranch-cost=3", f"-mbranch-cost={cost}")
        for flag in ("-fno-caller-saves", "-fno-tree-sra", "-fno-cse-follow-jumps", "-fno-ipa-cp"):
            trials[flag.removeprefix("-fno-")] = " ".join(base_flags) + " " + flag
        for suffix, restore in (("early", ("-fno-early-inlining",)),
                                ("tail", ("-fno-tree-tail-merge",)),
                                ("early-tail", ("-fno-early-inlining", "-fno-tree-tail-merge"))):
            trials["caller-saves-restore-" + suffix] = " ".join(flag for flag in base_flags if flag not in restore) + " -fno-caller-saves"
        trials["small-inline"] = " ".join(base_flags) + " --param=max-inline-insns-auto=6 --param=max-inline-insns-single=20 --param=inline-unit-growth=0"
    if args.inline_tuning:
        if args.tuning or args.fine_tuning or args.sharing_sweep:
            parser.error("run inlining tuning separately from other sweeps")
        modes = ("dual",)
        base = ("-fno-schedule-insns -fno-schedule-insns2 -fno-code-hoisting -fno-tree-ter "
                "-fno-tree-dominator-opts -fno-tree-tail-merge -fno-optimize-sibling-calls "
                "-fno-if-conversion -mbranch-cost=3 -fno-tree-loop-im -fno-caller-saves")
        trials = {flag.removeprefix("-fno-"): base + " " + flag for flag in (
            "-fno-inline-small-functions", "-fno-inline-functions-called-once", "-fno-ipa-sra",
            "-fno-ipa-cp-clone", "-fno-tree-switch-conversion", "-fno-crossjumping", "-fno-peephole2")}
        for auto, single, growth in ((4, 24, 0), (8, 40, 5), (16, 60, 10), (32, 100, 20),
                                     (2, 12, 0), (6, 20, 0)):
            trials[f"inline-{auto}-{single}-{growth}"] = (base + f" --param=max-inline-insns-auto={auto}"
                f" --param=max-inline-insns-single={single} --param=inline-unit-growth={growth}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1792483200")
    rows = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(measure, board, mode,
                               (output / sharing if args.sharing_sweep else output) / trial
                               if trial else output / sharing if args.sharing_sweep else output,
                               options, trial, sharing)
                   for board in boards for mode in modes for trial, options in trials.items() for sharing in sharing_modes]
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["board"], row["mode"]))
    (output / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="ascii")
    return int(any(row["status"] == "error" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
