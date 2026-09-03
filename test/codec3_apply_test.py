#!/usr/bin/env python3
"""Generate independent codec-3 fixtures and run a compiled flash simulator."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib


HERE = Path(__file__).resolve().parent


def main() -> None:
    original = (HERE / "vectors" / "delta.mota").read_bytes()
    size = struct.unpack_from("<I", original, 23)[0]
    block = 1 << original[27]
    offset = 205 + 4 * ((size + block - 1) // block)
    patch = original[offset:offset + size]
    geometry = []
    pos = 1
    for _ in range(5):
        byte = patch[pos]
        pos += 1
        value, shift = byte & 63, 6
        while byte & 128:
            byte = patch[pos]
            pos += 1
            value |= (byte & 127) << shift
            shift += 7
        geometry.append(value)

    # The original 537-byte CRLE fixture does not compress with fixed Huffman.
    # detools permits trailing padding (also exercised by readback_test.c).
    # Padding provides two genuinely compressed records, the last a short chunk,
    # while retaining the exact committed base, decoded patch, and target image.
    assert len(patch) < 1024
    patch += bytes(1536 - len(patch))
    header = b"DIP1" + bytes([1, 1]) + struct.pack("<H6I", 1024, len(patch), *geometry)
    raw, compressed = [], []
    for start in range(0, len(patch), 1024):
        chunk = patch[start:start + 1024]
        encoder = zlib.compressobj(9, zlib.DEFLATED, -10, 8, zlib.Z_FIXED)
        encoded = encoder.compress(chunk) + encoder.flush()
        assert encoded[0] & 7 == 3 and len(encoded) < len(chunk)
        raw.append(struct.pack("<H", len(chunk) | 0x8000) + chunk)
        compressed.append(struct.pack("<H", len(encoded)) + encoded)

    def container(records: list[bytes]) -> bytes:
        payload = header + b"".join(records)
        manifest = bytearray(original[:205])
        struct.pack_into("<I", manifest, 23, len(payload))
        manifest[64] = 3
        # These tests start at APRV: the approving application owns signature/
        # Merkle verification. Leaf contents are immaterial to this entry point.
        leaves = bytes(4 * ((len(payload) + block - 1) // block))
        result = manifest + leaves + payload + b"vk496"
        struct.pack_into("<I", result, 4, len(result))
        return bytes(result)

    with tempfile.TemporaryDirectory(prefix="otafix-codec3-") as temp:
        paths = []
        for name, records in (("raw", raw), ("compressed", compressed),
                              ("mixed", [raw[0], compressed[1]])):
            path = Path(temp) / f"{name}.mota"
            path.write_bytes(container(records))
            paths.append(str(path))
        executables = sys.argv[1:] or [str(HERE / "codec3_apply_test")]
        for executable in executables:
            subprocess.run([str(Path(executable).resolve()), *paths], cwd=HERE, check=True)


if __name__ == "__main__":
    main()
