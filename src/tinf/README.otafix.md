# Optional bootloader DEFLATE experiment

This directory contains a reduced raw-DEFLATE decoder derived from
[jibsen/tinf](https://github.com/jibsen/tinf), version 1.2.1, revision
`57ffa1f1d5e3dde19011b2127bd26d01689b694b`. The original zlib license is in
`LICENSE`; altered source files identify the reduced implementation.

`MOTA_DEFLATE_CODEC` defaults **off**. With it off, the decoder and its record
buffers are not linked and codec 3 is not advertised. The option is an opt-in
bootloader experiment, not a change to ordinary OTA radio-transfer compression.
Enable it with `MOTA_DEFLATE_CODEC=1` in Make or `-DMOTA_DEFLATE_CODEC=ON` in
CMake. A target must still fit its unchanged linker envelope; enabling the
option does not reserve more flash or remove USB/BLE/recovery features.

## Current wire contract

Codec 3 wraps a codec-2 CRLE in-place application patch in a `DIP1` payload.
Its 32-byte little-endian header contains:

| Offset | Field |
| --- | --- |
| 0 | Four-byte `DIP1` magic |
| 4 | Version 1 |
| 5 | Profile 1: fixed Huffman, independent 1 KiB records |
| 6 | Two-byte decoded record size, exactly 1024 |
| 8 | Four-byte total decoded patch size, at most 1 MiB |
| 12, 16, 20, 24, 28 | Four-byte detools memory, segment, shift, source and target sizes |

Each record starts with a two-byte length. Bit 15 selects a raw record and the
remaining bits give its stored length. A raw record must have exactly the
expected decoded length. A compressed record must be strictly shorter and
decode to exactly that length: 1024 bytes, except for a shorter final record.
Incompressible records therefore use the raw form.

A compressed profile-1 record is exactly one final fixed-Huffman DEFLATE
block, with zero padding bits and no trailing bytes. Dynamic Huffman, stored
DEFLATE blocks, and multiple DEFLATE blocks are deliberately rejected. Merely
requesting `Z_FIXED` from an encoder does not guarantee this profile: encoders
may choose a stored block, which must instead be represented as a raw record.

All records are inflated and the duplicated detools geometry is checked before
the application is invalidated. Apply then reads the same bounded records
again, checks exact patch consumption, and verifies the final image hash. Two
static 1024-byte buffers bound record storage; decoder state uses the stack.
No heap or external 32 KiB history buffer is required.

## Full DEFLATE versus the restricted profile

Prefer a bounded full raw-DEFLATE implementation if compiler size optimization
can make the complete bootloader fit. Evaluate the decoder **and** DIP1 reader
and validation overhead, including flash initializers for writable data.
The fixed-only implementation is the smaller fallback, not proof that general
DEFLATE cannot fit any target.

Full DEFLATE must not silently broaden profile 1. Dynamic/stored/multiblock
support needs a separately specified profile and a way for the sender to know
the installed bootloader supports it. The existing codec-3 bit alone does not
distinguish such a future profile from this fixed-only one.

The pending experiment does not add a production package encoder or enable
codec 3 in release builds. Existing format-3 bootloader-update packages retain
their full-image, 1024-byte-block format; this experiment changes application
delta decoding, not bootloader package encoding.

## Verification

`make -C test codec3-check` explicitly builds decoder-enabled and
decoder-disabled application simulators, including the internal shared-slot
configuration. `make -C test check` includes these tests; `make -C test sanitize`
rebuilds them with address/undefined-behavior sanitizers. The standalone inflater
tests exercise valid fixed streams, bounds, truncations, rejected profiles and
malformed input.
