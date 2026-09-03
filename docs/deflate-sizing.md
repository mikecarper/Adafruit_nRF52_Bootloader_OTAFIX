# Bootloader DEFLATE size investigation (2026-09-03)

## Decision: bootloader experiment removed

The bootloader DEFLATE experiment has been removed, including the decoder,
record buffers, codec-3 capability, build options and experiment-only tests.
Ordinary CRLE in-place deltas and bootloader updates remain supported. MeshCore
radio-transfer compression and its application-side inflater are unaffected.

The results below are an archived investigation of the removed implementation,
not instructions for enabling a feature in the current tree. Its code and
protocol notes remain recoverable from Git history at `87fcca6`.

The size-optimized full-DEFLATE
prototype did not fit the existing bootloader flash envelope on RAK3401,
T1000-E, T096 or T114. The fixed-Huffman decoder is smaller, but is not a
general drop-in solution: its baseline RAK3401 build still overflows and the
T1000-E sizing build leaves only 28 bytes.

That 28-byte margin is not release qualification. Version/build metadata and
future code changes can consume it; every final artifact must be relinked and
checked. No decoder was enabled in production, no flash boundary was moved,
and no existing USB, BLE, recovery or board feature was removed for this test.

## Complete bootloader sizes

ARM GNU GCC 14.2.1, true C translation units, `-Os`, LTO with one partition,
function/data sections, linker garbage collection, and alignment sorting.
Existing `-fno-ipa-modref` and volatile flash-read protections were retained.
The full decoder additionally used decoder-local `NDEBUG`, retaining all
ordinary malformed-input, tree, distance and buffer-bound checks.

All values below are bytes. The executable flash limit is **40,784 bytes**,
`0xF4000..0xFDF50`; CF2 and BLMF/BLM2 remain in their existing fixed locations.

| Board | Decoder off | Fixed profile | Full prototype |
| --- | ---: | ---: | ---: |
| `wiscore_rak3401` | 39,472 | 40,916 (132 over) | 41,848 (1,064 over) |
| `t1000_e` | 39,312 | 40,756 (28 free) | 41,692 (908 over) |
| `heltec_t096` | 40,148 | 41,576 (792 over) | 42,508 (1,724 over) |
| `heltec_t114` | 40,600 | 42,044 (1,260 over) | 42,980 (2,196 over) |
| `wiscore_rak3401_rak13302_w25q16` | 40,620 | Not measured | Not measured |
| `wiscore_rak4631_w25q16` | 40,668 | Not measured | Not measured |

On the two internal-storage boards, the complete fixed-profile addition costs
1,444 bytes. Full decoding costs 2,376/2,380 bytes: approximately 0.91 KiB more.
These are **integration deltas**, not standalone library sizes; they include
the bounded record reader and preflight validation as well as decompression.

The reported size includes the flash load image for writable `.data` (248
bytes for the four internal/display targets; 476/456 bytes for the two W25Q16
variants respectively). GNU ld's `--print-memory-usage` FLASH line omitted that
load image here, so it was not used as the fit criterion. Successful links
were measured from ELF load addresses; rejected links were measured using
their map files, including `.data`'s load address. Failed trials did not use
an enlarged linker region to produce an installable image.

## Compiler-size trials

The following flags were appended **after** the production flags, in a
supplemental Makefile loaded with `make -f Makefile -f size.mk`. Expanded compile
and LTO-link recipes were checked with `make -n -B`: the final optimization was
`-Oz`, not a later overriding `-Os`. All existing safety flags remained present.

| Appended flags | RAK3401 fixed / full | T1000-E fixed / full |
| --- | ---: | ---: |
| `-Oz -fno-unwind-tables -fno-asynchronous-unwind-tables` | 40,916 / 41,848 | 40,756 / 41,692 |
| `-Oz --param=max-inline-insns-single=10 --param=max-inline-insns-auto=10 --param=inline-unit-growth=5` | 40,996 / not measured | 40,852 / 41,772 |
| `-Oz -fno-inline-small-functions -fno-inline-functions-called-once` | Not measured | Not measured / 44,828 |

None improved on the baseline. The equal plain `-Os`/`-Oz` results were real
compiler outcomes, not ineffective Make overrides. These results led to removal
of the experiment rather than enabling it across these targets or weakening
validation to squeeze in full DEFLATE.

### Reproduction identity

The production sources were the merged bootloader tree at
`adadcd76469c2ad699a96907e54add19e1210bb4`, with TinyUSB at
`f9d99c11d75ac9e6f432ec6cd12284447ebc07de`. Subsequent license/comment and test
changes do not change the production decoder semantics. All trials used the
same explicit qualification metadata:

```text
MOTA_BOOTLOADER_TEST_BUILD=1
MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040405
GIT_VERSION=0.11.0-OTAFIX2.4.3-8-gadadcd7-test-version-0x02040405
GIT_SUBMODULE_VERSIONS=qualified-f9d99c11d
```

These metadata overrides avoided WSL interpreting Windows-absolute submodule
Git paths; they were only for measurement. They are not release identity or
full submodule provenance. The strings occupy 54 and 20 bytes including their
terminating NULs; real final-build metadata can alter the flash result.

The normal board Makefile, linker script and source selection were retained.
`MOTA_DEFLATE_CODEC=0` selected the off baseline; `=1` selected the fixed reader.
For the full prototype only, the supplemental Makefile replaced
`src/tinf/tinflate.o` with the bounded full adapter described below, rather than
linking both decoders. Builds targeted the `.out` ELF directly with
`CROSS_COMPILE` pointing to ARM GNU 14.2.1 and `PYTHON=python3`; no flashing or
release packaging targets ran.

## Full-DEFLATE prototype

The measurement-only implementation uses MeshCore's existing bounded raw tinf
decoder at `src/helpers/ota/tinf/tinflate.c`, as present in MeshCore commit
`dea2ce495f1a850f898bd83eb43020b9845c4568`. It exposes
`tinf_uncompress_exact()` and supports fixed, dynamic, stored and multiple raw
DEFLATE blocks. The adapter retains non-NULL/nonempty input/output checks,
passes the expected decoded size as the destination bound, and requires both
`TINF_OK` and an exactly matching returned output length. No gzip/zlib wrapper,
compressor or external history buffer is linked.

This substitutes only the decompressor for sizing; it is **not** a new wire
protocol implementation or a deployable full-DEFLATE image. Profile 1 remains
fixed-only. A full implementation needs explicit profile/capability negotiation
and matching encoder/app integration before any such packages can be sent.
See [the archived experimental contract](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/87fcca6dff14d50f453cbb305a5c4a348d511915/src/tinf/README.otafix.md).

Full tinf's local tree state is approximately 1,256 bytes on ARM, with another
320-byte code-length array and 32-byte offsets array in its deepest helper
path, before frames and callers. The bootloader's default stack is 8 KiB;
full integration would still need call-chain/interrupt margin qualification.

## Historical investigation verification

The decoder-off merged tree passed the host regression suite and linked the
six baseline boards above. The fixed implementation passed 1,271 real apply
entry-point cases and 28,495 standalone inflater cases under ASan/UBSan;
standalone tests also passed with Windows GCC. The full prototype was used
for code-size measurement, not claimed as hardware or full-protocol testing.

No devices were flashed during this investigation. These results do not imply
that every possible compiler transformation has been exhausted; they establish
the measured trade-off without relying on removed validation or features.
