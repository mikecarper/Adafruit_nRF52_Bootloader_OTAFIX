#!/usr/bin/env python3
"""Exercise an application UF2 through a real Linux-mounted boot drive.

This is a destructive hardware-in-the-loop release test. It binds the selected
application serial port to one physical USB path, enters UF2 mode with
MeshCore's ``uf2reset`` command, mounts only the matching block device, copies
and flushes a hash-pinned application UF2, and verifies that the original
application USB identity and an expected CLI reply return.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UF2_BLOCK_SIZE = 512
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_NOFLASH = 0x00000001
UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000
BOOTLOADER_UF2_FAMILY = 0xD663823C
FAT_FILESYSTEMS = {"vfat", "msdos", "exfat"}
APPLICATION_LIMITS = {
    "nrf52": 0x6D000,
    "nrf52833": 0x6D000,
    "nrf52840": 0xEA000,
}
COMPANION_TERMINAL_RESET = (
    b"+++MESHCORE-TERM-STOP\r\n+++MESHCORE-TERM-START\r\n"
)
KERNEL_ERROR_RE = re.compile(
    r"offline device|lost async page write|buffer i/o error|"
    r"fat-fs.*(?:error|unable|failed)|blk_update_request.*i/o error|"
    r"critical medium error|end_request: i/o error",
    re.IGNORECASE,
)


class HilError(RuntimeError):
    """The guarded physical test could not continue or did not pass."""


@dataclass(frozen=True)
class BoardProfile:
    name: str
    boot_vid: str
    boot_pid: str
    volume_label: str
    product_name: str
    board_id: str
    mcu_variant: str
    application_limit: int


@dataclass(frozen=True)
class UsbIdentity:
    node: str
    serial: str
    path_stem: str
    vid: str
    pid: str
    product: str
    interface: str


@dataclass(frozen=True)
class Uf2Image:
    path: str
    sha256: str
    size: int
    blocks: int
    family: str
    first_address: str
    final_address: str


@dataclass(frozen=True)
class BlockDevice:
    node: str
    fstype: str
    label: str
    mountpoints: tuple[str, ...]
    identity: UsbIdentity


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str
    elapsed_seconds: float


def normalize_hex(value: str) -> str:
    return value.strip().lower().removeprefix("0x").zfill(4)


def normalize_serial(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def parse_integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _macro(header: str, name: str, string: bool = False) -> str:
    if string:
        pattern = rf'^\s*#define\s+{re.escape(name)}\s+"([^"]+)"'
    else:
        pattern = rf"^\s*#define\s+{re.escape(name)}\s+(0x[0-9A-Fa-f]+|[0-9]+)"
    match = re.search(pattern, header, re.MULTILINE)
    if match is None:
        raise HilError(f"board header does not define {name}")
    return match.group(1)


def load_board_profile(board: str, root: Path = REPOSITORY_ROOT) -> BoardProfile:
    if re.fullmatch(r"[a-zA-Z0-9_]+", board) is None:
        raise HilError(f"invalid board name: {board!r}")
    header_path = root / "src" / "boards" / board / "board.h"
    if not header_path.is_file():
        raise HilError(f"unknown board or missing board.h: {board}")
    header = header_path.read_text(encoding="ascii")
    cmake_path = header_path.with_name("board.cmake")
    if not cmake_path.is_file():
        raise HilError(f"board has no board.cmake: {board}")
    cmake = cmake_path.read_text(encoding="ascii")
    variant_match = re.search(
        r"^\s*set\(MCU_VARIANT\s+(nrf52|nrf52833|nrf52840)\s*\)",
        cmake,
        re.MULTILINE,
    )
    if variant_match is None:
        raise HilError(f"board.cmake does not define a supported MCU_VARIANT: {board}")
    mcu_variant = variant_match.group(1)
    return BoardProfile(
        name=board,
        boot_vid=normalize_hex(_macro(header, "USB_DESC_VID")),
        boot_pid=normalize_hex(_macro(header, "USB_DESC_UF2_PID")),
        volume_label=_macro(header, "UF2_VOLUME_LABEL", string=True),
        product_name=_macro(header, "UF2_PRODUCT_NAME", string=True),
        board_id=_macro(header, "UF2_BOARD_ID", string=True),
        mcu_variant=mcu_variant,
        application_limit=APPLICATION_LIMITS[mcu_variant],
    )


def inspect_application_uf2(
    path: Path,
    expected_sha256: str,
    expected_family: int,
    expected_base: int,
    application_limit: int,
) -> Uf2Image:
    if not path.is_file() or path.suffix.lower() != ".uf2":
        raise HilError(f"application is not a readable .uf2 file: {path}")
    actual_digest = sha256_file(path)
    expected_digest = expected_sha256.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        raise HilError("--sha256 must contain exactly 64 hexadecimal characters")
    if actual_digest != expected_digest:
        raise HilError(
            f"application SHA-256 mismatch: expected {expected_digest}, "
            f"found {actual_digest}"
        )
    data = path.read_bytes()
    if not data or len(data) % UF2_BLOCK_SIZE:
        raise HilError("application UF2 size is not a nonzero multiple of 512")

    block_numbers: set[int] = set()
    expected_blocks: int | None = None
    ranges: list[tuple[int, int]] = []
    family_ids: set[int] = set()
    for offset in range(0, len(data), UF2_BLOCK_SIZE):
        block = data[offset : offset + UF2_BLOCK_SIZE]
        start0, start1, flags, target, payload_size, number, count, family = (
            struct.unpack_from("<IIIIIIII", block)
        )
        end_magic = struct.unpack_from("<I", block, 508)[0]
        if (start0, start1, end_magic) != (
            UF2_MAGIC_START0,
            UF2_MAGIC_START1,
            UF2_MAGIC_END,
        ):
            raise HilError(f"invalid UF2 magic in block at file offset {offset}")
        if flags & UF2_FLAG_NOFLASH:
            raise HilError(f"NOFLASH block {number} is not valid for this HIL test")
        if not flags & UF2_FLAG_FAMILY_ID_PRESENT:
            raise HilError(f"UF2 block {number} has no family ID")
        if payload_size == 0 or payload_size > 476 or payload_size % 4:
            raise HilError(f"UF2 block {number} has invalid payload size {payload_size}")
        if count == 0 or number >= count:
            raise HilError(f"UF2 block {number} has invalid block count {count}")
        if expected_blocks is None:
            expected_blocks = count
        elif count != expected_blocks:
            raise HilError("UF2 blocks disagree about the total block count")
        if number in block_numbers:
            raise HilError(f"UF2 block number {number} is duplicated")
        block_numbers.add(number)
        family_ids.add(family)
        end = target + payload_size
        if end < target:
            raise HilError(f"UF2 block {number} target range overflows")
        ranges.append((target, end))

    if expected_blocks != len(block_numbers):
        raise HilError(
            f"UF2 is incomplete: header expects {expected_blocks} blocks, "
            f"file contains {len(block_numbers)}"
        )
    if block_numbers != set(range(expected_blocks or 0)):
        raise HilError("UF2 block-number sequence is incomplete")
    if family_ids == {BOOTLOADER_UF2_FAMILY}:
        raise HilError("refusing a bootloader-update UF2; this test requires an application")
    if family_ids != {expected_family}:
        found = ", ".join(f"0x{value:08X}" for value in sorted(family_ids))
        raise HilError(
            f"application UF2 family mismatch: expected 0x{expected_family:08X}, "
            f"found {found}"
        )
    first_address = min(start for start, _ in ranges)
    final_address = max(end for _, end in ranges)
    if first_address != expected_base:
        raise HilError(
            f"application UF2 starts at 0x{first_address:X}, expected 0x{expected_base:X}"
        )
    if any(start < expected_base or end > application_limit for start, end in ranges):
        raise HilError(
            "application UF2 writes outside the explicitly allowed range "
            f"0x{expected_base:X}..0x{application_limit:X}"
        )

    ordered_ranges = sorted(ranges)
    for previous, current in zip(ordered_ranges, ordered_ranges[1:]):
        if current[0] < previous[1]:
            raise HilError("application UF2 contains overlapping target ranges")

    return Uf2Image(
        path=str(path.resolve()),
        sha256=actual_digest,
        size=len(data),
        blocks=len(block_numbers),
        family=f"0x{expected_family:08X}",
        first_address=f"0x{first_address:X}",
        final_address=f"0x{final_address:X}",
    )


def run_command(
    command: list[str], timeout: float = 30, check: bool = True
) -> CommandResult:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        output_parts = []
        for part in (error.stdout, error.stderr):
            if isinstance(part, bytes):
                output_parts.append(part.decode("utf-8", errors="replace"))
            elif part:
                output_parts.append(part)
        raise HilError(
            f"command timed out after {timeout:.0f}s: {' '.join(command)}"
            + (f"\n{''.join(output_parts).strip()}" if output_parts else "")
        ) from error
    elapsed = time.monotonic() - started
    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    command_result = CommandResult(result.returncode, output, elapsed)
    if check and result.returncode != 0:
        raise HilError(
            f"command failed with status {result.returncode}: {' '.join(command)}"
            + (f"\n{output}" if output else "")
        )
    return command_result


def privileged(command: list[str]) -> list[str]:
    if os.geteuid() == 0:
        return command
    sudo = shutil.which("sudo")
    if sudo is None:
        raise HilError("sudo is required for a non-root physical UF2 drive test")
    return [sudo, "-n", *command]


def udev_properties(node: str) -> dict[str, str]:
    result = run_command(
        ["udevadm", "info", "--query=property", f"--name={node}"],
        timeout=10,
    )
    properties: dict[str, str] = {}
    for line in result.output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def usb_path_stem(path: str) -> str:
    marker = "-usb-"
    if marker not in path:
        return path
    prefix, usb_path = path.split(marker, 1)
    interface_path = usb_path.split("-", 1)[0]
    if re.search(r":[0-9]+\.[0-9]+$", interface_path):
        interface_path = interface_path.rsplit(":", 1)[0]
    return f"{prefix}{marker}{interface_path}"


def identity_from_properties(node: str, properties: dict[str, str]) -> UsbIdentity:
    if properties.get("ID_BUS") != "usb":
        raise HilError(f"device is not on USB according to udev: {node}")
    path_stem = usb_path_stem(properties.get("ID_PATH", ""))
    vid = normalize_hex(properties.get("ID_VENDOR_ID", ""))
    pid = normalize_hex(properties.get("ID_MODEL_ID", ""))
    if not path_stem or not vid.strip("0") or not pid.strip("0"):
        raise HilError(f"device lacks stable USB path or VID/PID properties: {node}")
    return UsbIdentity(
        node=str(Path(node).resolve()),
        serial=normalize_serial(properties.get("ID_SERIAL_SHORT", "")),
        path_stem=path_stem,
        vid=vid,
        pid=pid,
        product=properties.get("ID_MODEL_FROM_DATABASE")
        or properties.get("ID_MODEL", ""),
        interface=properties.get("ID_USB_INTERFACE_NUM", "").lower(),
    )


def usb_identity(node: str) -> UsbIdentity:
    return identity_from_properties(node, udev_properties(node))


def same_physical_device(candidate: UsbIdentity, selected: UsbIdentity) -> bool:
    if candidate.path_stem != selected.path_stem:
        return False
    return not (
        selected.serial and candidate.serial and candidate.serial != selected.serial
    )


def _flatten_lsblk(nodes: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for node in nodes:
        yield node
        yield from _flatten_lsblk(node.get("children") or [])


def list_block_records() -> list[dict[str, Any]]:
    result = run_command(
        [
            "lsblk",
            "--json",
            "--paths",
            "--output",
            "NAME,TYPE,FSTYPE,LABEL,MOUNTPOINTS",
        ],
        timeout=10,
    )
    try:
        payload = json.loads(result.output)
    except json.JSONDecodeError as error:
        raise HilError("lsblk returned invalid JSON") from error
    return list(_flatten_lsblk(payload.get("blockdevices") or []))


def matching_block_devices(
    records: Iterable[dict[str, Any]],
    selected: UsbIdentity,
    profile: BoardProfile,
    identity_loader: Callable[[str], UsbIdentity] = usb_identity,
) -> list[BlockDevice]:
    matches: list[BlockDevice] = []
    for record in records:
        node = str(record.get("name") or "")
        fstype = str(record.get("fstype") or "").lower()
        label = str(record.get("label") or "")
        if (
            not node
            or record.get("type") not in {"disk", "part"}
            or fstype not in FAT_FILESYSTEMS
            or label.casefold() != profile.volume_label.casefold()
        ):
            continue
        try:
            identity = identity_loader(node)
        except HilError:
            continue
        if (
            identity.vid != profile.boot_vid
            or identity.pid != profile.boot_pid
            or not same_physical_device(identity, selected)
        ):
            continue
        raw_mountpoints = record.get("mountpoints") or []
        if isinstance(raw_mountpoints, str):
            raw_mountpoints = [raw_mountpoints]
        mountpoints = tuple(str(item) for item in raw_mountpoints if item)
        matches.append(BlockDevice(node, fstype, label, mountpoints, identity))
    return matches


def wait_for_block_device(
    selected: UsbIdentity, profile: BoardProfile, timeout: float
) -> BlockDevice:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = matching_block_devices(list_block_records(), selected, profile)
        if len(matches) > 1:
            names = ", ".join(match.node for match in matches)
            raise HilError(f"ambiguous matching UF2 block devices: {names}")
        if matches:
            return matches[0]
        time.sleep(0.25)
    raise HilError(
        f"matching {profile.boot_vid}:{profile.boot_pid} "
        f"{profile.volume_label!r} UF2 drive did not appear"
    )


def mounted_source(mountpoint: str) -> str:
    result = run_command(
        ["findmnt", "-rn", "-o", "SOURCE", "--target", mountpoint],
        timeout=10,
    )
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise HilError(f"cannot resolve one mount source for {mountpoint}")
    return str(Path(lines[0]).resolve())


def validate_mount(block: BlockDevice, mountpoint: str) -> None:
    source = mounted_source(mountpoint)
    if source != str(Path(block.node).resolve()):
        raise HilError(
            f"UF2 mount source changed: expected {block.node}, found {source}"
        )


def mount_block_device(block: BlockDevice) -> tuple[str, bool]:
    if len(block.mountpoints) > 1:
        raise HilError(
            f"matching UF2 block device has multiple mounts: {block.mountpoints}"
        )
    if block.mountpoints:
        mountpoint = block.mountpoints[0]
        validate_mount(block, mountpoint)
        return mountpoint, False
    mountpoint = tempfile.mkdtemp(prefix="otafix-uf2-hil-")
    try:
        run_command(privileged(["mount", "--", block.node, mountpoint]), timeout=30)
        validate_mount(block, mountpoint)
    except Exception:
        Path(mountpoint).rmdir()
        raise
    return mountpoint, True


def revalidate_block_and_mount(
    selected: UsbIdentity,
    profile: BoardProfile,
    expected: BlockDevice,
    mountpoint: str,
) -> BlockDevice:
    matches = matching_block_devices(list_block_records(), selected, profile)
    if len(matches) != 1:
        raise HilError("selected UF2 block device disappeared or became ambiguous")
    current = matches[0]
    if str(Path(current.node).resolve()) != str(Path(expected.node).resolve()):
        raise HilError(
            f"selected UF2 block device changed from {expected.node} to {current.node}"
        )
    validate_mount(current, mountpoint)
    return current


def copy_and_sync(
    application: Path,
    mountpoint: str,
    timeout: float,
    executor: Callable[..., CommandResult] = run_command,
) -> tuple[CommandResult, CommandResult]:
    copy_result = executor(
        privileged(["cp", "--", str(application), f"{mountpoint}/{application.name}"]),
        timeout=timeout,
    )
    sync_result = executor(
        privileged(["sync", "-f", "--", mountpoint]),
        timeout=timeout,
    )
    return copy_result, sync_result


def list_tty_nodes() -> list[str]:
    nodes: list[str] = []
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        nodes.extend(str(path) for path in Path("/dev").glob(Path(pattern).name))
    return sorted(nodes)


def matching_application_ports(selected: UsbIdentity) -> list[UsbIdentity]:
    matches: list[UsbIdentity] = []
    for node in list_tty_nodes():
        try:
            identity = usb_identity(node)
        except HilError:
            continue
        if (
            identity.vid == selected.vid
            and identity.pid == selected.pid
            and same_physical_device(identity, selected)
            and (not selected.interface or identity.interface == selected.interface)
        ):
            matches.append(identity)
    return matches


def wait_for_application(selected: UsbIdentity, timeout: float) -> UsbIdentity:
    deadline = time.monotonic() + timeout
    stable_node = ""
    stable_samples = 0
    while time.monotonic() < deadline:
        matches = matching_application_ports(selected)
        if len(matches) > 1:
            names = ", ".join(match.node for match in matches)
            raise HilError(f"ambiguous returning application serial ports: {names}")
        if matches:
            current = matches[0]
            if current.node == stable_node:
                stable_samples += 1
            else:
                stable_node = current.node
                stable_samples = 1
            if stable_samples >= 3:
                return current
        else:
            stable_node = ""
            stable_samples = 0
        time.sleep(0.25)
    raise HilError(
        f"application USB identity {selected.vid}:{selected.pid} did not return"
    )


def read_kernel_log() -> list[str]:
    result = run_command(
        # --raw is supported by the Pi's util-linux 2.38.1. "raw" is not a
        # --time-format value there, and --raw cannot be combined with --color.
        # Raw output is uncolored with stable monotonic timestamps.
        privileged(["dmesg", "--raw"]),
        timeout=15,
    )
    return result.output.splitlines()


def kernel_log_delta(before: list[str], after: list[str]) -> list[str]:
    if after[: len(before)] == before:
        return after[len(before) :]
    if not before:
        return after
    for index in range(len(after) - 1, -1, -1):
        if after[index] == before[-1]:
            return after[index + 1 :]
    raise HilError("kernel log rotated during the UF2 test; I/O errors cannot be excluded")


def verify_no_kernel_io_errors(lines: Iterable[str]) -> None:
    failures = [line for line in lines if KERNEL_ERROR_RE.search(line)]
    if failures:
        raise HilError("kernel reported UF2 storage I/O errors:\n" + "\n".join(failures))


def unmount_owned(mountpoint: str, expected_source: str) -> None:
    findmnt = run_command(
        ["findmnt", "-rn", "-o", "SOURCE", "--target", mountpoint],
        timeout=10,
        check=False,
    )
    if findmnt.returncode == 0 and findmnt.output.strip():
        sources = [line.strip() for line in findmnt.output.splitlines() if line.strip()]
        if len(sources) != 1 or str(Path(sources[0]).resolve()) != str(
            Path(expected_source).resolve()
        ):
            raise HilError(f"refusing to unmount changed mount at {mountpoint}")
        run_command(privileged(["umount", "--", mountpoint]), timeout=30)
    Path(mountpoint).rmdir()


def enter_uf2(meshcli: str, port: str) -> CommandResult:
    command = [meshcli, "-q", "-c", "off", "-r", "-s", port, "uf2reset"]
    try:
        result = run_command(command, timeout=20, check=False)
    except HilError as error:
        if "timed out" not in str(error):
            raise
        return CommandResult(-1, str(error), 20.0)
    if "unknown command" in result.output.lower():
        raise HilError("application rejected the uf2reset command")
    return result


def serial_text_command(
    port: str,
    command: str,
    companion: bool,
    disconnect_expected: bool = False,
) -> CommandResult:
    try:
        import serial
    except ImportError as error:
        raise HilError("pyserial is required for Companion terminal mode") from error

    start = b""
    if companion:
        start = COMPANION_TERMINAL_RESET
    started = time.monotonic()
    output = bytearray()
    try:
        with serial.Serial(port, 115200, timeout=0.2, write_timeout=2) as stream:
            stream.dtr = True
            stream.reset_input_buffer()
            if start:
                stream.write(start)
                stream.flush()
                time.sleep(0.7)
                stream.reset_input_buffer()
            stream.write((command + "\r\n").encode("ascii"))
            stream.flush()
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                chunk = stream.read(4096)
                if chunk:
                    output.extend(chunk)
                    deadline = min(deadline + 0.1, time.monotonic() + 0.6)
            # Leave the CLI selected. TERM-STOP explicitly selects Binary;
            # doing that after a text query breaks the next plain-ASCII host.
            # Firmware owns session cleanup when this serial port closes.
    except (OSError, serial.SerialException) as error:
        if not disconnect_expected:
            raise HilError(f"serial terminal command failed: {error}") from error
    return CommandResult(
        0,
        output.decode("utf-8", errors="replace").strip(),
        time.monotonic() - started,
    )


def verify_application_reply(
    meshcli: str,
    port: str,
    command: str,
    expected_reply: str,
    companion: bool = False,
) -> CommandResult:
    deadline = time.monotonic() + 30.0
    last = CommandResult(-1, "no output", 0.0)
    while time.monotonic() < deadline:
        try:
            if companion:
                last = serial_text_command(port, command, companion=True)
            else:
                last = run_command(
                    [meshcli, "-q", "-c", "off", "-r", "-s", port, command],
                    timeout=10,
                    check=False,
                )
        except HilError as error:
            last = CommandResult(-1, str(error), 0.0)
        if expected_reply in last.output:
            return last
        time.sleep(0.5)
    raise HilError(
        f"application reply did not contain {expected_reply!r}:\n{last.output}"
    )


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii")


def check_dependencies(meshcli: str, companion: bool) -> str:
    for command in ("udevadm", "lsblk", "findmnt", "mount", "umount", "cp", "sync", "dmesg"):
        if shutil.which(command) is None:
            raise HilError(f"required Linux command is not installed: {command}")
    if companion:
        try:
            import serial  # noqa: F401
        except ImportError as error:
            raise HilError("pyserial is required for Companion terminal mode") from error
        return meshcli
    resolved = shutil.which(meshcli)
    if resolved is None:
        candidate = Path(meshcli).expanduser()
        if not candidate.is_file():
            raise HilError(f"meshcli is not installed or executable: {meshcli}")
        resolved = str(candidate.resolve())
    return resolved


def check_noninteractive_privilege() -> None:
    if os.geteuid() != 0:
        run_command(privileged(["true"]), timeout=10)


def modem_manager_is_active() -> bool:
    if shutil.which("systemctl") is None:
        return False
    result = run_command(
        ["systemctl", "is-active", "--quiet", "ModemManager"],
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def run_hil(
    args: argparse.Namespace, report: dict[str, Any] | None = None
) -> dict[str, Any]:
    started = time.monotonic()
    profile = load_board_profile(args.board)
    image = inspect_application_uf2(
        args.application,
        args.sha256,
        args.family,
        args.app_base,
        profile.application_limit,
    )
    meshcli = check_dependencies(args.meshcli, args.companion_terminal)
    check_noninteractive_privilege()
    selected = usb_identity(str(args.port))
    if selected.serial != normalize_serial(args.serial):
        raise HilError(
            f"selected port serial is {selected.serial or 'missing'}, "
            f"expected {normalize_serial(args.serial)}"
        )
    if modem_manager_is_active():
        raise HilError("ModemManager is active; stop it before the physical UF2 test")

    if report is None:
        report = {}
    report.update({
        "status": "PREFLIGHT",
        "board": asdict(profile),
        "application": asdict(image),
        "selected_application_usb": asdict(selected),
        "kernel_log_checked": not args.skip_kernel_log,
        "terminal_mode": "companion" if args.companion_terminal else "repeater",
    })
    before_reply = verify_application_reply(
        meshcli,
        selected.node,
        args.verify_command,
        args.expect_before_reply,
        args.companion_terminal,
    )
    report["application_reply_before"] = asdict(before_reply)
    if not args.execute:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return report

    before_log = [] if args.skip_kernel_log else read_kernel_log()
    mountpoint: str | None = None
    owned_mount = False
    block: BlockDevice | None = None
    try:
        if args.companion_terminal:
            entry = serial_text_command(
                selected.node,
                "uf2reset",
                companion=True,
                disconnect_expected=True,
            )
        else:
            entry = enter_uf2(meshcli, selected.node)
        report["uf2reset"] = asdict(entry)
        block = wait_for_block_device(selected, profile, args.enumeration_timeout)
        report["bootloader_block"] = asdict(block)
        mountpoint, owned_mount = mount_block_device(block)
        report["mountpoint"] = mountpoint
        report["mount_owned_by_test"] = owned_mount

        revalidate_block_and_mount(selected, profile, block, mountpoint)
        copy_result, sync_result = copy_and_sync(
            args.application, mountpoint, args.copy_timeout
        )
        report["copy"] = asdict(copy_result)
        report["sync"] = asdict(sync_result)

        if owned_mount:
            # Finish FAT metadata while the bootloader is still in its idle
            # completion window. Waiting for application USB first guarantees
            # that a later umount runs against a disconnected block device.
            unmount_owned(mountpoint, block.node)
            owned_mount = False
            report["unmounted_before_application_return"] = True

        returned = wait_for_application(selected, args.return_timeout)
        report["returned_application_usb"] = asdict(returned)
        reply = verify_application_reply(
            meshcli,
            returned.node,
            args.verify_command,
            args.expect_reply,
            args.companion_terminal,
        )
        report["application_reply"] = asdict(reply)

        if not args.skip_kernel_log:
            new_log = kernel_log_delta(before_log, read_kernel_log())
            report["kernel_log_delta"] = new_log
            verify_no_kernel_io_errors(new_log)
        report["status"] = "PASS"
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return report
    finally:
        if owned_mount and mountpoint is not None and block is not None:
            unmount_owned(mountpoint, block.node)


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a hash-pinned application UF2 through the exact selected "
            "board's real Linux-mounted boot drive and verify app return."
        )
    )
    parser.add_argument("--board", required=True, help="src/boards directory name")
    parser.add_argument("--port", required=True, type=Path, help="application serial port")
    parser.add_argument("--serial", required=True, help="exact USB serial identity")
    parser.add_argument("--application", required=True, type=Path)
    parser.add_argument("--sha256", required=True, help="exact application UF2 digest")
    parser.add_argument("--family", required=True, type=parse_integer)
    parser.add_argument("--app-base", required=True, type=parse_integer)
    parser.add_argument(
        "--expect-before-reply", required=True, help="literal current CLI text"
    )
    parser.add_argument("--expect-reply", required=True, help="literal expected CLI text")
    parser.add_argument("--verify-command", default="ver")
    parser.add_argument("--meshcli", default="meshcli")
    parser.add_argument(
        "--companion-terminal",
        action="store_true",
        help="wrap serial commands in the Full Companion terminal tokens",
    )
    parser.add_argument("--enumeration-timeout", type=float, default=60.0)
    parser.add_argument("--copy-timeout", type=float, default=360.0)
    parser.add_argument("--return-timeout", type=float, default=60.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--skip-kernel-log",
        action="store_true",
        help="skip dmesg I/O-error gate (does not qualify a release)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the destructive drive copy; otherwise run preflight only",
    )
    return parser


def main() -> int:
    args = argument_parser().parse_args()
    report: dict[str, Any] = {"status": "FAIL"}
    try:
        report = run_hil(args, report)
    except (HilError, OSError) as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
        write_report(args.report, report)
        print(f"FAIL: {error}", file=sys.stderr)
        if args.execute:
            print(
                "The application may now be invalid. Keep the board in recovery "
                "and restore the hash-pinned application through a known-good path.",
                file=sys.stderr,
            )
        return 1
    write_report(args.report, report)
    if report["status"] == "PASS":
        print(
            "PASS: mounted-drive application UF2 copy, flush, application return, "
            "CLI reply, and kernel I/O-error gate"
        )
    else:
        print(
            "PREFLIGHT PASS: artifact and exact USB identity validated; "
            "no device write was performed"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
