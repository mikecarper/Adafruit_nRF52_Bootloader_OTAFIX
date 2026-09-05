# OTAFIX 2.4.6

Stable OTAFIX 2.4.6 release based on Adafruit bootloader 0.11.0.

## Retained-RAM application mOTA handoff

OTAFIX 2.4.6 adds a fixed 64 KiB retained-SRAM arena for internal-only
nRF52840 profiles. A compatible MeshCore application can split an authenticated
format-2 application `.mota` into a page-aligned internal-flash prefix and a
suffix of at most 64 KiB at `0x20030000..0x20040000`, then software-reset into
OTAFIX. This extends flash-only staging without requiring QSPI, microSD, or
storage on the LoRa source radio.

The bootloader copies and zero-consumes the 72-byte handoff before trusting it.
It requires:

- an exact software-reset reason and one-shot trigger;
- fixed flash/RAM geometry and exact container length;
- the handoff CRC32 and its complement;
- the application's SHA-256 of the complete container, with only the approval
  bytes normalized to zero; and
- an application-approved package whose signature and Merkle tree were already
  validated, followed by OTAFIX's base-image, output-image, and bounds checks
  before it commits application settings.

A malformed, stale, power-cycled, substituted, or unreadable RAM handoff fails
closed before application flash is invalidated. The bootloader stack is linked
below the arena. Normal applications can still use all physical SRAM when they
are not participating in this handoff.

Make and CMake now enforce the same physical reservation. The Make linker
invocation supplies the arena definition before GNU ld evaluates the linker
script; a regression test locks that ordering so a build cannot compile hybrid
support while accidentally retaining the old full-RAM stack boundary.

The arena is enabled for these internal-only profiles:

`gat562`, `heltec_mesh_pocket`, `heltec_mesh_tower_v2`, `heltec_t096`,
`heltec_t1`, `heltec_t114`, `keepteen_lt1`, `minewsemi_mx25le01`,
`promicro_nrf52840`, `t1000_e`, `thinknode_m3`, `wiscore_rak3401`,
`wiscore_rak4631_board`, and `wismesh_tag`.

QSPI and microSD profiles retain their previous full bootloader-RAM layout and
storage-backed apply paths.

## Upgrade and rollback compatibility

Use only the artifact matching the exact board and storage profile. The signed
bootloader `.mota` and an accepted exact-board `update-..._mbr.uf2` preserve the
installed MeshCore application and node data. Combined SoftDevice-and-
bootloader Legacy DFU packages generally require MeshCore to be reinstalled.
SWD sector programming can preserve untouched sectors, while a chip recover
erases the device.

Version ordering is still unrestricted among bootloaders with compatible
layout capabilities. On an internal-only board, however, OTAFIX 2.4.6 rejects
a bootloader `.mota` candidate that removes the fixed-RAM capability. To
deliberately return such a board from 2.4.6 to 2.4.5 or earlier, use that
release's exact-board dedicated `_mbr.uf2`, Legacy DFU package, or SWD. This
continuity rule does not affect QSPI/microSD profiles.

OTAFIX 2.4.6 includes the 2.4.5 Android `GATT INVALID HANDLE` correction. A
target still running 2.4.3 or 2.4.4 executes its old BLE code during the
one-time upgrade; if Nordic's Android client cannot complete that handoff, use
the exact-board signed `.mota`, dedicated bootloader `_mbr.uf2`, serial Legacy
DFU, the hardened XIAO BLE updater, or SWD.

If OTAFIX 2.4.3 is installed, update the bootloader before copying a MeshCore
application `.uf2` to the mounted UF2 drive. That warning is specific to drive
copy of an application UF2. The dedicated exact-board bootloader
`update-..._mbr.uf2` uses its guarded bootloader path and remains allowed.

## Clearer display recovery state

Space-constrained display builds now show a compact white `DFU` mark in both
USB and BLE recovery modes. This replaces the previous low-cost color bars
without pulling the full font/icon renderer into the fixed bootloader flash
envelope. The mark is rendered directly as RGB565 display lines, and bounded
USB string measurement avoids linking an otherwise unnecessary `strlen`; both
changes keep the signed `heltec_t114` qualification profile within the fixed
envelope. The opt-in, nonrelease combination of signed firmware and dual-bank
DFU uses the board status LED alone because ECC plus the dual-bank
implementation cannot fit alongside a display renderer. MeshCore and the
release artifacts do not enable dual-bank DFU; standard release builds retain
the on-screen mark.

## GAT562 LoRa field kit

The release includes `GAT562-OTAFIX-2.4.6-LoRa-field-kit.zip` and its SHA-256
sidecar. It uses the phone-driven topology:

```text
Android phone -- encrypted Bluetooth --> local Full Companion source
local XIAO or second GAT562 ---- LoRa --> remote GAT562 repeater
```

The remote GAT562 is not USB-connected. The kit includes the isolated arm64
Android field APK, Full Companion ZIP/UF2 files for either a XIAO nRF52840 plus
Wio-SX1262 or a second GAT562 30S Mesh Kit, the exact signed 2.4.6 GAT562
bootloader `.mota`, the official public key and checksums, and the GAT562
LoRa-OTA receiver application for pre-deployment or recovery. The phone owns
the `.mota`; the source bridges it through a 256-byte RAM ring. The XIAO's
2 MB external flash is not used.

Proceed only when the target reports
`board=239A0029 target=D50D2D44 name=GAT562_DFU abi=3 caps=0A`. Stop for legacy
`4631_DFU`, any other target, or the GAT562 Mesh Watch 13. The kit's
`README.txt` records the exact release MID and image-hash prefix and gives the
complete direct/routed recipe.

## Compatibility and validation

- Packed stable bootloader version: `0x020406FF`; nonrelease qualification
  lineage: `0x02040601`.
- All 27 board profiles compile with Arm GNU Toolchain 14.2.Rel1. Linker
  assertions enforce the fixed flash envelope and the internal-only RAM arena.
- Make and CMake cover both display-controller variants: `heltec_t096`
  (ST7735S) and `heltec_t114` (ST7789), including the signed and dual-bank CI
  variants.
- Host tests cover hybrid cross-boundary reads and successful apply, exact
  reset/CRC/geometry/SHA gates, one-shot consumption, RAM-read failure,
  power-cut behavior, candidate capability continuity, and full physical-RAM
  compatibility for ordinary application and recovery images.
- Existing synthetic gates for the 2.4.3 mounted-drive regression, the 2.4.5
  bonded GATT-cache transition, bootloader update authentication, and
  QSPI/microSD paths remain enabled.

No application or node-data format is changed by installing this bootloader.
A MeshCore build must explicitly support the retained-RAM ABI before it will
use the new hybrid staging path; older applications continue using their
existing supported path.

[Full source comparison](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/compare/0.11.0-OTAFIX2.4.5...0.11.0-OTAFIX2.4.6)
