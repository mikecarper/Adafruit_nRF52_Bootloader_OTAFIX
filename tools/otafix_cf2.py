#!/usr/bin/env python3
"""Safely inspect or patch CF2 data in OTAFIX BIN/UF2 artifacts.

The upstream JavaScript patcher predates OTAFIX's whole-image BLMF CRC and can
write beyond the compiled CF2 object's zero padding. This wrapper preserves its
configuration syntax and read-only output, but refuses every mutation of a
BLMF-protected image. Legacy mutation is transactional and is accepted only if
all changed bytes remain inside the existing zero-padded CF2 span.
"""

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_BLOCK_SIZE = 512
UF2_DATA_OFFSET = 32
UF2_DATA_MAX = 476

CF2_MAGIC0 = 0x1E9E10F1
CF2_MAGIC1 = 0x20227A79
BLMF_MAGIC0 = 0x464D4C42
BLMF_MAGIC1 = 0x31435243
BLMF_VERSION = 1
BLMF_HEADER_SIZE = 44


class ArtifactError(ValueError):
    pass


class Artifact:
    def __init__(self, data: bytes):
        self.data = data
        self.is_uf2 = len(data) >= 8 and struct.unpack_from("<II", data) == (
            UF2_MAGIC0,
            UF2_MAGIC1,
        )
        self.memory = {}
        self.file_to_address = {}
        if self.is_uf2:
            self._decode_uf2()
        else:
            self.memory = {offset: value for offset, value in enumerate(data)}
            self.file_to_address = {offset: offset for offset in range(len(data))}

    def _decode_uf2(self):
        if len(self.data) % UF2_BLOCK_SIZE:
            raise ArtifactError("UF2 length is not a multiple of 512 bytes")
        for block_offset in range(0, len(self.data), UF2_BLOCK_SIZE):
            block = self.data[block_offset:block_offset + UF2_BLOCK_SIZE]
            magic0, magic1 = struct.unpack_from("<II", block)
            if magic0 != UF2_MAGIC0 or magic1 != UF2_MAGIC1:
                raise ArtifactError(f"invalid UF2 block at file offset 0x{block_offset:X}")
            if struct.unpack_from("<I", block, 508)[0] != UF2_MAGIC_END:
                raise ArtifactError(f"invalid UF2 end magic at file offset 0x{block_offset:X}")
            target, payload_size = struct.unpack_from("<II", block, 12)
            if payload_size == 0 or payload_size > UF2_DATA_MAX:
                raise ArtifactError(f"invalid UF2 payload size {payload_size}")
            if target + payload_size > 0x100000000:
                raise ArtifactError("UF2 target range overflows 32 bits")
            for index in range(payload_size):
                address = target + index
                value = block[UF2_DATA_OFFSET + index]
                old = self.memory.get(address)
                if old is not None and old != value:
                    raise ArtifactError(f"conflicting UF2 data at address 0x{address:08X}")
                self.memory[address] = value
                self.file_to_address[block_offset + UF2_DATA_OFFSET + index] = address

    def read(self, address: int, size: int):
        try:
            return bytes(self.memory[address + offset] for offset in range(size))
        except KeyError:
            return None

    def read_u16(self, address: int):
        data = self.read(address, 2)
        return None if data is None else struct.unpack("<H", data)[0]

    def read_u32(self, address: int):
        data = self.read(address, 4)
        return None if data is None else struct.unpack("<I", data)[0]

    def aligned_addresses(self):
        return sorted(address for address in self.memory if address % 4 == 0)


def _canonical_name(name: bytes) -> bool:
    end = name.find(b"\0")
    return end > 0 and all(0x21 <= value <= 0x7E for value in name[:end]) and all(
        value == 0 for value in name[end:]
    )


def has_structural_blmf(artifact: Artifact) -> bool:
    """Return true for a structurally valid BLMF, even if its CRC is stale."""
    for address in artifact.aligned_addresses():
        if artifact.read_u32(address) != BLMF_MAGIC0 or artifact.read_u32(address + 4) != BLMF_MAGIC1:
            continue
        header = artifact.read(address, BLMF_HEADER_SIZE)
        if header is None:
            continue
        (_, _, version, header_size, image_start, image_size, board_id,
         device_name, _) = struct.unpack("<IIHHIII16sI", header)
        if (
            version != BLMF_VERSION
            or header_size != BLMF_HEADER_SIZE
            or image_size < BLMF_HEADER_SIZE
            or image_size % 4
            or image_start + image_size > 0x100000000
            or board_id in (0, 0xFFFFFFFF)
            or not _canonical_name(device_name)
        ):
            continue
        if artifact.is_uf2:
            if image_start <= address and address + BLMF_HEADER_SIZE <= image_start + image_size:
                return True
        else:
            # A raw file can be either a bootloader-region BIN (offset zero is
            # image_start) or a combined absolute-address BIN (offset zero is
            # flash address zero).
            relative = image_size <= len(artifact.data) and address + BLMF_HEADER_SIZE <= image_size
            absolute = (
                image_start + image_size <= len(artifact.data)
                and image_start <= address
                and address + BLMF_HEADER_SIZE <= image_start + image_size
            )
            if relative or absolute:
                return True
    return False


def cf2_spans(artifact: Artifact):
    """Return (start, safe_end) spans backed by existing zero padding."""
    spans = []
    for address in artifact.aligned_addresses():
        if artifact.read_u32(address) != CF2_MAGIC0 or artifact.read_u32(address + 4) != CF2_MAGIC1:
            continue
        used = artifact.read_u32(address + 8)
        if used is None or used > 1024:
            raise ArtifactError(f"invalid CF2 entry count at 0x{address:08X}")
        entries_end = address + 16 + used * 8
        if artifact.read(entries_end, 8) is None:
            raise ArtifactError(f"truncated CF2 data at 0x{address:08X}")
        safe_end = entries_end
        while artifact.read_u32(safe_end) == 0:
            safe_end += 4
        if safe_end - entries_end < 8:
            raise ArtifactError(f"CF2 data at 0x{address:08X} lacks a zero terminator")
        spans.append((address, safe_end))
    if not spans:
        raise ArtifactError("CF2 data not found")
    return spans


def validate_transaction(original: Artifact, patched: Artifact, spans):
    if original.is_uf2 != patched.is_uf2 or len(original.data) != len(patched.data):
        raise ArtifactError("patcher changed the artifact format or length")
    allowed = [(start + 8, end) for start, end in spans]
    for file_offset, (before, after) in enumerate(zip(original.data, patched.data)):
        if before == after:
            continue
        address = original.file_to_address.get(file_offset)
        if address is None or not any(start <= address < end for start, end in allowed):
            raise ArtifactError(
                f"patcher changed byte outside CF2 bounds at file offset 0x{file_offset:X}"
            )

    patched_starts = [start for start, _ in cf2_spans(patched)]
    original_starts = [start for start, _ in spans]
    if patched_starts != original_starts:
        raise ArtifactError("patcher added, removed, or relocated CF2 data")
    for start, safe_end in spans:
        used = patched.read_u32(start + 8)
        if used is None or used > 1024:
            raise ArtifactError(f"invalid patched CF2 entry count at 0x{start:08X}")
        terminator = start + 16 + used * 8
        if terminator + 8 > safe_end or patched.read(terminator, 8) != b"\0" * 8:
            raise ArtifactError(f"patched CF2 data exceeds its zero-padded span at 0x{start:08X}")


def run_patcher(patcher: Path, image: Path, config: Path | None = None):
    if config is None:
        command = ["node", str(patcher), str(image)]
    else:
        # The bundled Node CLI scopes `fs` inside readBin() but later uses it
        # from main(). Provide the missing global without modifying a submodule.
        shim = 'global.fs=require("fs"); require(process.argv[1])'
        command = ["node", "-e", shim, str(patcher), str(image), str(config)]
    return subprocess.run(command, text=True, capture_output=True, check=False)


def patch_transactionally(patcher: Path, image_path: Path, config_path: Path) -> int:
    original_data = image_path.read_bytes()
    original = Artifact(original_data)
    if has_structural_blmf(original):
        print(
            "otafix_cf2: refusing to patch a BLMF-protected bootloader; "
            "change pinconfig.c and rebuild",
            file=sys.stderr,
        )
        return 2
    spans = cf2_spans(original)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{image_path.name}.otafix-cf2-", dir=image_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        shutil.copy2(image_path, temporary_path)
        result = run_patcher(patcher, temporary_path, config_path)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode:
            return result.returncode
        patched = Artifact(temporary_path.read_bytes())
        validate_transaction(original, patched, spans)
        os.replace(temporary_path, image_path)
        return 0
    except (ArtifactError, OSError) as exc:
        print(f"otafix_cf2: refusing unsafe patch: {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect CF2 or safely patch a legacy, non-BLMF BIN/UF2 artifact"
    )
    parser.add_argument("image", type=Path)
    parser.add_argument("config", nargs="?", type=Path)
    args = parser.parse_args()
    patcher = Path(__file__).resolve().parents[1] / "lib" / "uf2" / "patcher" / "patcher.js"
    try:
        if args.config is not None:
            return patch_transactionally(patcher, args.image, args.config)
        result = run_patcher(patcher, args.image)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    except (ArtifactError, OSError) as exc:
        print(f"otafix_cf2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
