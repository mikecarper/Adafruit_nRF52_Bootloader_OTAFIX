#!/usr/bin/env python3
"""Check and install the latest signed OTAFIX bootloader over MeshCore LoRa."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.request import Request, urlopen
import zipfile


REPOSITORY = "mikecarper/Adafruit_nRF52_Bootloader_OTAFIX"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
LATEST_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
OFFICIAL_PUBLIC_KEY = (
    "272564CC588D3D122285A15E6E2566D2ABE7177BB7EA1D1E41B23B29F0F85D2D"
)
BUNDLE_RE = re.compile(r"^OTAFIX-(.+)-bootloader-mota\.zip$")
VERSION_RE = re.compile(
    r"OTAFIX(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?:-preview\.(?P<preview>[0-9]+))?"
)
IDENTITY_RE = re.compile(
    r"BL board=(?P<board>[0-9A-Fa-f]{8}) "
    r"target=(?P<target>[0-9A-Fa-f]{8}) "
    r"name=(?P<name>\S+) crc=(?P<crc>[0-9A-Fa-f]{8}) "
    r"abi=(?P<abi>[0-9]+) caps=(?P<caps>[0-9A-Fa-f]{2})"
)
STAGED_RE = re.compile(
    r"staged:ready mid=(?P<mid>[0-9A-Fa-f]{8}) "
    r"hash=(?P<hash>[0-9A-Fa-f]{16})"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MOTA_SIZE = 41330
MOTA_HEADER_SIZE = 8


class UpdateError(RuntimeError):
    """A guarded update could not continue."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    channel: int
    label: str

    @property
    def order(self) -> tuple[int, int, int, int]:
        return self.major, self.minor, self.patch, self.channel


@dataclass(frozen=True)
class NodeIdentity:
    board_id: str
    target_id: str
    name: str
    crc: str
    abi: int
    caps: int


@dataclass(frozen=True)
class Release:
    tag: str
    version: Version
    page_url: str
    bundle_url: str
    bundle_name: str
    bundle_digest: str
    public_key_url: str
    public_key_digest: str


def clean_output(text: str) -> str:
    return ANSI_RE.sub("", text).strip()


def parse_version(text: str) -> Version:
    match = VERSION_RE.search(text)
    if match is None:
        raise UpdateError(f"cannot find an OTAFIX version in: {text!r}")
    major, minor, patch = (
        int(match.group(name)) for name in ("major", "minor", "patch")
    )
    preview_text = match.group("preview")
    channel = 0xFF if preview_text is None else int(preview_text)
    if any(value > 0xFF for value in (major, minor, patch, channel)):
        raise UpdateError("OTAFIX version component exceeds one byte")
    if preview_text is not None and not 1 <= channel <= 0xFE:
        raise UpdateError("preview number must be in 1..254")
    label = f"{major}.{minor}.{patch}"
    if preview_text is not None:
        label += f"-preview.{channel}"
    return Version(major, minor, patch, channel, label)


def parse_identity(text: str) -> NodeIdentity:
    match = IDENTITY_RE.search(clean_output(text))
    if match is None:
        raise UpdateError(f"node did not report a valid bootloader identity: {text!r}")
    return NodeIdentity(
        match.group("board").upper(),
        match.group("target").upper(),
        match.group("name"),
        match.group("crc").upper(),
        int(match.group("abi")),
        int(match.group("caps"), 16),
    )


def parse_staged(text: str) -> tuple[str, str]:
    match = STAGED_RE.search(clean_output(text))
    if match is None:
        raise UpdateError("node did not report a complete staged bootloader package")
    return match.group("mid").upper(), match.group("hash").upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_digest(asset: dict[str, Any]) -> str:
    digest = str(asset.get("digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise UpdateError(f"release asset lacks a SHA-256 digest: {asset.get('name')}")
    return digest.split(":", 1)[1].lower()


def fetch_latest_release() -> Release:
    request = Request(
        LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "otafix-mota-updater",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    assets = payload.get("assets", [])
    bundles = [asset for asset in assets if BUNDLE_RE.fullmatch(asset.get("name", ""))]
    keys = [
        asset for asset in assets
        if asset.get("name") == "OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt"
    ]
    if len(bundles) != 1 or len(keys) != 1:
        raise UpdateError("latest release does not contain one signed mOTA bundle and key")
    bundle, public_key = bundles[0], keys[0]
    tag = str(payload["tag_name"])
    return Release(
        tag=tag,
        version=parse_version(tag),
        page_url=str(payload.get("html_url") or LATEST_PAGE),
        bundle_url=str(bundle["browser_download_url"]),
        bundle_name=str(bundle["name"]),
        bundle_digest=asset_digest(bundle),
        public_key_url=str(public_key["browser_download_url"]),
        public_key_digest=asset_digest(public_key),
    )


def download(url: str, destination: Path, expected_digest: str) -> None:
    if destination.is_file() and sha256(destination) == expected_digest:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "otafix-mota-updater"})
    with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    if sha256(temporary) != expected_digest:
        temporary.unlink(missing_ok=True)
        raise UpdateError(f"downloaded SHA-256 mismatch for {destination.name}")
    temporary.replace(destination)


def command_path(value: str, label: str) -> str:
    resolved = shutil.which(value)
    if resolved is None:
        candidate = Path(value).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise UpdateError(f"{label} is not installed or executable: {value}")
    return resolved


def run(command: list[str], timeout: float = 30, check: bool = True) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = clean_output("\n".join(part for part in (result.stdout, result.stderr) if part))
    if check and result.returncode != 0:
        raise UpdateError(output or f"command failed with exit {result.returncode}")
    return output


def mesh_command(meshcli: str, port: str, command: str,
                 attempts: int = 3) -> str:
    last = ""
    for attempt in range(attempts):
        last = run(
            [meshcli, "-q", "-c", "off", "-r", "-s", port, command],
            timeout=30,
            check=False,
        )
        if last and "Unknown command" not in last:
            return last
        if attempt + 1 < attempts:
            time.sleep(1)
    raise UpdateError(f"no usable reply to {command!r}: {last or 'no reply'}")


def query_node(meshcli: str, port: str) -> tuple[Version, str, NodeIdentity]:
    version_reply = mesh_command(meshcli, port, "get bootloader.ver")
    identity_reply = mesh_command(meshcli, port, "ota bootloader")
    version = parse_version(version_reply)
    identity = parse_identity(identity_reply)
    if identity.abi < 3 or identity.caps not in (0x09, 0x0A, 0x0E):
        raise UpdateError(
            f"unsupported bootloader capability: ABI {identity.abi}, caps 0x{identity.caps:02X}"
        )
    return version, version_reply, identity


def choose_target(meshcli: str) -> tuple[str, Version, str, NodeIdentity]:
    candidates: list[tuple[str, Version, str, NodeIdentity]] = []
    print("\nScanning serial ports for self-update-capable OTAFIX targets...")
    for port in serial_ports():
        try:
            version, reply, identity = query_node(meshcli, port)
        except (UpdateError, subprocess.TimeoutExpired):
            continue
        candidates.append((port, version, reply, identity))
    if not candidates:
        raise UpdateError("no self-update-capable OTAFIX target was found")
    labels = [
        f"{identity.name} - OTAFIX {version.label} - {port}"
        for port, version, _, identity in candidates
    ]
    selected = choose("Choose the target node", labels)
    return candidates[labels.index(selected)]


def serial_ports() -> list[str]:
    if os.name != "nt":
        by_id = Path("/dev/serial/by-id")
        if by_id.is_dir():
            ports = [str(path) for path in sorted(by_id.iterdir()) if path.is_symlink()]
            if ports:
                return ports
    ports: list[str] = []
    try:
        from serial.tools import list_ports

        ports.extend(port.device for port in list_ports.comports())
    except ImportError:
        pass
    return list(dict.fromkeys(ports))


def choose(prompt: str, choices: list[str], default: int = 0) -> str:
    if not choices:
        raise UpdateError(f"no choices available for {prompt.lower()}")
    print(f"\n{prompt}")
    for index, choice in enumerate(choices, 1):
        suffix = " [default]" if index - 1 == default else ""
        print(f"  {index}) {choice}{suffix}")
    while True:
        answer = input(f"Select 1-{len(choices)}: ").strip()
        if not answer:
            return choices[default]
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        print("Invalid selection.")


def yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def estimate_update_seconds(bandwidth: float, hops: int,
                            sf: int = 5) -> tuple[int, int, int, int]:
    """Return conservative transfer-low/high and total-low/high estimates."""
    if bandwidth not in (500.0, 250.0, 125.0, 62.5):
        raise UpdateError("bandwidth must be 500, 250, 125, or 62.5 kHz")
    if hops < 1:
        raise UpdateError("hop count must be at least one")
    if not 5 <= sf <= 12:
        raise UpdateError("spreading factor must be in 5..12")

    # Four direct BW500/SF5 physical transfers of this exact 41,330-byte
    # format took 67..89 seconds. Use a rounded 65..100-second baseline,
    # scale by symbol time and add 75% for each store-and-forward RF hop.
    bandwidth_factor = 500.0 / bandwidth
    sf_factor = 2.0 ** (sf - 5)
    hop_factor = 1.0 + 0.75 * (hops - 1)
    low = math.ceil(65 * bandwidth_factor * sf_factor * hop_factor)
    high = math.ceil(100 * bandwidth_factor * sf_factor * hop_factor)
    # Discovery, manifest exchange, verification, apply, and reboot.
    return low, high, low + 40, high + 90


def duration_text(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    if minutes == 0:
        return f"{remainder}s"
    if remainder == 0:
        return f"{minutes}m"
    return f"{minutes}m {remainder}s"


def estimate_text(bandwidth: float, hops: int, sf: int) -> str:
    low, high, total_low, total_high = estimate_update_seconds(
        bandwidth, hops, sf
    )
    return (
        f"transfer {duration_text(low)}-{duration_text(high)}, "
        f"total {duration_text(total_low)}-{duration_text(total_high)}"
    )


def select_package(manifest: dict[str, Any], identity: NodeIdentity) -> dict[str, Any]:
    matches = [
        item for item in manifest.get("packages", [])
        if str(item.get("target_id", "")).upper() == f"0X{identity.target_id}"
    ]
    if len(matches) == 2 and identity.name == "TOWER_V2_OTA":
        board = (
            "heltec_mesh_tower_v2_sdcard"
            if identity.caps == 0x09 else "heltec_mesh_tower_v2"
        )
        matches = [item for item in matches if item.get("board") == board]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UpdateError(f"release has no package for target 0x{identity.target_id}")
    board = choose(
        "Multiple exact-target profiles exist; select the physical storage profile",
        [str(item["board"]) for item in matches],
    )
    return next(item for item in matches if item["board"] == board)


def validate_package_contract(path: Path, package: dict[str, Any],
                              identity: NodeIdentity, release: Release) -> None:
    blob = path.read_bytes()
    if len(blob) != MOTA_SIZE:
        raise UpdateError(f"selected package is {len(blob)} bytes, expected {MOTA_SIZE}")
    if blob[:4] != b"mOTA" or struct.unpack_from("<I", blob, 4)[0] != len(blob):
        raise UpdateError("selected package has an invalid mOTA header")

    manifest = memoryview(blob)[MOTA_HEADER_SIZE:]
    target_id, fw_version, image_size, payload_size = struct.unpack_from(
        "<IIII", manifest, 3
    )
    merkle_root = bytes(manifest[20:24]).hex().upper()
    image_hash = bytes(manifest[24:56]).hex()
    hardware_id = bytes(manifest[57:89]).rstrip(b"\0").decode("ascii")
    signer = bytes(manifest[97:129]).hex().upper()
    packed_version = (
        (release.version.major << 24)
        | (release.version.minor << 16)
        | (release.version.patch << 8)
        | release.version.channel
    )
    expected = (
        manifest[0] == 3
        and manifest[1] == 0x07
        and manifest[2] == 0x12
        and target_id == int(identity.target_id, 16)
        and fw_version == packed_version
        and image_size == 0xA000
        and payload_size == 0xA000
        and manifest[19] == 10
        and manifest[56] == 0
        and bytes(manifest[89:97]) == bytes(8)
        and signer == OFFICIAL_PUBLIC_KEY
        and str(package.get("target_id", "")).upper() == f"0X{target_id:08X}"
        and str(package.get("firmware_version", "")).upper()
        == f"0X{fw_version:08X}"
        and str(package.get("hardware_id", "")) == hardware_id
        and str(package.get("merkle_root", "")).upper() == merkle_root
        and str(package.get("image_sha256", "")).lower() == image_hash
    )
    if not expected:
        raise UpdateError(
            "signed package binary does not match the release, target, or inventory"
        )


def prepare_package(release: Release, identity: NodeIdentity, cache: Path,
                    motatool: str) -> tuple[Path, dict[str, Any]]:
    release_dir = cache / release.tag
    bundle = release_dir / release.bundle_name
    public_key = release_dir / "OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt"
    download(release.bundle_url, bundle, release.bundle_digest)
    download(release.public_key_url, public_key, release.public_key_digest)
    key_text = public_key.read_text(encoding="ascii").strip().upper()
    if key_text != OFFICIAL_PUBLIC_KEY:
        raise UpdateError("latest release public key is not the pinned official key")

    with zipfile.ZipFile(bundle) as archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise UpdateError("release bundle has no valid manifest.json") from exc
        if manifest.get("tag") != release.tag:
            raise UpdateError("bundle tag does not match the latest release")
        if str(manifest.get("signing_public_key", "")).upper() != OFFICIAL_PUBLIC_KEY:
            raise UpdateError("bundle manifest signer is not the official key")
        package = select_package(manifest, identity)
        package_name = str(package.get("file", ""))
        if (
            Path(package_name).name != package_name
            or re.fullmatch(r"update-[A-Za-z0-9_.-]+\.mota", package_name) is None
        ):
            raise UpdateError("bundle inventory contains an unsafe package filename")
        member = f"mota/{package_name}"
        if member not in archive.namelist():
            raise UpdateError(f"bundle is missing {member}")
        package_path = release_dir / package_name
        package_path.write_bytes(archive.read(member))

    if sha256(package_path) != str(package["sha256"]).lower():
        raise UpdateError("selected package SHA-256 does not match the bundle manifest")
    run([motatool, "verify", str(package_path), "--pub", str(public_key)], timeout=60)
    validate_package_contract(package_path, package, identity, release)
    return package_path, package


def serial_text_command(port: str, command: str, companion: bool) -> str:
    try:
        import serial
    except ImportError as exc:
        raise UpdateError("pyserial is required to control the LoRa source") from exc
    start = b"+++MESHCORE-TERM-START\r\n" if companion else b""
    stop = b"+++MESHCORE-TERM-STOP\r\n" if companion else b""
    with serial.Serial(port, 115200, timeout=0.2, write_timeout=2) as stream:
        stream.reset_input_buffer()
        if start:
            stream.write(start)
            stream.flush()
            time.sleep(0.7)
            stream.reset_input_buffer()
        stream.write((command + "\r\n").encode("ascii"))
        stream.flush()
        deadline = time.monotonic() + 3
        output = bytearray()
        while time.monotonic() < deadline:
            chunk = stream.read(4096)
            if chunk:
                output.extend(chunk)
                deadline = min(deadline + 0.1, time.monotonic() + 0.6)
        if stop:
            stream.write(stop)
            stream.flush()
    return clean_output(output.decode("utf-8", "replace"))


def detect_source_mode(meshcli: str, port: str) -> str:
    reply = serial_text_command(port, "ota status", companion=True)
    if "OTA seeder" in reply:
        return "companion"
    reply = mesh_command(meshcli, port, "ota status")
    if "OTA" not in reply:
        raise UpdateError("selected source does not expose MeshCore OTA seeding")
    return "raw"


def source_command(meshcli: str, port: str, mode: str, command: str) -> str:
    if mode == "companion":
        return serial_text_command(port, command, companion=True)
    return mesh_command(meshcli, port, command)


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)


def install_update(args: argparse.Namespace, meshcli: str, motatool: str,
                   target_port: str, current: Version,
                   identity: NodeIdentity, release: Release) -> None:
    package_path, package = prepare_package(release, identity, args.cache, motatool)
    expected_mid = str(package["merkle_root"]).upper()
    expected_hash = str(package["image_sha256"])[:16].upper()
    print(
        f"\nSelected {package['board']}: {package_path.name}\n"
        f"  MID {expected_mid}, image hash {expected_hash}, {package['size']} bytes"
    )

    try:
        target_resolved = Path(target_port).resolve()
    except OSError:
        target_resolved = Path(target_port)
    ports = []
    for port in serial_ports():
        try:
            resolved = Path(port).resolve()
        except OSError:
            resolved = Path(port)
        if port != target_port and resolved != target_resolved:
            ports.append(port)
    source_port = args.source_serial or choose("Choose the LoRa source", ports)
    source_mode = args.source_mode
    if source_mode == "auto":
        print("Detecting source mode...")
        source_mode = detect_source_mode(meshcli, source_port)
    print(f"Source mode: {source_mode}")

    key_reply = mesh_command(meshcli, target_port, "ota key")
    if OFFICIAL_PUBLIC_KEY[:16] not in key_reply:
        if not yes_no("Trust the official OTAFIX release key on this node?", default=True):
            raise UpdateError("official signing key was not trusted")
        mesh_command(meshcli, target_port, f"ota key add {OFFICIAL_PUBLIC_KEY}")
        key_reply = mesh_command(meshcli, target_port, "ota key")
        if OFFICIAL_PUBLIC_KEY[:16] not in key_reply:
            raise UpdateError("node did not retain the official signing key")

    print(
        "\nThe temporary radio must be legal at your location and must match on "
        "source, target, and every intermediate relay."
    )
    hops = args.hops
    if hops is None:
        hop_choice = choose(
            "How many RF hops are between source and target?",
            ["1 hop", "2 hops", "3 hops", "4 hops"],
        )
        hops = int(hop_choice.split()[0])
    if hops < 1:
        raise UpdateError("--hops must be at least one")
    args.hops = hops
    if args.temp_radio:
        temp_radio = args.temp_radio
        fields = temp_radio.split(",")
        if len(fields) != 5:
            raise UpdateError("--temp-radio must be frequency,bw,sf,cr,minutes")
        bandwidth = float(fields[1])
        sf = int(fields[2])
        estimate_update_seconds(bandwidth, hops, sf)
        print(
            f"Estimated {hops}-hop OTAFIX update at BW{bandwidth:g}/SF{sf}: "
            f"{estimate_text(bandwidth, hops, sf)}."
        )
    else:
        bandwidth_choices = [500.0, 250.0, 125.0, 62.5]
        if args.bandwidth is None:
            labels = [
                f"{bandwidth:g} kHz - {estimate_text(bandwidth, hops, args.sf)}"
                for bandwidth in bandwidth_choices
            ]
            selected = choose("Choose bandwidth", labels)
            bandwidth = float(selected.split()[0])
        else:
            bandwidth = args.bandwidth
        estimate_update_seconds(bandwidth, hops, args.sf)
        temp_radio = (
            f"{args.frequency:.3f},{bandwidth:g},{args.sf},5,{args.temp_minutes}"
        )
        print(
            f"Estimated {hops}-hop OTAFIX update at BW{bandwidth:g}/SF{args.sf}: "
            f"{estimate_text(bandwidth, hops, args.sf)}."
        )
        if hops > 1:
            print(
                f"Before continuing, put all {hops - 1} intermediate relay(s) "
                f"on TempRadio {temp_radio}."
            )
    serve_process: subprocess.Popen[str] | None = None
    target_temp = False
    source_temp = False
    with tempfile.TemporaryDirectory(prefix="otafix-serve-") as directory:
        serve_dir = Path(directory)
        shutil.copy2(package_path, serve_dir / package_path.name)
        log_path = args.cache / release.tag / f"motatool-{identity.target_id}.log"
        log_stream = log_path.open("w", encoding="utf-8")
        try:
            target_reply = mesh_command(meshcli, target_port, f"tempradio {temp_radio}")
            if "OK" not in target_reply:
                raise UpdateError(f"target rejected TempRadio: {target_reply}")
            target_temp = True
            source_reply = source_command(
                meshcli, source_port, source_mode, f"tempradio {temp_radio}"
            )
            if "OK" not in source_reply:
                raise UpdateError(f"source rejected TempRadio: {source_reply}")
            source_temp = True

            serve_command = [
                motatool, "serve", "--dir", str(serve_dir),
                "--serial", source_port, "-v",
            ]
            if source_mode == "companion":
                serve_command.append("--companion-terminal")
            serve_process = subprocess.Popen(
                serve_command,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
            )
            time.sleep(2)
            if serve_process.poll() is not None:
                raise UpdateError(f"motatool seeder exited; see {log_path}")

            print(f"Seeder running; log: {log_path}")
            seen = False
            for _ in range(12):
                listing = mesh_command(meshcli, target_port, "ota ls")
                if expected_mid in listing:
                    seen = True
                    break
                time.sleep(3)
            if not seen:
                raise UpdateError(f"target did not discover exact MID {expected_mid}")
            print(f"Target discovered exact MID {expected_mid}; starting LoRa download.")
            pull = mesh_command(meshcli, target_port, f"ota pull {expected_mid} flash")
            if "OK pulling" not in pull and expected_mid not in pull:
                raise UpdateError(f"target rejected pull: {pull}")

            deadline = time.monotonic() + args.transfer_timeout * 60
            while time.monotonic() < deadline:
                if serve_process.poll() is not None:
                    raise UpdateError(f"motatool seeder exited; see {log_path}")
                status = mesh_command(meshcli, target_port, "ota status")
                status_line = next(
                    (line for line in status.splitlines() if "bootloader download:" in line),
                    status,
                )
                print(status_line)
                if expected_mid not in status:
                    raise UpdateError("target status no longer names the requested MID")
                if "ready to install" in status:
                    break
                time.sleep(10)
            else:
                raise UpdateError("LoRa transfer timed out")

            confirmation = mesh_command(meshcli, target_port, "ota bootloader")
            device_mid, device_hash = parse_staged(confirmation)
            if (device_mid, device_hash) != (expected_mid, expected_hash):
                raise UpdateError(
                    "device confirmation does not match the independently verified package"
                )
            print(f"Device confirmed staged MID {device_mid}, hash {device_hash}.")
            if not yes_no(
                f"Install OTAFIX {release.version.label} on {package['board']} now?"
            ):
                print("Install cancelled; the verified package remains staged.")
                return

            try:
                install_reply = mesh_command(
                    meshcli,
                    target_port,
                    f"ota bootloader install {device_mid} {device_hash}",
                    attempts=1,
                )
            except UpdateError as exc:
                # The USB console can disappear before meshcli receives the
                # success reply. Do not resend a privileged command blindly;
                # post-reboot version/result verification resolves the outcome.
                print(f"Install reply was lost ({exc}); verifying reboot outcome.")
            else:
                if "ERR" in install_reply:
                    raise UpdateError(f"bootloader install was refused: {install_reply}")
            stop_process(serve_process)
            serve_process = None
            print("Install armed; waiting for the target to reboot...")
            verify_deadline = time.monotonic() + 90
            last_error = ""
            while time.monotonic() < verify_deadline:
                time.sleep(4)
                try:
                    new_version, _, new_identity = query_node(meshcli, target_port)
                    status = mesh_command(meshcli, target_port, "ota status")
                except (UpdateError, subprocess.TimeoutExpired) as exc:
                    last_error = str(exc)
                    continue
                if new_identity.target_id != identity.target_id:
                    raise UpdateError("bootloader target identity changed after installation")
                if new_version.order != release.version.order:
                    last_error = f"node reports {new_version.label}"
                    continue
                if "blup:C8" not in status or "no download" not in status:
                    last_error = status
                    continue
                print(
                    f"SUCCESS: {package['board']} now runs OTAFIX "
                    f"{new_version.label}; bootloader result blup:C8."
                )
                return
            raise UpdateError(f"post-reboot verification timed out: {last_error}")
        finally:
            stop_process(serve_process)
            log_stream.close()
            if source_temp:
                try:
                    source_command(meshcli, source_port, source_mode, "normalradio")
                except Exception as exc:  # best-effort recovery path
                    print(f"WARNING: source normal-radio restore failed: {exc}", file=sys.stderr)
            if target_temp:
                try:
                    mesh_command(meshcli, target_port, "normalradio", attempts=1)
                except Exception:
                    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-serial", help="target raw CLI serial port")
    parser.add_argument("--source-serial", help="LoRa source serial port")
    parser.add_argument(
        "--source-mode", choices=("auto", "companion", "raw"), default="auto"
    )
    parser.add_argument("--meshcli", default="meshcli")
    parser.add_argument("--motatool", default="motatool")
    parser.add_argument(
        "--cache", type=Path,
        default=Path.home() / ".cache" / "otafix-updater",
    )
    parser.add_argument(
        "--temp-radio",
        help="advanced full override: frequency,bw,sf,cr,minutes",
    )
    parser.add_argument("--frequency", type=float, default=909.950,
                        help="TempRadio frequency in MHz (default: 909.950)")
    parser.add_argument("--sf", type=int, default=5,
                        help="TempRadio spreading factor (default: 5)")
    parser.add_argument(
        "--bandwidth", type=float, choices=(500.0, 250.0, 125.0, 62.5),
        help="TempRadio bandwidth in kHz (menu by default)",
    )
    parser.add_argument("--hops", type=int,
                        help="RF hop count from source to target (menu by default)")
    parser.add_argument("--temp-minutes", type=int, default=120,
                        help="TempRadio duration (default: 120 minutes)")
    parser.add_argument("--transfer-timeout", type=int, default=15,
                        help="LoRa transfer timeout in minutes")
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    meshcli = command_path(args.meshcli, "meshcli")
    if args.target_serial:
        target_port = args.target_serial
        print(f"\nQuerying bootloader on {target_port}...")
        current, version_reply, identity = query_node(meshcli, target_port)
    else:
        target_port, current, version_reply, identity = choose_target(meshcli)
        print(f"\nSelected {target_port}.")
    print(clean_output(version_reply))
    print(
        f"Identity: board={identity.board_id} target={identity.target_id} "
        f"name={identity.name} ABI={identity.abi} caps=0x{identity.caps:02X}"
    )
    print(f"Checking {LATEST_PAGE}...")
    release = fetch_latest_release()
    print(f"Latest release: OTAFIX {release.version.label} ({release.page_url})")

    if current.order < release.version.order:
        state = "UPDATE AVAILABLE"
    elif current.order == release.version.order:
        state = "UP TO DATE"
    else:
        state = "NODE IS NEWER THAN THE PUBLIC RELEASE"
    print(f"Result: {state} ({current.label} -> {release.version.label})")
    if args.check_only:
        return 0 if current.order >= release.version.order else 10

    while True:
        action = choose(
            "OTAFIX menu",
            [
                "Refresh version and latest-release check",
                "Download, verify, and install latest over LoRa",
                "Show bootloader identity",
                "Exit",
            ],
            default=1 if current.order < release.version.order else 0,
        )
        if action.startswith("Refresh"):
            current, _, identity = query_node(meshcli, target_port)
            release = fetch_latest_release()
            relation = "update available" if current.order < release.version.order else "current"
            print(f"Installed {current.label}; latest {release.version.label}: {relation}.")
        elif action.startswith("Download"):
            if current.order >= release.version.order:
                print(
                    "No newer public bootloader is available. The device enforces "
                    "strictly increasing signed bootloader versions."
                )
                continue
            motatool = command_path(args.motatool, "motatool")
            install_update(
                args, meshcli, motatool, target_port, current, identity, release
            )
            current, _, identity = query_node(meshcli, target_port)
            release = fetch_latest_release()
        elif action.startswith("Show"):
            print(
                f"Installed OTAFIX {current.label}: board={identity.board_id}, "
                f"target={identity.target_id}, name={identity.name}, "
                f"crc={identity.crc}, ABI={identity.abi}, caps=0x{identity.caps:02X}"
            )
        else:
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UpdateError, OSError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
