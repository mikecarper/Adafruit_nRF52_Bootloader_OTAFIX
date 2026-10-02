# OTAFIX 2.4.12 recovery candidate notes

## Release scope

This describes the planned recovery-only prerelease under tag
`R_0.11.0-OTAFIX2.4.12`. It is not published: the MeshCore Open physical
transfer test is pending reconnection of the second phone to the test VM.
The normal latest release remains OTAFIX 2.4.10. There is no normal 2.4.12
release, MeshCore Open kit, or signed bootloader `.mota` bundle in this release.
The correction retains the existing bootloader mOTA features and their
exact-identity validation rules.

`OTAFIX-2.4.12-R_recovery.zip` contains 35 board profiles, their local DFU ZIP,
UF2 updater and HEX files, an inventory, instructions, and checksums. As with
2.4.11, six included profiles remain unqualified on hardware:
`gat562_mesh_watch13`, `lilygo_t_impulse_plus`, `lilygo_techo_card`, `meshtiny`,
`muzi_base`, and `nano_g2_ultra`. The archive identifies them under
`qualification_pending_boards`. `thinknode_m8` remains excluded because its
factory USB identity has not been verified.

Recovery images are temporary bridges. Follow the
[recovery instructions](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/feature/ota-delta-apply/docs/recovery-allow-all.md) and use the profile matching
the currently installed bootloader identity before restoring the normal
bootloader for the physical board.

## Bluetooth application-to-bootloader correction

The released RAK4631 MeshCore application
`v1.17.1.7-halo-keymind-cascade-dev-2d03e098` has an unsafe Bluefruit DFU
callback. It selects the main stack pointer (MSP) while its C frame still
belongs to the FreeRTOS process stack pointer (PSP). The compiled callback
then restores that frame using MSP and can fault outside SRAM before
reaching the bootloader entry point.

OTAFIX 2.4.12 adds a narrow, assembly-only HardFault fallback for this legacy
handoff. It acts only when `GPREGRET` is exactly the Bluetooth direct-jump
marker `0xB1`. Without using the damaged stack or reading its exception frame,
it changes that marker to reset-based BLE DFU marker `0xA8` and requests a
hardware reset. Other fault markers retain the existing halt behavior.

The reset routine preserves the ARM priority group and uses the CMSIS reset
key, request bit, and memory barriers. A private `SystemInit` wrapper retains
Nordic's vendor errata logic while sharing this reset implementation. This
keeps the correction inside the fixed bootloader envelope without removing
update features or changing the shared SDK sources.

The matching MeshCore application fix uses a safe assembly handoff. This
bootloader correction provides a route for already installed affected applications;
it does not replace their application code or claim to recover arbitrary
HardFaults. Installing a corrected application remains the lasting repair.

## Installing a bootloader without application staging metadata

The RAK bootloader UF2 updater uses fixed staging flash at `0xE0000`. Before
its first erase, the existing safety guard requires a valid application's
hash-bound `EndF` record to prove that its live image fits below that staging
range. An application without a usable `EndF` cannot prove this,
even if its code is small enough. Its bootloader UF2 update is refused.
The guard remains unchanged in 2.4.12.

This also applies to ordinary non-LoRa application builds that omit `EndF`,
including the fixed Bluetooth qualification application. Correcting the
Bluetooth callback does not itself add that staging metadata.

For that one-time bootstrap, use the recovery profile's combined
SoftDevice/bootloader DFU ZIP through a working serial/CDC or Bluetooth DFU
connection. Force the board into DFU using its supported hardware entry
procedure if the affected application's buttonless entry cannot start it.
The combined ZIP uses application flash as staging and requires the
application to be reinstalled after the bootloader is stable. This is
different from running an application erase firmware; no automatic
filesystem erase is added by this correction.

Confirm `INFO_UF2.TXT` or the application bootloader query shows
`R_0x02040CFF` / OTAFIX 2.4.12 after installation. A completed file copy alone
does not prove the replacement bootloader activated.

## Verification

- All 35 included recovery profiles built successfully. Both Heltec display
  variants, T096 and T114, are included.
- All 24 normal release profiles still fit the fixed envelope. They are
  qualification builds and are not distributed as a normal 2.4.12 release.
  The tightest normal RAK4631 `auto` image has 10 bytes left before `0xFDF50`.
  This includes the flash load image for initialized RAM (`.data`): `.text`
  ends at `0xFDEA2`, and the 164-byte `.data` load image ends at `0xFDF46`.
  The linker's printed FLASH-region subtotal alone omits that `.data` load
  image and therefore overstates the executable-region headroom.
- Emulator checks against all 28 linked images and the full bootloader host suite
  passed. The checks exercise recovery with an invalid MSP, preserve the
  retained peer record, verify that non-`B1` faults do not request a reset,
  and check the shared reset priority-group behavior.

### Physical Nordic DFU qualification

On 1 October 2026, a RAK4631 running the exact published 1.17.1.7 application
was tested with Nordic nRF Connect 4.24.3 on an LG phone
running Android 5.1.1. USB data was connected during this test.

With published recovery 2.4.11, the application-to-bootloader request failed
before transferring application data. The phone reported
`Unable to write Op Code 1: device disconnected`, subsequent GATT errors
occurred, no DFU advertisement was observed in a supplemental scan, and the
application version remained unchanged.

With the 2.4.12 qualification candidate installed and the same old application
restored, the Nordic request produced `4631_DFU` at the same Bluetooth address
after about 11.7 seconds. The application transfer completed at approximately
2.2 kB/s and activated at 17:02:19 America/Los_Angeles. Post-update CLI queries
confirmed `v1.17.1.8-ble-dfu-test` and bootloader OTAFIX 2.4.12.

No erase firmware was used. Seven queried values matched their pre-update
hashes: node name, TX power, latitude, longitude, frequency, airtime factor,
and public key. The radio tuple also matched. Its raw reply changed because
the old reply appended `,preamble=32 (auto)`; restoring that suffix to the
new tuple reproduced the old reply hash exactly.

This result qualifies that application/bootloader/phone combination. It is
not an all-board hardware result or a battery-only test.

The physical-test bootloader was a qualification artifact, not an artifact
built from the clean production release tag:

| Qualification identifier | Value |
| --- | --- |
| Packed version | `0x02040CFF` |
| Bootloader manifest CRC32 | `5B8F3E90` |
| Make DFU ZIP SHA-256 | `949aba1f296340686edeab1e3bf8f4302c339cec4ce34f993cf292b4feb091fb` |

Use the published archive inventory and checksums for production downloads;
the qualification checksum above identifies only the tested candidate.

### MeshCore Open physical qualification

Pending. The second LG phone reached the updater in MeshCore Open 9.5.5,
Android legacy build code 26, then `Enable radio updater` rejected a selected
route's hash width before sending the command. Open commit `03b0d707` fixes
that route validation and passes 81 focused tests. Its API 21/ARMv7 build
code 27 was installed with pairing data retained.

The phone disappeared from the VM's USB inventory during re-enumeration,
before a completed Open transfer could be recorded. The automatic USB
configuration watcher was stopped. Reconnect that second phone before
recording transfer completion and post-update CLI verification. No Open
physical pass is implied by the Nordic result.

While that test is pending, the RAK4631 has been restored to published normal
bootloader 2.4.10 and the fixed qualification application. A supplemental
Linux Bluetooth check reached `4631_DFU` revision `0800` from application
revision `0100`, then returned to the application after enabling bootloader
control notifications and sending its exit request. Final CLI verification
confirmed both versions, the saved radio tuple, and all seven unchanged
settings digests. USB data is restored. This is a handoff/exit check, not an
Open payload-transfer qualification.

## Separate setup-page report

The original report also described setup-page errors after an application UF2
install, followed by success after an erase firmware and reinstall. The
standard MeshCore erase firmware formats InternalFS and ExtraFS; a normal
application UF2 preserves those stores. The original state was lost after
erase, so the specific failed setting, file, or client state is unknown.

Current MeshCore also restores the four-field `get radio` response expected
by the official setup app (commit `ca23d38e`). The old application adds a
preamble suffix, as observed during the settings comparison above. Its CLI
regression checks the restored response contract. This is a concrete older
application compatibility defect, but the original setup-page error was not
captured, so it does not conclusively identify that report's cause.

Current MeshCore identity/settings recovery, common radio persistence, and
companion primary radio persistence suites passed all seven tests. Those
protections and the preserved settings in the Nordic test do not establish
the cause of the earlier setup-page error. This release adds no automatic
erase and does not prescribe one as a Bluetooth repair.
