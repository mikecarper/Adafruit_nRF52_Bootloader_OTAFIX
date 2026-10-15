# RAK4631 all-in-one OTAFIX qualification

This is a test candidate, not a published or hardware-qualified release.
The target is `wiscore_rak4631_auto`. Do not flash a failed or oversized build.

## Storage contract

One bootloader supports the existing internal flash and retained-RAM staging,
all three existing RAK NOR selectors, and authenticated RAK15002 microSD
application apply. Bootloader self-updates keep using the existing internal
flash staging path; SD bootloader packages are rejected without probing SD
or falling back to another source. USB CDC, UF2 and BLE DFU recovery remain.

Storage is selected explicitly by the reset handoff, not by probing attached
modules. An SD handoff is consumed and checked before any SD bus access. A
missing, corrupted, wrong-purpose or wrong-image handoff cannot fall back to
an older approved image on internal flash or NOR.

The RAK15002 staging file must be contiguous. A firmware cache/archive file
may be fragmented; application firmware must copy and verify it into a
contiguous install-staging file before handing it to the bootloader. The
72-byte authorization record binds the source sectors, purpose, container
length and normalized SHA-256. Power loss invalidates the retained handoff;
an interrupted destructive apply remains in DFU instead of booting a partial
application.

The deployed `4631_DFU` identity and legacy `MOTABLDR`/`MOTASTOR` bytes are
unchanged. The additive 16-byte `MOTASDRA` capability must be checked by future
application firmware before using SD apply. Old release filenames or the word
`adaptive` do not prove SD support. A successor bootloader must retain the
new capability; missing, incompatible or duplicate valid markers are rejected.

## Hardware boundaries

RAK15002 uses SPIM2 with physical nRF52840 pins CS P0.26, SCK P0.03,
MOSI P0.30 and MISO P0.29. These are physical pins, not a translated Arduino
pin numbering scheme. The radio's separate SPI instance is not used.
The module uses unswitched 3V3; no GPS sensor-slot power rail is toggled.
See the [manufacturer's RAK15002 datasheet](https://docs.rakwireless.com/product-categories/wisblock/rak15002/datasheet/).

RAK15001 and RAK15002 share a chip select and cannot be installed on the same
bus simultaneously. Other supported NOR on CS P0.31 stays deselected before
SD clocks. A supported header-wired NOR uses its existing separate pin tuple.
Internal/RAM apply does not initialize the external bus.

## Qualification gates

- Actual release-mode ARM link must fit the unchanged 40,784-byte code region
  at `0xF4000`, including the initialized `.data` load image; CF2 and the
  fixed BLMF/BLM2 envelope must not move. The linker's FLASH summary alone
  does not include that `.data` load extent.
- Retain the fixed top-of-SRAM 64 KiB handoff arena, no heap, existing USB IDs,
  legacy capability bytes and update identities.
- Native sanitizer tests cover SD full/delta apply, one-shot authorization,
  no fallback, internal/RAM/NOR isolation, internal bootloader updates and
  rejection of SD bootloader-update requests,
  old-loader upgrades and successor capability/identity rejection.
- Protocol-level driver tests must cover selected pin tuples, wake and deep
  sleep, JEDEC rejection, bounded busy waits, failed transport and verified
  approval-word programming without modifying neighboring bytes.
- Build and test the existing RAK3401, Heltec T096/T114 and Tower profiles.
- Before production promotion, physically qualify RAK15002 and every supported
  NOR wiring, including corrupt/removable media, reboot, interrupted erase,
  deliberate power cuts during apply and USB/BLE recovery.

No RAK15002 is available in the current lab. Host tests and ARM builds do not
replace those physical checks. This change builds the bootloader first; it
does not claim that current MeshCore application firmware already stages or
installs SD updates using this new capability.

## Verified test candidate: 2026-10-15

The dirty qualification tree was built with the explicit test-only packed
version `0x02040B7E` (`TEST_0x02040B7E`), not as a production release.
Both ordinary CMake and Make `all` completed, including the manifest CRC
verification and UF2 conversion. Make also generated the SoftDevice/bootloader
Legacy DFU ZIP. The normal candidate preserves `4631_DFU`; the separately
built manual recovery profile preserves its existing `4631_AUTO_DFU` identity.
Qualification did not flash hardware or publish a release.

The combined profile requires Arm GNU Toolchain **15.3.Rel1** with the
profile-specific, standards-conforming size options in
`cmake/mota_compiler_policy.cmake` and `Makefile`. No constant-object merging,
flash-boundary expansion or validation removal is used. Other profiles retain
their GCC 14.2 baseline. CI selects the matching compiler, and Docker can
select it with `--build-arg ARM_GNU_RELEASE=15.3.rel1`.

The normal production USB/BLE version text is the complete packed identifier
`BL_0xXXXXXXXX`, including major, minor, patch and release channel. Full Git
provenance remains in package names; the manifest version and board/USB
identities are unchanged. The larger 15-character `TEST_` label and existing
`R_` recovery label take precedence. This bounds display-text flash usage
even when future stable or preview tags are longer.

Actual executable flash loads, including initialized data:

| Profile | Compiler | Loaded bytes | Margin before CF2 |
| --- | --- | ---: | ---: |
| RAK4631 all-in-one, normal | 15.3.Rel1 | 40,776 | 8 |
| Heltec T096 | 14.2.Rel1 | 40,044 | 740 |
| Heltec T114 | 14.2.Rel1 | 40,376 | 408 |
| RAK3401 adaptive | 14.2.Rel1 | 40,364 | 420 |
| MeshTower V2 SD | 14.2.Rel1 | 40,579 | 205 |

The combined normal image has 40,608 bytes of text plus 168 bytes of
initialized data, ending at `0xFDF48`, before CF2 at `0xFDF50`. Both build
methods retain the linker overlap assertions. The 40,960-byte raw BIN includes
the fixed CF2/manifest envelope and padding; it is not the executable-load
measurement. This is a tight fit: feature changes require another real link,
not an estimate from the reported FLASH percentage.

The original dirty-tree host run passed **378 Python cases and 29 native suites**, with
three documented skips. It included sanitizer-backed validation of the actual
CMake binary; the actual Make binary separately passed the same five admission
groups. Both the current and deployed pre-SD policy admit the intact candidate.
Corrupted CRCs, identities, legacy capabilities and every byte of the SD
capability are rejected as expected. Retained-record tests corrupt every byte
of both 72-byte handoffs and cover repaired-CRC semantic/geometry failures.

The ARM output audit confirms RAM-based NOR/SD DMA command buffers, 255-byte
SPIM2 chunks, both DMA memory barriers, bounded waits, and complete capability
comparisons. The internal staged payload is deliberately unaligned; optimized
field loads rely on the normal Cortex-M reset-default unaligned-access setting.
Supported application handoffs use `NVIC_SystemReset`; arbitrary debugger/PC
entry with `UNALIGN_TRP` enabled is not qualified.

### Rebuild the test candidate

Select the GCC 15.3 toolchain on `PATH`, initialize the existing submodules,
and run from the repository root:

```sh
cmake -S . -B cmake-build-rak-all-in-one-test \
  -DBOARD=wiscore_rak4631_auto \
  -DMOTA_BOOTLOADER_TEST_BUILD=ON \
  -DMOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040B7E
cmake --build cmake-build-rak-all-in-one-test

make BOARD=wiscore_rak4631_auto BUILD=_build-rak-all-in-one-test \
  MOTA_BOOTLOADER_TEST_BUILD=1 \
  MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040B7E all
```

The local test bundle is under `_build-rak4631-all-in-one-test-20261015/`.
Its CMake raw BIN SHA-256 is
`7a8af36c98d329d8da52357e3e7460ba728805334e1fdb6c7c6588d38e0b9622`.
Its CMake bootloader/MBR UF2 SHA-256 is
`89e7542d3e5c4cf0b800474cde97276b220ab10fd63bd33ac42c3d35b24a815f`.
These identify this local test build, not a published release or a hardware
qualification. Physical SD/NOR interruption tests and application-side SD
staging integration remain outstanding.
