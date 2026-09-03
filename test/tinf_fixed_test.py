#!/usr/bin/env python3
"""Host regression tests for the bootloader's bounded tinf profile."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[1]


def fixed_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(
        level=9, method=zlib.DEFLATED, wbits=-10, memLevel=8, strategy=zlib.Z_FIXED
    )
    return compressor.compress(data) + compressor.flush()


def build_library(output: Path) -> None:
    subprocess.run(
        [
            os.environ.get("CC", "gcc"),
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            str(ROOT / "src" / "tinf" / "tinflate.c"),
            "-o",
            str(output),
        ],
        check=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="otafix-tinf-") as temp:
        suffix = ".dll" if os.name == "nt" else ".so"
        library_path = Path(temp) / ("tinf_test" + suffix)
        build_library(library_path)
        library = ctypes.CDLL(str(library_path))
        inflate = library.tinf_uncompress_fixed
        inflate.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        inflate.restype = ctypes.c_int

        def decode(encoded: bytes, output_size: int) -> tuple[int, bytes]:
            output = (ctypes.c_ubyte * max(output_size, 1))()
            source = (ctypes.c_ubyte * max(len(encoded), 1))()
            if encoded:
                source[: len(encoded)] = encoded
            result = inflate(output, output_size, source, len(encoded))
            return result, bytes(output[:output_size])

        rng = random.Random(0xD1F1)
        samples = [
            b"A",
            b"hello hello hello",
            b"A" * 1024,
            bytes(range(256)) * 4,
            b"0123456789abcdef" * 64,
        ]
        for _ in range(200):
            seed = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
            samples.append((seed * (1024 // len(seed) + 1))[: rng.randrange(1, 1025)])

        accepted = 0
        for sample in samples:
            encoded = fixed_deflate(sample)
            # zlib may select a stored block despite Z_FIXED. Such output is a
            # wrapper-level raw record, not a codec-3 compressed record.
            if encoded[0] & 7 != 3:
                assert decode(encoded, len(sample))[0] != 0
                continue
            result, actual = decode(encoded, len(sample))
            assert result == 0, (len(sample), encoded.hex(), result)
            assert actual == sample
            accepted += 1

            assert decode(encoded + b"\x00", len(sample))[0] != 0
            assert decode(encoded, len(sample) + 1)[0] != 0
            if len(sample) > 1:
                assert decode(encoded, len(sample) - 1)[0] != 0
            for cut in range(len(encoded)):
                assert decode(encoded[:cut], len(sample))[0] != 0

        assert accepted > 100

        stored = zlib.compressobj(level=0, wbits=-10)
        stored_stream = stored.compress(b"stored" * 30) + stored.flush()
        assert stored_stream[0] & 7 == 1
        assert decode(stored_stream, 180)[0] != 0

        dynamic_data = bytes(range(251)) * 4
        dynamic = zlib.compressobj(level=9, wbits=-10)
        dynamic_stream = dynamic.compress(dynamic_data) + dynamic.flush()
        if dynamic_stream[0] & 7 == 5:
            assert decode(dynamic_stream, len(dynamic_data))[0] != 0

        multi = zlib.compressobj(level=9, wbits=-10, strategy=zlib.Z_FIXED)
        multi_stream = multi.compress(b"first" * 50) + multi.flush(zlib.Z_SYNC_FLUSH)
        multi_stream += multi.compress(b"second" * 50) + multi.flush()
        assert multi_stream[0] & 1 == 0
        assert decode(multi_stream, 650)[0] != 0

        # Arbitrary malformed input must fail without writing past the caller's
        # bounded output. The host compiler catches warnings; integration tests
        # run this same loop under ASan/UBSan in the sanitizer target.
        for size in range(1, 65):
            for _ in range(20):
                malformed = bytes(rng.randrange(256) for _ in range(size))
                decode(malformed, 1024)

        if os.name == "nt":
            handle = library._handle
            del decode, inflate, library
            free_library = ctypes.windll.kernel32.FreeLibrary
            free_library.argtypes = [ctypes.c_void_p]
            free_library.restype = ctypes.c_int
            assert free_library(handle)

    print(f"tinf fixed-profile tests passed ({accepted} compressed vectors)")


if __name__ == "__main__":
    main()
