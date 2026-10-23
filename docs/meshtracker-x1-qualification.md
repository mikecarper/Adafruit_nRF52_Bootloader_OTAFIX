# MeshTracker X1 internal-staging qualification candidate

Current release: [OTAFIX 2.4.12](release-2.4.12.md). [Download 2.4.12](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/v0.11.0-OTAFIX2.4.12).

This is a new source port, **not a hardware-qualified download**. Its release
qualification marker remains set. Make, CMake and the board header require an
explicit test build, and Make/CMake additionally require an explicit packed test
version. Normal and recovery release inventories exclude it.

## Confirmed contracts

- The manufacturer [MeshCore installation guide](https://wiki.seeedstudio.com/sensecap_meshtracker_x1_meshcore/)
  documents native USB/UF2, a real button-plus-USB entry sequence, and serial
  bootloader installation. Its [factory bootloader ZIP](https://files.seeedstudio.com/wiki/SenseCAP/Meshcore/MeshTrackerX1/Bootloader.zip)
  has CF2 USB identity **2886:0057** and board ID
  `nRF52840-MeshTracker-X1-v1`. This port preserves those identities.
- [MeshCore PR 3112](https://github.com/meshcore-dev/MeshCore/pull/3112) and
  [Meshtastic PR 10834](https://github.com/meshtastic/firmware/pull/10834)
  agree on red/green/blue LEDs **P0.03/P0.24/P0.28**, active high, and user
  button **P0.06**, active high with a pulldown. Red/green provide the ordinary
  bootloader status LEDs; blue is not touched. The existing common button
  implementation already supports active-high pulldown controls.
- A board-only held-button policy first probes USB using the existing bounded,
  serviced VBUS-settling/host-enumeration wait. A USB host gets UF2/CDC; no VBUS
  falls back to BLE after the 3-second settling bound, and a charger/no host
  falls back after the enumeration timeout. Explicit BLE, serial/UF2 and
  double-reset requests retain precedence. Non-X1 boards keep their existing
  policy; a one-shot cold VBUS read is deliberately avoided.
- The MeshCore board uses **S140 7.3.0**, application base `0x27000`. This port
  selects that SoftDevice version in both build systems, not the default 6.1.1.
  The existing v7 host apply tests exercise this application base.

## Deliberate storage and GPIO limits

The candidate has `MOTA_INTERNAL_BOOTLOADER_UPDATE` only. It supports signed
bootloader self-updates and exact-base application deltas subject to the
internal workspace and retained-RAM limits. It does **not** support full
application mOTA images and does not advertise or probe QSPI.

The X1 physically has external flash. [MeshCore PR 3139](https://github.com/meshcore-dev/MeshCore/pull/3139)
supplies its pins and P0.15 flash enable, but its full boot-time rail contract
is not yet independently verified. Internal staging avoids that dependency
without asserting that the device lacks flash. A later external-storage port
needs its own compatibility decision; `X1INT_DFU` binds this candidate's mOTA
identity to the internal layout.

There are no peripheral GPIO hooks. The flash rail and flash pins, GNSS,
sensors, RTC, haptic driver, buzzer, radio reset and charge/status inputs remain
undriven at reset. This limits speculative electrical behavior; it does not
prove that the product power controller will remain awake throughout DFU.

## Required physical qualification before promotion

Capture the exact production hardware revision, factory USB descriptor and
`INFO_UF2.TXT`, then verify cold USB entry, button-plus-USB entry, BLE entry,
timeout-to-application and operation with and without USB power. Confirm that
the product's power/reset controller does not interrupt lengthy USB, BLE or
LoRa updates without additional GPIO servicing. Verify all untouched rails
and recovery behavior against the schematic/measurements.

Install a matching **internal-staging S140-v7** MeshCore application and test
exact-base delta apply, signed exact-profile bootloader self-update, wrong-base
and cross-board rejection, and interrupted apply/recovery. No mOTA handoff
from an external-staging application is compatible with this candidate.
Preserve identity/settings and perform the ordinary
[hardware checks](meshcore-hardware-coverage.md#hardware-checks-before-promotion)
before removing the pending marker. This work has not flashed hardware.
