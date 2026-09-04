#!/usr/bin/env python3
"""Identity-gated Nordic SDK 11 Legacy BLE DFU client for OTAFIX.

The client deliberately supports only the two package shapes used by this
project:

* an application-only Nordic Legacy DFU ZIP; or
* a combined SoftDevice + 40 KiB OTAFIX bootloader recovery ZIP.

It is fail-closed.  The ZIP's SHA-256, advertised address and name, advertised
and connected DFU service, and required DIS model must all match before START
DFU.  Packet receipt notifications are cumulative and must equal the
exact byte count sent.  A missing, malformed, short, or ahead receipt aborts
the transfer rather than guessing whether the target accepted data.

PRN is also the write window.  At the universally compatible 20-byte packet
size it starts at eight writes and may move to 16 and then 32 only after
consecutive exact, timely receipts.  Larger packets use smaller levels bounded
by the target's eight-packet lazy-erase FIFO.  Timing decisions include a
bounded receipt latency allowance and the actual payload bytes acknowledged,
so healthy high-MTU writes are not compared with a 20-byte per-packet limit. A
window moves one step down after one materially slow exact receipt. Changes
therefore happen only at a proven synchronization boundary.

Bleak is imported only by :func:`run`, so the package parser and protocol can
be tested on a host with no BLE stack installed.
"""

from __future__ import annotations

import argparse
import asyncio
import binascii
import hashlib
import hmac
import io
import inspect
import json
import math
import signal
import stat
import struct
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Protocol


DFU_SERVICE = "00001530-1212-efde-1523-785feabcd123"
DFU_CONTROL = "00001531-1212-efde-1523-785feabcd123"
DFU_PACKET = "00001532-1212-efde-1523-785feabcd123"
DIS_MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"

OP_START = 0x01
OP_INITIALIZE = 0x02
OP_RECEIVE = 0x03
OP_VALIDATE = 0x04
OP_ACTIVATE_RESET = 0x05
OP_PRN_REQUEST = 0x08
OP_RESPONSE = 0x10
OP_PRN = 0x11

MODE_SD_BOOTLOADER = 0x03
MODE_APPLICATION = 0x04

RESULT_SUCCESS = 0x01
RESULT_NAMES = {
    0x01: "success",
    0x02: "invalid state",
    0x03: "not supported",
    0x04: "data size exceeds limit",
    0x05: "CRC error",
    0x06: "operation failed",
}

MAX_PACKAGE_BYTES = 4 * 1024 * 1024
MAX_FIRMWARE_BYTES = 1024 * 1024
# SDK11's dual- and single-bank implementations both have a 128-byte init
# packet buffer.  Reject an incompatible package locally, before START DFU can
# erase or prepare any flash.
MAX_INIT_BYTES = 128
MAX_MANIFEST_BYTES = 64 * 1024
OTAFIX_BOOTLOADER_BYTES = 0xA000
ATT_MTU_MIN = 23
ATT_MTU_MAX = 517
ATT_WRITE_COMMAND_OVERHEAD = 3
ATT_WRITE_COMMAND_MAX = ATT_MTU_MAX - ATT_WRITE_COMMAND_OVERHEAD


class DfuError(RuntimeError):
    """A validation or protocol failure for which continuing is unsafe."""


class WriteCapabilityUnavailable(DfuError):
    """BlueZ could not provide a trustworthy write capability observation."""


@dataclass(frozen=True)
class Package:
    kind: str
    mode: int
    firmware: bytes
    init_packet: bytes
    softdevice_size: int
    bootloader_size: int
    application_size: int
    sha256: str


def _require_uint(value: Any, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DfuError(f"{label} must be an integer")
    if value < 0 or value > maximum:
        raise DfuError(f"{label} is outside 0..{maximum}")
    return value


def _safe_root_member(name: Any, label: str) -> str:
    if not isinstance(name, str) or not name:
        raise DfuError(f"{label} must name a ZIP member")
    if "\\" in name or "\x00" in name:
        raise DfuError(f"unsafe {label}: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise DfuError(f"unsafe {label}: {name!r}")
    return name


def _validate_zip_directory(infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    if not infos or len(infos) > 16:
        raise DfuError("DFU ZIP has an invalid member count")
    result: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    total_size = 0
    for info in infos:
        name = _safe_root_member(info.filename, "archive member")
        if info.orig_filename != info.filename:
            raise DfuError(f"archive member contains an embedded NUL: {info.orig_filename!r}")
        if info.is_dir() or info.flag_bits & 0x01:
            raise DfuError(f"unsupported directory or encrypted member: {name!r}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise DfuError(f"symbolic-link archive member is not allowed: {name!r}")
        folded_name = name.casefold()
        if name in result or folded_name in folded:
            raise DfuError(f"duplicate or case-colliding archive member: {name!r}")
        if info.file_size < 0 or info.file_size > MAX_FIRMWARE_BYTES:
            raise DfuError(f"archive member has an unsafe size: {name!r}")
        total_size += info.file_size
        if total_size > MAX_PACKAGE_BYTES:
            raise DfuError("DFU ZIP expands beyond the safety limit")
        result[name] = info
        folded.add(folded_name)
    return result


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DfuError(f"DFU manifest has duplicate JSON key {key!r}")
        result[key] = value
    return result


def _hex_field(value: Any, label: str, size: int) -> bytes:
    if not isinstance(value, str) or len(value) != size * 2:
        raise DfuError(f"{label} must be exactly {size * 2} hexadecimal digits")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise DfuError(f"{label} is not hexadecimal") from exc


def _parse_init_packet(
    packet: bytes, metadata: Any, firmware: bytes, dfu_version: float
) -> None:
    if not isinstance(metadata, dict):
        raise DfuError("manifest init_packet_data must be an object")
    common = {
        "application_version",
        "device_revision",
        "device_type",
        "softdevice_req",
    }
    unsigned_keys = common | {"firmware_crc16"}
    signed_keys = common | {
        "ext_packet_id",
        "firmware_hash",
        "firmware_length",
        "init_packet_ecds",
    }
    if set(metadata) == unsigned_keys and dfu_version == 0.5:
        signed = False
    elif set(metadata) == signed_keys and dfu_version == 0.8:
        signed = True
    else:
        raise DfuError("manifest init_packet_data has missing or unknown fields")
    if len(packet) < 12 or len(packet) > MAX_INIT_BYTES:
        raise DfuError("Legacy DFU init packet has an invalid length")

    device_type, device_revision, app_version, sd_count = struct.unpack_from(
        "<HHIH", packet, 0
    )
    base_length = 10 + 2 * sd_count
    expected_length = base_length + (104 if signed else 2)
    if sd_count == 0 or len(packet) != expected_length:
        raise DfuError("Legacy DFU init packet has invalid SoftDevice requirements")
    softdevice_req = list(struct.unpack_from(f"<{sd_count}H", packet, 10))

    manifest_values = {
        "device_type": device_type,
        "device_revision": device_revision,
        "application_version": app_version,
    }
    for key, parsed in manifest_values.items():
        if _require_uint(metadata.get(key), f"init_packet_data.{key}", 0xFFFFFFFF) != parsed:
            raise DfuError(f"manifest and init packet disagree about {key}")
    manifest_sd = metadata.get("softdevice_req")
    if not isinstance(manifest_sd, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in manifest_sd
    ):
        raise DfuError("init_packet_data.softdevice_req must be an integer list")
    if manifest_sd != softdevice_req:
        raise DfuError("manifest and init packet disagree about softdevice_req")

    if not signed:
        firmware_crc = struct.unpack_from("<H", packet, base_length)[0]
        expected_crc = binascii.crc_hqx(firmware, 0xFFFF)
        if firmware_crc != expected_crc:
            raise DfuError(
                f"init packet firmware CRC mismatch: 0x{firmware_crc:04x} != "
                f"0x{expected_crc:04x}"
            )
        if _require_uint(
            metadata.get("firmware_crc16"),
            "init_packet_data.firmware_crc16",
            0xFFFF,
        ) != firmware_crc:
            raise DfuError("manifest and init packet disagree about firmware_crc16")
        return

    ext_id, firmware_length = struct.unpack_from("<II", packet, base_length)
    firmware_hash = packet[base_length + 8 : base_length + 40]
    signature = packet[base_length + 40 : base_length + 104]
    if ext_id != 2 or firmware_length != len(firmware):
        raise DfuError("signed init packet has the wrong identifier or firmware length")
    if firmware_hash != hashlib.sha256(firmware).digest():
        raise DfuError("signed init packet firmware hash does not match the image")
    if _require_uint(
        metadata.get("ext_packet_id"), "init_packet_data.ext_packet_id", 0xFFFFFFFF
    ) != ext_id or _require_uint(
        metadata.get("firmware_length"),
        "init_packet_data.firmware_length",
        MAX_FIRMWARE_BYTES,
    ) != firmware_length:
        raise DfuError("manifest and signed init packet disagree")
    if _hex_field(
        metadata.get("firmware_hash"), "init_packet_data.firmware_hash", 32
    ) != firmware_hash or _hex_field(
        metadata.get("init_packet_ecds"), "init_packet_data.init_packet_ecds", 64
    ) != signature:
        raise DfuError("manifest and signed init packet hash/signature disagree")


def read_package(path: Path, expected_sha256: str) -> Package:
    """Read and fully validate one exact Nordic Legacy DFU ZIP."""

    expected = expected_sha256.casefold()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise DfuError("expected package SHA-256 must be exactly 64 hexadecimal digits")
    try:
        package_size = path.stat().st_size
    except OSError as exc:
        raise DfuError(f"cannot stat DFU package: {exc}") from exc
    if package_size <= 0 or package_size > MAX_PACKAGE_BYTES:
        raise DfuError("DFU package file has an unsafe size")
    try:
        blob = path.read_bytes()
    except OSError as exc:
        raise DfuError(f"cannot read DFU package: {exc}") from exc
    if len(blob) != package_size or len(blob) > MAX_PACKAGE_BYTES:
        raise DfuError("DFU package changed size while it was being read")
    digest = hashlib.sha256(blob).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise DfuError(
            f"package SHA-256 mismatch: got {digest}, expected {expected}"
        )

    try:
        # Parse the exact bytes whose digest was checked.  Reopening `path`
        # here would create a hash/open race in which a replaced file could be
        # transferred even though only the old bytes were authenticated.
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            directory = _validate_zip_directory(archive.infolist())
            manifest_info = directory.get("manifest.json")
            if manifest_info is None or manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise DfuError("DFU ZIP has no safe manifest.json")
            try:
                manifest_text = archive.read(manifest_info).decode("utf-8", "strict")
                root = json.loads(
                    manifest_text,
                    object_pairs_hook=_strict_json_object,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
                raise DfuError("DFU ZIP has no valid UTF-8 manifest.json") from exc
            if not isinstance(root, dict) or set(root) != {"manifest"}:
                raise DfuError("DFU manifest has an unexpected top-level shape")
            entries = root["manifest"]
            if not isinstance(entries, dict):
                raise DfuError("DFU manifest.manifest must be an object")

            supported = [
                key for key in ("application", "softdevice_bootloader") if key in entries
            ]
            unsupported = {
                key for key in ("softdevice", "bootloader") if key in entries
            }
            if len(supported) != 1 or unsupported:
                raise DfuError(
                    "package must contain exactly one application or "
                    "softdevice_bootloader image"
                )
            kind = supported[0]
            dfu_version = entries.get("dfu_version")
            if set(entries) != {"dfu_version", kind} or dfu_version not in (0.5, 0.8):
                raise DfuError("DFU manifest has missing, unknown, or unsupported entries")
            item = entries[kind]
            if not isinstance(item, dict):
                raise DfuError(f"manifest {kind} entry must be an object")

            common_keys = {"bin_file", "dat_file", "init_packet_data"}
            required_keys = (
                common_keys | {"sd_size", "bl_size"}
                if kind == "softdevice_bootloader"
                else common_keys
            )
            if set(item) != required_keys:
                raise DfuError(f"manifest {kind} entry has missing or unknown fields")
            bin_name = _safe_root_member(item.get("bin_file"), "bin_file")
            dat_name = _safe_root_member(item.get("dat_file"), "dat_file")
            if bin_name == dat_name or bin_name == "manifest.json" or dat_name == "manifest.json":
                raise DfuError("manifest members must be distinct")
            if set(directory) != {"manifest.json", bin_name, dat_name}:
                raise DfuError("DFU ZIP contains unreferenced or missing members")
            if directory[bin_name].file_size <= 0 or directory[bin_name].file_size > MAX_FIRMWARE_BYTES:
                raise DfuError("firmware member has an invalid size")
            if directory[dat_name].file_size <= 0 or directory[dat_name].file_size > MAX_INIT_BYTES:
                raise DfuError("init-packet member has an invalid size")
            try:
                firmware = archive.read(directory[bin_name])
                init_packet = archive.read(directory[dat_name])
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise DfuError("could not safely extract DFU package members") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise DfuError(f"invalid DFU ZIP: {exc}") from exc

    if len(firmware) % 4:
        raise DfuError("firmware image length must be word aligned")
    _parse_init_packet(init_packet, item["init_packet_data"], firmware, dfu_version)

    if kind == "application":
        sd_size = 0
        bl_size = 0
        app_size = len(firmware)
        mode = MODE_APPLICATION
    else:
        sd_size = _require_uint(item["sd_size"], "sd_size", MAX_FIRMWARE_BYTES)
        bl_size = _require_uint(item["bl_size"], "bl_size", MAX_FIRMWARE_BYTES)
        if sd_size <= 0 or bl_size != OTAFIX_BOOTLOADER_BYTES:
            raise DfuError(
                f"unexpected SD/bootloader sizes: {sd_size} / {bl_size}; "
                "expected a SoftDevice and 40 KiB OTAFIX bootloader"
            )
        if sd_size + bl_size != len(firmware):
            raise DfuError("combined manifest sizes do not equal firmware length")
        app_size = 0
        mode = MODE_SD_BOOTLOADER

    return Package(
        kind=kind,
        mode=mode,
        firmware=firmware,
        init_packet=init_packet,
        softdevice_size=sd_size,
        bootloader_size=bl_size,
        application_size=app_size,
        sha256=digest,
    )


def normalize_uuid(value: str) -> str:
    return value.replace("-", "").casefold()


def select_advertisement(
    discovered: dict[Any, tuple[Any, Any]],
    address: str,
    expected_name: str,
) -> tuple[Any, Any]:
    """Select exactly one advertisement matching all pre-connection gates."""

    matches = [
        (device, advertisement)
        for device, advertisement in discovered.values()
        if str(device.address).casefold() == address.casefold()
    ]
    if len(matches) != 1:
        raise DfuError(
            f"expected exactly one advertisement for {address}, found {len(matches)}"
        )
    device, advertisement = matches[0]
    if advertisement.local_name != expected_name:
        raise DfuError(
            f"advertised-name mismatch at {device.address}: got "
            f"{advertisement.local_name!r}, expected {expected_name!r}"
        )
    advertised_services = {
        normalize_uuid(str(uuid)) for uuid in (advertisement.service_uuids or [])
    }
    if normalize_uuid(DFU_SERVICE) not in advertised_services:
        raise DfuError(
            f"{device.address} does not advertise the Nordic Legacy DFU service"
        )
    return device, advertisement


def select_packet_size(
    *,
    high_mtu_requested: bool,
    mtu_acquired: bool,
    negotiated_mtu: int,
    max_write_without_response: int,
) -> int:
    """Return a proven safe DFU packet size, or the 20-byte fallback.

    BlueZ exposes the acquired ATT MTU directly and the characteristic's
    maximum write as a separately cached view of that MTU.  Both observations
    must be consistent before selecting a large packet.  The known OTAFIX
    target caps its packet characteristic at 244 bytes and requires large data
    writes to be word aligned.
    """

    if not high_mtu_requested or not mtu_acquired:
        return 20
    if negotiated_mtu <= 23 or max_write_without_response <= 20:
        return 20
    candidate = min(negotiated_mtu - 3, max_write_without_response, 244)
    candidate -= candidate % 4
    return candidate if candidate > 20 else 20


class Transport(Protocol):
    async def write_control(self, payload: bytes) -> None: ...

    async def write_packet(self, payload: bytes) -> None: ...


@dataclass(frozen=True)
class _Response:
    opcode: int
    result: int


@dataclass(frozen=True)
class _Receipt:
    byte_count: int


@dataclass(frozen=True)
class _Malformed:
    payload: bytes


@dataclass(frozen=True)
class PrnDecision:
    """One completed adaptive-PRN state-machine decision."""

    kind: str
    old_window: int
    new_window: int


@dataclass(frozen=True)
class DataTransferStats:
    """Timing for the complete RECEIVE/DATA phase, including final response."""

    payload_bytes: int
    elapsed: float

    @property
    def payload_rate(self) -> float:
        return self.payload_bytes / self.elapsed if self.elapsed > 0 else math.inf


class AdaptivePrn:
    """Move between a packet-size-safe set of PRN synchronization windows."""

    LEVELS = (8, 16, 32)
    # A neutral link can be trapped at the lowest window: the extra receipt
    # traffic itself can keep its measured rate below the normal promotion
    # threshold.  Two clean, exact receipts are enough to try one adjacent
    # safe level.  A probe is decided after at most two receipts at the new
    # level.  A clearly better/worse first sample decides immediately; close
    # samples are averaged so one scheduling jitter sample cannot oscillate
    # the window.  A failed probe or a real demotion from a previously kept
    # level blocks every further increase for this DFU session, including a
    # later fast-looking jitter streak.  Further slow receipts can still move
    # down through the remaining safe levels.
    NEUTRAL_RECEIPTS_TO_PROBE = 2
    PROBE_RECEIPTS_TO_DECIDE = 2
    PROBE_MATERIAL_RATE_RATIO = 0.10
    # A physical XIAO nRF52840 run sustained about 2110 payload B/s with
    # 244-byte writes and exact PRN4 receipts. The promotion floor leaves
    # margin below that measured result. The separate 2:1 slow floor creates
    # a broad neutral band, so jitter cannot make the window oscillate.
    DEFAULT_FAST_PAYLOAD_RATE = 1600.0
    DEFAULT_SLOW_PAYLOAD_RATE = 800.0
    # Receipt delivery includes the target notification, BLE connection event,
    # BlueZ, and asyncio wakeup. This allowance is paid once per exact receipt,
    # not once per packet, so larger windows still have to demonstrate useful
    # payload throughput.
    DEFAULT_RECEIPT_LATENCY_ALLOWANCE = 0.125

    def __init__(
        self,
        *,
        packet_size: int = 20,
        fast_payload_rate: float = DEFAULT_FAST_PAYLOAD_RATE,
        slow_payload_rate: float = DEFAULT_SLOW_PAYLOAD_RATE,
        receipt_latency_allowance: float = DEFAULT_RECEIPT_LATENCY_ALLOWANCE,
        fast_receipts_to_increase: int = 2,
        levels: tuple[int, ...] = LEVELS,
    ) -> None:
        if (
            isinstance(packet_size, bool)
            or not isinstance(packet_size, int)
            or packet_size < 20
            or packet_size > 244
            or packet_size % 4
        ):
            raise ValueError(
                "adaptive PRN packet size must be word aligned in 20..244"
            )
        if (
            isinstance(fast_payload_rate, bool)
            or not isinstance(fast_payload_rate, (int, float))
            or not math.isfinite(fast_payload_rate)
            or isinstance(slow_payload_rate, bool)
            or not isinstance(slow_payload_rate, (int, float))
            or not math.isfinite(slow_payload_rate)
            or not 0 < slow_payload_rate < fast_payload_rate
        ):
            raise ValueError("adaptive PRN timing thresholds are invalid")
        if (
            isinstance(receipt_latency_allowance, bool)
            or not isinstance(receipt_latency_allowance, (int, float))
            or not math.isfinite(receipt_latency_allowance)
            or receipt_latency_allowance < 0
        ):
            raise ValueError("adaptive PRN receipt allowance is invalid")
        if (
            isinstance(fast_receipts_to_increase, bool)
            or not isinstance(fast_receipts_to_increase, int)
            or fast_receipts_to_increase < 1
        ):
            raise ValueError("fast receipt count must be positive")
        if (
            not levels
            or any(isinstance(level, bool) or not isinstance(level, int) for level in levels)
            or any(level <= 0 or level > 0xFFFF for level in levels)
            or any(left >= right for left, right in zip(levels, levels[1:]))
        ):
            raise ValueError("adaptive PRN levels must be strictly increasing uint16 values")
        self.packet_size = packet_size
        self.fast_payload_rate = fast_payload_rate
        self.slow_payload_rate = slow_payload_rate
        self.receipt_latency_allowance = receipt_latency_allowance
        self.fast_receipts_to_increase = fast_receipts_to_increase
        self.levels = levels
        self.index = 0
        self.consecutive_fast = 0
        self._fast_rate_total = 0.0
        self.consecutive_neutral = 0
        self._neutral_rate_total = 0.0
        self.probe_active = False
        self.probe_blocked = False
        self.last_decision: PrnDecision | None = None
        self._probe_origin_index: int | None = None
        self._probe_baseline_rate = 0.0
        self._probe_rate_total = 0.0
        self._probe_receipts = 0

    @property
    def window(self) -> int:
        return self.levels[self.index]

    def _receipt_budget(self, payload_bytes: int, payload_rate: float) -> float:
        return self.receipt_latency_allowance + payload_bytes / payload_rate

    def _reset_neutral_streak(self) -> None:
        self.consecutive_neutral = 0
        self._neutral_rate_total = 0.0

    def _reset_fast_streak(self) -> None:
        self.consecutive_fast = 0
        self._fast_rate_total = 0.0

    def _start_probe(self, baseline_rate: float) -> None:
        if self.index >= len(self.levels) - 1:
            raise RuntimeError("adaptive PRN probe has no higher level")
        self._probe_origin_index = self.index
        self._probe_baseline_rate = baseline_rate
        self.index += 1
        self.probe_active = True
        self._probe_rate_total = 0.0
        self._probe_receipts = 0
        self._reset_fast_streak()
        self._reset_neutral_streak()

    def _finish_probe(self, *, keep: bool) -> None:
        if not keep:
            if self._probe_origin_index is None:
                raise RuntimeError("adaptive PRN probe has no origin")
            self.index = self._probe_origin_index
            self.probe_blocked = True
        self.probe_active = False
        self._probe_origin_index = None
        self._probe_baseline_rate = 0.0
        self._probe_rate_total = 0.0
        self._probe_receipts = 0
        self._reset_fast_streak()
        self._reset_neutral_streak()

    def observe_exact_receipt(
        self,
        elapsed: float,
        packet_count: int,
        payload_bytes: int | None = None,
    ) -> int:
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed <= 0
            or isinstance(packet_count, bool)
            or not isinstance(packet_count, int)
            or packet_count <= 0
        ):
            raise ValueError("receipt timing sample is invalid")
        if payload_bytes is None:
            payload_bytes = packet_count * self.packet_size
        if (
            isinstance(payload_bytes, bool)
            or not isinstance(payload_bytes, int)
            or payload_bytes <= 0
            or payload_bytes > packet_count * self.packet_size
        ):
            raise ValueError("receipt payload sample is invalid")

        fast_budget = self._receipt_budget(
            payload_bytes, self.fast_payload_rate
        )
        slow_budget = self._receipt_budget(
            payload_bytes, self.slow_payload_rate
        )
        observed_rate = payload_bytes / elapsed
        self.last_decision = None

        if self.probe_active:
            # Storage bounds are already enforced by ``levels``.  This branch
            # only decides whether the adjacent safe level improved delivery.
            lower_rate = self._probe_baseline_rate * (
                1.0 - self.PROBE_MATERIAL_RATE_RATIO
            )
            upper_rate = self._probe_baseline_rate * (
                1.0 + self.PROBE_MATERIAL_RATE_RATIO
            )
            old_window = self.window
            if elapsed >= slow_budget or observed_rate < lower_rate:
                self._finish_probe(keep=False)
                self.last_decision = PrnDecision(
                    "probe_rolled_back", old_window, self.window
                )
            elif observed_rate > upper_rate:
                self._finish_probe(keep=True)
                self.last_decision = PrnDecision(
                    "probe_kept", old_window, self.window
                )
            else:
                self._probe_rate_total += observed_rate
                self._probe_receipts += 1
                if self._probe_receipts >= self.PROBE_RECEIPTS_TO_DECIDE:
                    average_rate = (
                        self._probe_rate_total / self._probe_receipts
                    )
                    keep = average_rate >= self._probe_baseline_rate or math.isclose(
                        average_rate,
                        self._probe_baseline_rate,
                        rel_tol=1e-9,
                        abs_tol=0.0,
                    )
                    self._finish_probe(keep=keep)
                    self.last_decision = PrnDecision(
                        "probe_kept" if keep else "probe_rolled_back",
                        old_window,
                        self.window,
                    )
            return self.window

        if elapsed >= slow_budget:
            old_window = self.window
            self.index = max(0, self.index - 1)
            self._reset_fast_streak()
            self._reset_neutral_streak()
            if self.window != old_window:
                # A level that was initially useful can still become too slow
                # later in the same transfer.  Once that real demotion occurs,
                # keep the lower safe level for the rest of this session rather
                # than cycling up again on two transiently fast receipts.
                self.probe_blocked = True
                self.last_decision = PrnDecision(
                    "slow_demoted", old_window, self.window
                )
        elif elapsed <= fast_budget:
            self._reset_neutral_streak()
            if self.probe_blocked:
                self._reset_fast_streak()
            else:
                self.consecutive_fast += 1
                self._fast_rate_total += observed_rate
                if (
                    self.consecutive_fast
                    >= self.fast_receipts_to_increase
                    and self.index < len(self.levels) - 1
                ):
                    old_window = self.window
                    baseline_rate = (
                        self._fast_rate_total / self.consecutive_fast
                    )
                    self._start_probe(baseline_rate)
                    self.last_decision = PrnDecision(
                        "probe_started", old_window, self.window
                    )
                elif self.index == len(self.levels) - 1:
                    self._reset_fast_streak()
        else:
            self._reset_fast_streak()
            if self.probe_blocked or self.index == len(self.levels) - 1:
                self._reset_neutral_streak()
            else:
                self.consecutive_neutral += 1
                self._neutral_rate_total += observed_rate
                if (
                    self.consecutive_neutral
                    >= self.NEUTRAL_RECEIPTS_TO_PROBE
                ):
                    old_window = self.window
                    baseline_rate = (
                        self._neutral_rate_total / self.consecutive_neutral
                    )
                    self._start_probe(baseline_rate)
                    self.last_decision = PrnDecision(
                        "probe_started", old_window, self.window
                    )
        return self.window


class LegacyDfu:
    """Strict Legacy DFU protocol engine independent of the BLE backend."""

    def __init__(
        self,
        transport: Transport,
        *,
        packet_size: int,
        response_timeout: float,
        receipt_timeout: float,
        clock: Callable[[], float] = time.monotonic,
        adaptive_prn: AdaptivePrn | None = None,
        progress: Callable[[int, int, int, float], None] | None = None,
        window_changed: Callable[[int, int, float, int], None] | None = None,
        adaptation_event: Callable[[PrnDecision, float, int], None] | None = None,
    ) -> None:
        if packet_size < 20 or packet_size > 244 or packet_size % 4:
            raise ValueError("DFU packet size must be a word-aligned value in 20..244")
        if response_timeout <= 0 or receipt_timeout <= 0:
            raise ValueError("DFU timeouts must be positive")
        self.transport = transport
        self.packet_size = packet_size
        self.response_timeout = response_timeout
        self.receipt_timeout = receipt_timeout
        self.clock = clock
        # The current OTAFIX target buffers at most eight 256-byte pstorage
        # packets while lazy erase is active.  Packet writes above 64 bytes
        # bypass the 240-byte accumulator, so they must never use PRN 16/32.
        # At exactly 64 bytes, three writes pack per store; PRN 16 remains
        # below the same storage horizon.  Up to 60 bytes, PRN 32 produces at
        # most eight accumulated stores.
        if packet_size > 64:
            safe_prn_levels = (4, 8)
        elif packet_size == 64:
            safe_prn_levels = (8, 16)
        else:
            safe_prn_levels = (8, 16, 32)
        if adaptive_prn is None:
            self.prn = AdaptivePrn(
                packet_size=packet_size, levels=safe_prn_levels
            )
        else:
            if (
                adaptive_prn.packet_size != packet_size
                or adaptive_prn.levels
                != safe_prn_levels[: len(adaptive_prn.levels)]
            ):
                raise ValueError(
                    f"adaptive PRN {adaptive_prn.packet_size}-byte levels "
                    f"{adaptive_prn.levels} do not preserve the safe "
                    f"{safe_prn_levels} start/bounds for {packet_size}-byte packets"
                )
            self.prn = adaptive_prn
        self.progress = progress
        self.window_changed = window_changed
        self.adaptation_event = adaptation_event
        self.events: asyncio.Queue[_Response | _Receipt | _Malformed] = asyncio.Queue()

    def notification(self, _sender: Any, data: bytearray | bytes) -> None:
        payload = bytes(data)
        if len(payload) == 3 and payload[0] == OP_RESPONSE:
            self.events.put_nowait(_Response(payload[1], payload[2]))
        elif len(payload) == 5 and payload[0] == OP_PRN:
            self.events.put_nowait(_Receipt(struct.unpack_from("<I", payload, 1)[0]))
        else:
            self.events.put_nowait(_Malformed(payload))

    async def _next_event(
        self, timeout: float, label: str
    ) -> _Response | _Receipt | _Malformed:
        try:
            return await asyncio.wait_for(self.events.get(), timeout)
        except asyncio.TimeoutError as exc:
            raise DfuError(f"timed out waiting for {label}") from exc

    async def expect_response(self, opcode: int, timeout: float | None = None) -> None:
        event = await self._next_event(
            timeout if timeout is not None else self.response_timeout,
            f"response to opcode 0x{opcode:02x}",
        )
        if isinstance(event, _Malformed):
            raise DfuError(f"malformed DFU notification: {event.payload.hex()}")
        if not isinstance(event, _Response):
            raise DfuError(
                f"unexpected packet receipt while awaiting opcode 0x{opcode:02x}"
            )
        if event.opcode != opcode:
            raise DfuError(
                f"response opcode mismatch: got 0x{event.opcode:02x}, "
                f"expected 0x{opcode:02x}"
            )
        if event.result != RESULT_SUCCESS:
            name = RESULT_NAMES.get(event.result, f"unknown result 0x{event.result:02x}")
            raise DfuError(f"DFU opcode 0x{opcode:02x} failed: {name}")

    async def _set_prn(self, count: int) -> None:
        await self.transport.write_control(
            bytes((OP_PRN_REQUEST,)) + struct.pack("<H", count)
        )

    async def start(self, package: Package) -> None:
        await self.transport.write_control(bytes((OP_START, package.mode)))
        await self.transport.write_packet(
            struct.pack(
                "<III",
                package.softdevice_size,
                package.bootloader_size,
                package.application_size,
            )
        )
        # Combined recovery erases/prepares much more flash before acknowledging.
        timeout = max(self.response_timeout, 180.0) if package.mode == MODE_SD_BOOTLOADER else self.response_timeout
        await self.expect_response(OP_START, timeout)

    async def initialize(self, init_packet: bytes) -> None:
        await self.transport.write_control(bytes((OP_INITIALIZE, 0x00)))
        # Init data stays on the universally safe Legacy DFU write size.
        for offset in range(0, len(init_packet), 20):
            await self.transport.write_packet(init_packet[offset : offset + 20])
        await self.transport.write_control(bytes((OP_INITIALIZE, 0x01)))
        await self.expect_response(OP_INITIALIZE, max(self.response_timeout, 60.0))
        await self._set_prn(self.prn.window)

    async def send_firmware(self, firmware: bytes) -> DataTransferStats:
        if not firmware or len(firmware) % 4:
            raise DfuError("firmware transfer must be nonempty and word aligned")
        phase_started = self.clock()
        await self.transport.write_control(bytes((OP_RECEIVE,)))
        sent = 0
        confirmed = 0
        window_packets = 0
        window_bytes = 0
        window_started = self.clock()
        send_started = window_started
        next_progress = 5

        while sent < len(firmware):
            remaining = len(firmware) - sent
            chunk_length = min(remaining, self.packet_size)

            # Nordic's original non-accumulator receive path sends the final
            # RECEIVE response but does not send PRN when the final write also
            # lands exactly on a PRN boundary.  Never wait for a receipt that
            # this target family is known not to emit.  Split that tail so the
            # boundary is a non-final, word-aligned write.  The second branch
            # makes room when the otherwise-final tail would be only one word.
            slots_to_receipt = self.prn.window - window_packets
            if slots_to_receipt == 1 and remaining <= self.packet_size:
                if remaining < 8:
                    raise DfuError("cannot safely split a final PRN-boundary word")
                chunk_length = 4
            elif (
                slots_to_receipt == 2
                and remaining == self.packet_size + 4
            ):
                chunk_length = self.packet_size - 4

            chunk = firmware[sent : sent + chunk_length]
            await self.transport.write_packet(chunk)
            sent += len(chunk)
            window_packets += 1
            window_bytes += len(chunk)

            if window_packets == self.prn.window:
                event = await self._next_event(
                    self.receipt_timeout,
                    f"exact cumulative packet receipt at {sent} bytes",
                )
                if isinstance(event, _Malformed):
                    raise DfuError(f"malformed DFU notification: {event.payload.hex()}")
                if not isinstance(event, _Receipt):
                    raise DfuError(f"missing packet receipt at {sent} bytes")
                if event.byte_count != sent:
                    relation = "short" if event.byte_count < sent else "ahead"
                    raise DfuError(
                        f"{relation} packet receipt: target reports {event.byte_count}, "
                        f"host sent {sent}"
                    )
                confirmed = event.byte_count
                elapsed = self.clock() - window_started
                old_window = self.prn.window
                self.prn.observe_exact_receipt(
                    elapsed, window_packets, window_bytes
                )
                if self.prn.window != old_window:
                    await self._set_prn(self.prn.window)
                    if self.window_changed is not None:
                        self.window_changed(
                            old_window, self.prn.window, elapsed, window_packets
                        )
                if (
                    self.prn.last_decision is not None
                    and self.adaptation_event is not None
                ):
                    self.adaptation_event(
                        self.prn.last_decision, elapsed, window_packets
                    )
                window_packets = 0
                window_bytes = 0
                window_started = self.clock()

            percent = sent * 100 // len(firmware)
            if percent >= next_progress or sent == len(firmware):
                elapsed_total = max(self.clock() - send_started, 0.001)
                if self.progress is not None:
                    self.progress(
                        sent, confirmed, len(firmware), sent / elapsed_total
                    )
                while next_progress <= percent:
                    next_progress += 5

        await self.expect_response(OP_RECEIVE, max(self.response_timeout, 120.0))
        phase_elapsed = max(0.0, self.clock() - phase_started)
        confirmed = len(firmware)
        if self.progress is not None:
            self.progress(
                sent,
                confirmed,
                len(firmware),
                sent / max(phase_elapsed, 0.001),
            )
        return DataTransferStats(len(firmware), phase_elapsed)

    async def validate(self) -> None:
        await self.transport.write_control(bytes((OP_VALIDATE,)))
        await self.expect_response(OP_VALIDATE, max(self.response_timeout, 120.0))

    async def activate(self) -> None:
        await self.transport.write_control(bytes((OP_ACTIVATE_RESET,)))


class BleakTransport:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def write_control(self, payload: bytes) -> None:
        await self.client.write_gatt_char(DFU_CONTROL, payload, response=True)

    async def write_packet(self, payload: bytes) -> None:
        await self.client.write_gatt_char(DFU_PACKET, payload, response=False)


def _strict_capability_integer(
    value: Any,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WriteCapabilityUnavailable(f"{label} is not an integer")
    if value < minimum or value > maximum:
        raise WriteCapabilityUnavailable(
            f"{label} is outside {minimum}..{maximum}: {value}"
        )
    return value


def _read_negotiated_mtu(client: Any) -> int:
    try:
        value = client.mtu_size
    except Exception as exc:
        raise WriteCapabilityUnavailable("ATT MTU could not be read") from exc
    return _strict_capability_integer(value, "ATT MTU", ATT_MTU_MIN, ATT_MTU_MAX)


def _read_max_write_without_response(characteristic: Any) -> int:
    try:
        value = characteristic.max_write_without_response_size
    except Exception as exc:
        raise WriteCapabilityUnavailable(
            "write-without-response capability could not be read"
        ) from exc
    return _strict_capability_integer(
        value,
        "write-without-response capability",
        ATT_MTU_MIN - ATT_WRITE_COMMAND_OVERHEAD,
        ATT_WRITE_COMMAND_MAX,
    )


async def negotiate_packet_size(client: Any, high_mtu_requested: bool) -> int:
    """Try BlueZ's explicit MTU acquisition, otherwise retain 20-byte writes."""

    if not high_mtu_requested:
        return 20
    acquired = False
    backend = getattr(client, "_backend", None)
    acquire = getattr(backend, "_acquire_mtu", None)
    if acquire is not None:
        try:
            await acquire()
            acquired = True
        except Exception as exc:
            if not client.is_connected:
                raise DfuError(
                    "BLE link disconnected during high MTU negotiation"
                ) from exc
            print(f"High MTU negotiation failed ({exc}); using 20-byte packets", flush=True)
    if not client.is_connected:
        raise DfuError("BLE link disconnected during high MTU negotiation")
    try:
        services = client.services
        characteristic = services.get_characteristic(DFU_PACKET)
    except Exception as exc:
        if not client.is_connected:
            raise DfuError(
                "BLE link disconnected while reading high MTU capability"
            ) from exc
        raise DfuError(
            "BLE service cache failed while reading high MTU capability"
        ) from exc
    if characteristic is None:
        if not client.is_connected:
            raise DfuError(
                "BLE link disconnected while reading high MTU capability"
            )
        raise DfuError("connected device has no Legacy DFU packet characteristic")
    try:
        negotiated_mtu = _read_negotiated_mtu(client)
        max_write = _read_max_write_without_response(characteristic)
    except WriteCapabilityUnavailable as exc:
        if not client.is_connected:
            raise DfuError(
                "BLE link disconnected while reading high MTU capability"
            ) from exc
        print(
            f"High MTU capability observation failed ({exc}); "
            "using 20-byte packets",
            flush=True,
        )
        negotiated_mtu = 23
        max_write = 20
        acquired = False
    if not client.is_connected:
        raise DfuError("BLE link disconnected while reading high MTU capability")
    if acquired and negotiated_mtu > 23 and max_write == 20:
        wait_observation_failed = False
        try:
            max_write, waited = await wait_for_max_write_without_response(
                client, characteristic
            )
        except WriteCapabilityUnavailable as exc:
            max_write = 20
            waited = 0.0
            wait_observation_failed = True
            print(
                f"High MTU capability observation failed while waiting ({exc}); "
                "retaining the 20-byte compatibility fallback",
                flush=True,
            )
        if not wait_observation_failed and max_write > 20:
            print(
                f"write-without-response capability became {max_write} after "
                f"{waited:.3f}s",
                flush=True,
            )
        elif not wait_observation_failed:
            print(
                f"write-without-response capability remained {max_write} after "
                f"{waited:.3f}s; retaining the 20-byte compatibility fallback",
                flush=True,
            )
    size = select_packet_size(
        high_mtu_requested=True,
        mtu_acquired=acquired,
        negotiated_mtu=negotiated_mtu,
        max_write_without_response=max_write,
    )
    print(
        f"ATT MTU={negotiated_mtu}, write-without-response={max_write}; "
        f"using {size}-byte DFU packets",
        flush=True,
    )
    return size


async def wait_for_max_write_without_response(
    client: Any,
    characteristic: Any,
    *,
    timeout: float = 3.0,
    poll_interval: float = 0.1,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> tuple[int, float]:
    """Wait briefly for BlueZ's characteristic MTU cache to catch up.

    ``AcquireWrite`` can prove an ATT MTU larger than 23 before BlueZ emits the
    corresponding ``GattCharacteristic1.MTU`` property change.  Bleak then
    temporarily reports the default 20-byte write capability.  Poll only the
    already identity-gated packet characteristic and fail safe to its final
    reported value; never reconnect, rescan, or probe the target with a write.
    """

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
        or isinstance(poll_interval, bool)
        or not isinstance(poll_interval, (int, float))
        or not math.isfinite(poll_interval)
        or poll_interval <= 0
    ):
        raise ValueError("write-capability wait values must be finite and positive")
    try:
        expected_services = client.services
    except Exception as exc:
        if not client.is_connected:
            raise DfuError(
                "BLE link disconnected while waiting for write capability"
            ) from exc
        raise DfuError(
            "BLE service cache could not be captured for write-capability wait"
        ) from exc
    expected_handle = getattr(characteristic, "handle", None)
    started = clock()
    if (
        isinstance(started, bool)
        or not isinstance(started, (int, float))
        or not math.isfinite(started)
    ):
        raise DfuError("write-capability clock returned an invalid start time")
    deadline = started + timeout
    if not math.isfinite(deadline):
        raise DfuError("write-capability deadline is not finite")
    previous = started

    while True:
        if not client.is_connected:
            raise DfuError("BLE link disconnected while waiting for write capability")
        try:
            current_services = client.services
            current = current_services.get_characteristic(DFU_PACKET)
        except Exception as exc:
            if not client.is_connected:
                raise DfuError(
                    "BLE link disconnected while waiting for write capability"
                ) from exc
            raise DfuError(
                "BLE service cache failed while waiting for write capability"
            ) from exc
        if not client.is_connected:
            raise DfuError("BLE link disconnected while waiting for write capability")
        if current_services is not expected_services:
            raise DfuError("BLE service collection identity changed while connected")
        if current is None:
            raise DfuError("DFU packet characteristic disappeared while connected")
        if current is not characteristic:
            raise DfuError("DFU packet characteristic object changed while connected")
        if (
            expected_handle is not None
            and getattr(current, "handle", None) != expected_handle
        ):
            raise DfuError("DFU packet characteristic identity changed while connected")
        try:
            max_write = _read_max_write_without_response(current)
        except WriteCapabilityUnavailable as exc:
            if not client.is_connected:
                raise DfuError(
                    "BLE link disconnected while waiting for write capability"
                ) from exc
            raise
        if not client.is_connected:
            raise DfuError("BLE link disconnected while waiting for write capability")
        now = clock()
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
            or now < previous
        ):
            raise DfuError("write-capability clock is not finite and monotonic")
        previous = now
        remaining = deadline - now
        if max_write != 20 or remaining <= 0:
            return max_write, max(0.0, now - started)
        delay = min(float(poll_interval), remaining)
        if not math.isfinite(delay) or delay <= 0:
            raise DfuError("write-capability wait produced an invalid delay")
        await sleep(delay)


async def read_model(client: Any, expected_model: str) -> str:
    characteristic = client.services.get_characteristic(DIS_MODEL_NUMBER)
    if characteristic is None:
        raise DfuError("connected device does not expose the required DIS model number")
    try:
        model = bytes(await client.read_gatt_char(DIS_MODEL_NUMBER)).decode(
            "utf-8", "strict"
        ).rstrip("\x00")
    except Exception as exc:
        raise DfuError(f"could not read DIS model number: {exc}") from exc
    if model != expected_model:
        raise DfuError(
            f"DIS model mismatch: got {model!r}, expected {expected_model!r}"
        )
    return model


def ignore_termination_signals() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for name in ("SIGHUP", "SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, signal.SIG_IGN)
    return previous


def restore_signals(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def require_confirmed_activation_write(
    confirmed: bool, write_error: Exception | None
) -> None:
    """Reject a peer disconnect that followed an unconfirmed ACTIVATE write."""

    if not confirmed:
        raise DfuError(
            "target disconnected after an unconfirmed ACTIVATE write; delivery is "
            f"unknown ({write_error!r}); verify target identity manually"
        )


def begin_connected_generation(disconnected: asyncio.Event) -> None:
    """Discard callbacks from connection attempts that preceded the live link.

    BlueZ can fail one LE connection attempt and immediately retry it inside a
    single ``BleakClient.connect()`` call.  Bleak delivers the failed attempt's
    disconnect callback even when the retry succeeds.  Treating that stale
    event as a disconnect after VALIDATE makes the host tear down a healthy
    link before it can send ACTIVATE.

    Call this only after ``connect()`` has returned successfully.  A real
    disconnect of the established generation will set the event again.
    """

    disconnected.clear()


def bleak_adapter_kwargs(factory: Any, adapter: str) -> dict[str, Any]:
    """Use Bleak 3's BlueZ options while preserving Bleak 2 support."""

    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        # ``adapter`` remains accepted by Bleak 3 as a compatibility argument.
        # Prefer a working explicit adapter over silently selecting the wrong
        # controller when a third-party wrapper cannot be introspected.
        return {"adapter": adapter}
    if "bluez" in parameters:
        return {"bluez": {"adapter": adapter}}
    return {"adapter": adapter}


async def cleanup_before_activation(client: Any, notify_started: bool) -> None:
    """Stop notifications and always attempt a pre-ACTIVATE disconnect."""

    try:
        if notify_started and client.is_connected:
            await client.stop_notify(DFU_CONTROL)
    finally:
        # A stop-notify failure must never suppress the actual disconnect
        # attempt.
        if client.is_connected:
            await client.disconnect()


async def lab_pre_start_pause(
    seconds: float, client: Any, disconnected: asyncio.Event
) -> None:
    """Expose a bounded lab-only window before the first DFU write.

    The pause is deliberately before START so a hardware harness can make and
    verify one connection-parameter request without putting a partial image on
    the target.  Production callers leave the duration at zero.
    """
    if seconds == 0:
        return
    print(
        f"LAB PRE-START READY: pausing {seconds:g}s before the first DFU write",
        flush=True,
    )
    await asyncio.sleep(seconds)
    if disconnected.is_set() or not client.is_connected:
        raise DfuError("BLE link disconnected during the lab pre-START pause")
    print("LAB PRE-START COMPLETE: BLE link remains connected", flush=True)


async def run(args: argparse.Namespace) -> None:
    overall_started = time.monotonic()
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as exc:
        raise DfuError("Bleak is required; install it in a dedicated pipx environment") from exc

    package = read_package(args.package, args.sha256)
    print(
        f"Package verified: kind={package.kind}, SHA-256={package.sha256}, "
        f"SD={package.softdevice_size}, BL={package.bootloader_size}, "
        f"APP={package.application_size}",
        flush=True,
    )
    discovered = await BleakScanner.discover(
        timeout=args.scan_timeout,
        return_adv=True,
        **bleak_adapter_kwargs(BleakScanner, args.adapter),
    )
    device, advertisement = select_advertisement(
        discovered, args.address, args.expected_name
    )
    print(
        f"Advertisement verified: address={device.address}, "
        f"name={advertisement.local_name!r}, Legacy DFU service present",
        flush=True,
    )

    disconnected = asyncio.Event()

    def disconnected_callback(_client: Any) -> None:
        disconnected.set()

    client = BleakClient(
        device,
        disconnected_callback=disconnected_callback,
        timeout=args.connect_timeout,
        **bleak_adapter_kwargs(BleakClient, args.adapter),
    )
    activation_attempted = False
    notify_started = False
    protected_signals: dict[int, Any] = {}
    try:
        # Keep connect inside the cleanup scope: a backend can raise after it
        # has established a partial connection.
        await client.connect()
        begin_connected_generation(disconnected)
        if not client.is_connected:
            raise DfuError("BLE link disconnected as connect() completed")
        if str(client.address).casefold() != args.address.casefold():
            raise DfuError(
                f"connected-address mismatch: got {client.address}, expected {args.address}"
            )
        if client.services.get_service(DFU_SERVICE) is None:
            raise DfuError("connected device does not expose Nordic Legacy DFU service")
        if client.services.get_characteristic(DFU_CONTROL) is None:
            raise DfuError("connected device has no Legacy DFU control characteristic")
        if client.services.get_characteristic(DFU_PACKET) is None:
            raise DfuError("connected device has no Legacy DFU packet characteristic")

        model = await read_model(client, args.expected_model)
        print(f"DIS model verified: {model!r}", flush=True)
        packet_size = await negotiate_packet_size(client, args.high_mtu)
        await lab_pre_start_pause(
            args.lab_pre_start_pause, client, disconnected
        )
        transport = BleakTransport(client)

        def progress(
            sent: int, confirmed: int, total: int, send_rate: float
        ) -> None:
            print(
                f"  DATA sent {sent * 100 // total:3d}% {sent}/{total}; "
                f"target-confirmed {confirmed}/{total}; "
                f"DATA-to-current-point average {send_rate:.0f} payload B/s",
                flush=True,
            )

        def adaptation_event(
            decision: PrnDecision, elapsed: float, packets: int
        ) -> None:
            labels = {
                "probe_started": "probe started",
                "probe_kept": "probe kept",
                "probe_rolled_back": "probe rolled back and further increases blocked",
                "slow_demoted": (
                    "reduced after a slow exact receipt and further "
                    "increases blocked"
                ),
            }
            label = labels.get(decision.kind, decision.kind)
            print(
                f"  PRN/window {label}: {decision.old_window} -> "
                f"{decision.new_window} after an "
                f"exact {elapsed:.3f}s/{packets}-packet receipt",
                flush=True,
            )

        dfu = LegacyDfu(
            transport,
            packet_size=packet_size,
            response_timeout=args.timeout,
            receipt_timeout=args.receipt_timeout,
            progress=progress,
            adaptation_event=adaptation_event,
        )
        await client.start_notify(DFU_CONTROL, dfu.notification)
        notify_started = True

        print(f"START: {package.kind}", flush=True)
        await dfu.start(package)
        print(f"INIT: {len(package.init_packet)} bytes", flush=True)
        await dfu.initialize(package.init_packet)
        prn_levels = " -> ".join(str(level) for level in dfu.prn.levels)
        print(
            f"DATA: {len(package.firmware)} bytes; adaptive PRN/window {prn_levels}",
            flush=True,
        )
        data_stats = await dfu.send_firmware(package.firmware)
        print(
            f"DATA complete: {data_stats.payload_bytes} bytes confirmed in "
            f"{data_stats.elapsed:.3f}s "
            f"({data_stats.payload_rate:.0f} payload B/s; DATA phase only)",
            flush=True,
        )
        print("VALIDATE: target CRC/final image validation", flush=True)
        await dfu.validate()

        # ACTIVATE delivery may race the target's reset.  From here onward a
        # central-initiated disconnect is forbidden: it cannot distinguish a
        # failed write from an accepted command whose response was cut off.
        if disconnected.is_set() or not client.is_connected:
            raise DfuError("target disconnected before ACTIVATE could be sent")
        protected_signals = ignore_termination_signals()
        activation_attempted = True
        print("ACTIVATE: waiting for the target to disconnect itself", flush=True)
        activation_write_confirmed = False
        activation_write_error: Exception | None = None
        try:
            await dfu.activate()
            activation_write_confirmed = True
        except Exception as exc:
            activation_write_error = exc
            print(
                f"ACTIVATE write returned {exc!r}; delivery is unknown, preserving the link",
                flush=True,
            )
        try:
            await asyncio.wait_for(disconnected.wait(), args.activation_timeout)
        except asyncio.TimeoutError:
            print(
                f"WARNING: no peer disconnect after {args.activation_timeout:g}s; "
                "waiting indefinitely rather than interrupting a possible copy",
                flush=True,
            )
            await disconnected.wait()
        require_confirmed_activation_write(
            activation_write_confirmed, activation_write_error
        )
        print("Target initiated the expected BLE disconnect", flush=True)
    finally:
        if activation_attempted:
            # The peer has disconnected on the successful path.  Deliberately
            # make no post-ACTIVATE GATT or BlueZ cleanup calls.
            restore_signals(protected_signals)
        else:
            await cleanup_before_activation(client, notify_started)

    if package.kind == "softdevice_bootloader":
        print(
            "Combined recovery accepted. Wait for both MBR copy/finalization resets, "
            "then verify INFO_UF2.TXT before installing an application.",
            flush=True,
        )
    else:
        print("Application DFU accepted; verify the exact application identity after reboot.", flush=True)
    overall_elapsed = time.monotonic() - overall_started
    print(
        f"DFU end-to-end through target disconnect: {overall_elapsed:.3f}s "
        "(package check, scan, connect, START, INIT, DATA, VALIDATE, and ACTIVATE)",
        flush=True,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Strict, identity-gated OTAFIX Nordic Legacy BLE DFU"
    )
    result.add_argument("--address", required=True, help="exact target BLE address")
    result.add_argument("--expected-name", required=True, help="exact advertised GAP name")
    result.add_argument("--package", required=True, type=Path)
    result.add_argument("--sha256", required=True, help="exact package SHA-256")
    result.add_argument(
        "--expected-model",
        required=True,
        help="exact required Device Information Service model number",
    )
    result.add_argument("--adapter", default="hci0")
    result.add_argument(
        "--high-mtu",
        action="store_true",
        help="request high MTU, retaining 20-byte writes unless negotiation is proven",
    )
    result.add_argument("--timeout", type=float, default=30.0)
    result.add_argument("--receipt-timeout", type=float, default=15.0)
    result.add_argument("--scan-timeout", type=float, default=20.0)
    result.add_argument("--connect-timeout", type=float, default=20.0)
    result.add_argument("--activation-timeout", type=float, default=180.0)
    result.add_argument(
        "--lab-pre-start-pause",
        type=float,
        default=0.0,
        help=(
            "testing only: pause after identity/MTU gates and before the first "
            "DFU write so a harness can verify one connection update"
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    timeouts = (
        args.timeout,
        args.receipt_timeout,
        args.scan_timeout,
        args.connect_timeout,
        args.activation_timeout,
    )
    if any(not math.isfinite(value) or value <= 0 for value in timeouts):
        print("ERROR: all timeouts must be finite and positive", file=sys.stderr)
        return 2
    if (
        not math.isfinite(args.lab_pre_start_pause)
        or args.lab_pre_start_pause < 0
    ):
        print(
            "ERROR: --lab-pre-start-pause must be finite and nonnegative",
            file=sys.stderr,
        )
        return 2
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
