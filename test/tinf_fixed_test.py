#!/usr/bin/env python3
"""Independent zlib vectors and malformed-input tests for bounded fixed tinf."""

from __future__ import annotations

import os
from pathlib import Path
import random
import shlex
import struct
import subprocess
import sys
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[1]


def fixed_deflate(data: bytes) -> bytes:
    encoder = zlib.compressobj(9, zlib.DEFLATED, -10, 8, zlib.Z_FIXED)
    return encoder.compress(data) + encoder.flush()


def run_tests(executable: Path) -> None:
    # expected bytes = exact success; False = reject; None = arbitrary malformed
    # input whose memory safety is checked by the instrumented native runner.
    cases: list[tuple[bytes, int, bytes | bool | None]] = []
    rng = random.Random(0xD1F1)
    samples = [b"A", b"hello hello hello", b"A" * 1024,
               bytes(range(256)) * 4, b"0123456789abcdef" * 64]
    for _ in range(200):
        seed = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
        samples.append((seed * (1024 // len(seed) + 1))[:rng.randrange(1, 1025)])
    accepted = 0
    for sample in samples:
        encoded = fixed_deflate(sample)
        # Z_FIXED may still choose stored blocks; DIP1 must use raw records then.
        if encoded[0] & 7 != 3:
            cases.append((encoded, len(sample), False))
            continue
        cases.append((encoded, len(sample), sample))
        accepted += 1
        cases.append((encoded + b"\x00", len(sample), False))
        cases.append((encoded, len(sample) + 1, False))
        if len(sample) > 1:
            cases.append((encoded, len(sample) - 1, False))
        for cut in range(len(encoded)):
            cases.append((encoded[:cut], len(sample), False))
    assert accepted > 100

    stored = zlib.compressobj(level=0, wbits=-10)
    stream = stored.compress(b"stored" * 30) + stored.flush()
    assert stream[0] & 7 == 1
    cases.append((stream, 180, False))
    dynamic_rng = random.Random(91)
    dynamic_data = bytes(dynamic_rng.randrange(16) for _ in range(1024))
    dynamic = zlib.compressobj(level=9, wbits=-10)
    stream = dynamic.compress(dynamic_data) + dynamic.flush()
    assert stream[0] & 7 == 5
    cases.append((stream, len(dynamic_data), False))
    padded = fixed_deflate(b"A")
    assert padded[-1] == 0
    cases.append((padded[:-1] + b"\x80", 1, False))

    multi = zlib.compressobj(level=9, wbits=-10, strategy=zlib.Z_FIXED)
    stream = multi.compress(b"first" * 50) + multi.flush(zlib.Z_SYNC_FLUSH)
    stream += multi.compress(b"second" * 50) + multi.flush()
    assert stream[0] & 1 == 0
    cases.append((stream, 650, False))
    cases.append((b"", 0, False))
    cases.append((fixed_deflate(b"A"), 0, False))
    for size in range(1, 65):
        for _ in range(20):
            cases.append((bytes(rng.randrange(256) for _ in range(size)), 1024, None))

    batch = b"".join(struct.pack("<II", len(encoded), size) + encoded
                     for encoded, size, _ in cases)
    output = subprocess.run([str(executable)], input=batch, stdout=subprocess.PIPE,
                            check=True).stdout
    pos = 0
    for index, (_, size, expected) in enumerate(cases):
        result = struct.unpack_from("<i", output, pos)[0]
        actual = output[pos + 4:pos + 4 + size]
        pos += 4 + size
        if expected is False:
            assert result != 0, (index, "accepted invalid input")
        elif isinstance(expected, bytes):
            assert result == 0 and actual == expected, (index, size, result)
    assert pos == len(output)
    print(f"tinf fixed-profile tests passed ({accepted} compressed vectors, {len(cases)} cases)")


def main() -> None:
    if len(sys.argv) > 1:
        run_tests(Path(sys.argv[1]).resolve())
        return
    # Direct invocation remains convenient; make passes its own CFLAGS-built
    # runner, including ASan/UBSan, rather than hiding a second unsanitized build.
    with tempfile.TemporaryDirectory(prefix="otafix-tinf-") as temp:
        executable = Path(temp) / ("tinf_test.exe" if os.name == "nt" else "tinf_test")
        compiler = shlex.split(os.environ.get("CC", "gcc"))
        flags = shlex.split(os.environ.get("CFLAGS", "-std=c11 -O2 -Wall -Wextra -Werror"))
        subprocess.run([*compiler, *flags, "-I", str(ROOT / "src"),
                        str(ROOT / "test" / "tinf_fixed_test.c"),
                        str(ROOT / "src" / "tinf" / "tinflate.c"),
                        "-o", str(executable)], check=True)
        run_tests(executable)


if __name__ == "__main__":
    main()
