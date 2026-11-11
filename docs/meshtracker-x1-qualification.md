# MeshTracker X1 supported internal-staging profile

Current release: [OTAFIX 2.4.12](release-2.4.12.md). [Download 2.4.12](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/v0.11.0-OTAFIX2.4.12).

MeshTracker X1 is supported in the source tree and included in the next normal,
recovery and signed bootloader-mOTA release inventories. This promotion follows
the upstream [OTAFIX 2.5 X1 release](https://github.com/meshtastic/nRF52_Bootloader/releases/tag/0.9.2-OTAFIX2.5)
and [2.6.0 release](https://github.com/meshtastic/nRF52_Bootloader/releases/tag/2.6.0),
which reports X1 testing. Our exact profile retains the factory identity and
internal staging described below. Existing 2.4.12 assets and their manifest are
unchanged; a new release must publish the X1 files before remote downloaders
can offer them. No local physical X1 test is claimed by this promotion.

This change enables bootloader builds and exact-profile package validators and
builders. It does not enable a released matching internal-staging MeshCore X1
application or an application-driven LoRa bootloader-update handoff. That
integration remains separate work. Existing external-staging X1 applications
cannot supply this internal handoff.

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

The supported profile has `MOTA_INTERNAL_BOOTLOADER_UPDATE` only. It supports signed
bootloader self-updates and exact-base application deltas subject to the
internal workspace and retained-RAM limits. It does **not** support full
application mOTA images and does not advertise or probe QSPI.

The X1 physically has external flash. [MeshCore PR 3139](https://github.com/meshcore-dev/MeshCore/pull/3139)
supplies its pins and P0.15 flash enable, but its full boot-time rail contract
is not yet independently verified. Internal staging avoids that dependency
without asserting that the device lacks flash. A later external-storage port
needs its own compatibility decision; `X1INT_DFU` binds this profile's mOTA
identity to the internal layout. The name remains unchanged by promotion, so
existing exact-profile test images and future updates do not acquire a new
target identity. USB board ID is `0x28860057`, mOTA target `0xCDDA9FF9`.

There are no peripheral GPIO hooks. The flash rail and flash pins, GNSS,
sensors, RTC, haptic driver, buzzer, radio reset and charge/status inputs remain
undriven at reset. This limits speculative electrical behavior; it does not
prove that the product power controller will remain awake throughout DFU.

## Physical regression checklist

For future local hardware validation, capture the exact production hardware
revision, factory USB descriptor and
`INFO_UF2.TXT`, then verify cold USB entry, button-plus-USB entry, BLE entry,
timeout-to-application and operation with and without USB power. Confirm that
the product's power/reset controller does not interrupt lengthy USB, BLE or
LoRa updates without additional GPIO servicing. Verify all untouched rails
and recovery behavior against the schematic/measurements.

When a matching **internal-staging S140-v7** X1 application and its LoRa
bootloader-update integration are available, test exact-base delta apply,
signed exact-profile bootloader self-update, wrong-base and cross-board
rejection, and interrupted apply/recovery. No mOTA handoff
from an external-staging application is compatible with this profile.
Preserve identity/settings and perform the ordinary
[hardware checks](meshcore-hardware-coverage.md#hardware-checks-before-promotion)
when testing hardware. This work has not flashed hardware.

## Source verification on 2026-11-11

Fresh CMake builds pass for X1 and the required T096/T114 display variants
with Arm GNU 15.3.Rel1, using explicit test version `0x02040CFE`.
X1 uses 38,450 of 40,784 executable flash bytes, including the flash load
of initialized RAM, and emits a CRC-verified 40 KiB image with
`X1INT_DFU`, S140 FWID `0x0123`, application base `0x27000` and layout ABI 1.
Its native USB bootloader-update UF2 is also generated and the production
image validators accept the exact built binary.

The X1 host suites compile production apply/self-update code and pass, covering internal
and authenticated hybrid deltas, full-application rejection, exact identity,
SoftDevice/layout checks, scratch faults, interrupted apply and MBR handoff.
Release/coverage regressions verify that X1 is no longer pending, retains its
exact mapping and cannot acquire a download unless all real release assets
exist. These are build/host checks, not a local hardware-test report.
