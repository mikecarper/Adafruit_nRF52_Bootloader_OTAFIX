# OTAFIX 2.4.12

Stable bootloader release. Source tag: `v0.11.0-OTAFIX2.4.12`.
Packed production version: `0x02040CFF`.

[Download OTAFIX 2.4.12](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/v0.11.0-OTAFIX2.4.12)
or use the release's exact-board `bootloader-manifest.json`.

## USB recovery fixes

- Fix intermittent control-transfer failures while malformed USB mass-storage
  commands, short reads, phase errors and stall recovery run concurrently.
  Keep CDC recovery usable after rejected mass-storage commands.
- Discard rejected OUT payloads in bounded chunks, report failed commands with
  the correct residue and sense, and clear retired command state on BOT reset.
- Backport nRF52 USB DMA, DMA-safe control-request and stale OUT fixes. Cancel
  retired DMA work before reusing buffers and preserve endpoint ownership
  through reset and clear-halt recovery.
- Keep the synthetic `CURRENT.UF2` disk extent read-only during mounted writes.
  Derive its size from the installed application when valid and freeze that
  extent for the mounted session. A saved `CURRENT.UF2` copied back as a new
  file remains supported.
- Keep TinyUSB stopped after USB probing falls back to Bluetooth DFU, including
  delayed USB power events. All existing board-bound update checks remain.

## Board and build changes

- Correct the T1000-E active-high button and require a three-second hold for
  USB-first recovery. Releasing a qualified hold retains the recovery request;
  a short wake press starts the application. A qualified System OFF wake hold
  can also enter recovery.
- Use board-qualified Arm GNU 15.3.Rel1 for current profiles. Full RAK4631
  internal/RAM/NOR/SD support fits the existing flash envelope without removing
  storage features, validation or recovery transports.
- Keep one compatible normal `*_auto` image per RAK model, with standard
  `3401_DFU` and `4631_DFU` identities. Existing compatible standard RAK
  bootloaders do not require an identity migration.
- Keep the combined `heltec_mesh_tower_v2_sdcard` image as the single normal
  MeshTower V2 download. It supports SD-primary and optional internal staging.

## Downloads and updating

- `OTAFIX-2.4.12-bootloader-mota.zip`: 23 signed, exact-profile bootloader
  `.mota` packages, the official public key, inventory and checksums.
- `OTAFIX-2.4.12-R_recovery.zip`: 28 separately labelled recovery profiles.
- Individual board-bound bootloader UF2, combined SoftDevice/bootloader Legacy
  DFU ZIP and SWD HEX files, plus exact-board download metadata and checksums.
- MeshCore Open is distributed separately; this release contains no Android
  application, field kit or automatic settings erase.

Choose the normal image matching the physical board and installed update
identity. Use signed bootloader `.mota`, the exact-board `update-..._mbr.uf2`,
serial/BLE Legacy DFU or SWD as appropriate. A dedicated bootloader UF2 requires
valid hash-bound application `EndF` metadata before using its fixed staging
range. A combined SoftDevice/bootloader DFU ZIP requires the application to be
reinstalled. Do not treat a completed file copy as proof of activation.

Historical `*_AUTO_DFU` and dedicated external-storage RAK identities still
need the matching local recovery bridge before moving to a normal compatible
image. Recovery is optional repair tooling, not a normal update prerequisite.
See [recovery instructions](recovery-allow-all.md) and
[supported boards](../supported_boards.md).

## RAK15002 qualification scope

The combined RAK4631 image includes authenticated RAK15002 microSD application
apply, selected explicitly by a compatible application's retained handoff.
Bootloader self-updates use internal staging; SD bootloader-update requests
are rejected. Consumers must check the `MOTASDRA` capability rather than infer
SD support from a filename. Current application firmware must implement the
matching contiguous staging and authorization contract before using it.

The pin mapping matches RAK's official RAK4631 example and board definitions:
CS P0.26, SCK P0.03, MOSI P0.30 and MISO P0.29, with unswitched 3.3 V power.
The focused SPI, SD, authorization and isolation mock tests pass.

No RAK15002 was available for physical qualification. Real-card compatibility,
removal/corruption behavior, supported NOR wiring interruption tests and power
cuts during erase/apply remain unqualified. Inclusion in this release does not
claim those tests passed. See the
[RAK storage qualification record](rak4631-all-in-one-qualification.md).
The nine other hardware-pending source ports remain excluded from normal and
recovery downloads; successful compilation does not promote them.

## Verification

The implementation passed all 38 normal qualification builds with both Make
and CMake, including T096/ST7735S and T114/ST7789. No compiler warnings were
reported. The full RAK4631 qualification image used 40,728 of 40,784 executable
bytes, leaving 56 bytes before CF2. Production packages use the stable version
and are checked separately by the exact-tag release workflow.

On the tested RAK4631 and MercerWoodMesh Pi, 1,100 malformed-command concurrency
transitions completed with zero control failures and no GET retries. Short-read,
phase-error, CDC-recovery and rejected 8,192-byte OUT tests also passed.
Nine connected nRF52840 devices received the C8E qualification bootloader;
their original application and SoftDevice readbacks matched byte for byte,
and all returned to their original application versions and roles. Two
bootloader transfers overlapped successfully. The gateway service was restored
and temporary rules, mounts and leases were removed.

These hardware results identify qualification images, not a physical test of
every production file or every supported storage module. Detailed provenance
and limits are in the [2.4.12 qualification report](hardware-qualification-2.4.12.md).
Production signing, package checks and publication use the
[release workflow](../.github/workflows/githubci.yml).
