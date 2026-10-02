# OTAFIX 2.4.11 recovery correction notes

## Release scope

This correction repairs the existing recovery-only prerelease
`R_0.11.0-OTAFIX2.4.11` in place. Both MeshCore Open and Nordic nRF Connect
physical qualification passed with a corrected 2.4.11 qualification image.
The corrected production assets passed the clean-tag build, package validation,
and full download audit described below. Download the assets again if you have
an earlier copy of recovery 2.4.11. This correction creates no 2.4.12 release. The normal latest
release remains OTAFIX 2.4.10.

The original distribution tag `R_0.11.0-OTAFIX2.4.11` remains unchanged.
Corrected production binaries are built from the clean, exact
source-only tag `R_v0.11.0-OTAFIX2.4.11`, with packed version `0x02040BFF`.
The archive inventory identifies that source tag and commit separately
from the original distribution tag, its tag object, and its source commit. The 110
existing release asset names remain unchanged, including
`OTAFIX-2.4.11-R_recovery.zip`; corrected contents receive new checksums.
The release remains a non-latest prerelease. It includes no MeshCore Open
kit or signed bootloader `.mota` bundle. Existing bootloader mOTA features
and their exact-identity validation rules remain enabled.

Dispatch the recovery workflow with `release_tag=R_0.11.0-OTAFIX2.4.11`
and `source_tag=R_v0.11.0-OTAFIX2.4.11`. The source override is required for
this correction: the original distribution source lacks the new validation
and packaging tools. It is preserved as historical provenance, not used to
build the corrected images.

The recovery archive contains 35 board profiles, their local DFU ZIP,
UF2 updater and HEX files, an inventory, instructions, and checksums.
Six included profiles remain unqualified on hardware:
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

The 2.4.11 correction adds a narrow, assembly-only HardFault fallback for this
legacy handoff. It acts only when `GPREGRET` is exactly the Bluetooth direct-jump
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
The guard remains unchanged in the 2.4.11 correction.

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

Confirm `INFO_UF2.TXT` or the application bootloader query identifies recovery
OTAFIX 2.4.11 / packed version `0x02040BFF` after installation. Also match the
installed bootloader manifest CRC against the corrected profile's inventory,
using a bootloader query or readback where available. The original and repaired
assets use the same version, so a version string alone cannot distinguish them.
A completed file copy alone does not prove the replacement bootloader activated.

## Verification

- All 35 included recovery profiles built successfully. Both Heltec display
  variants, T096 and T114, are included. These are qualification builds.
  The production workflow requires clean source-only 2.4.11 tag provenance,
  builds all profiles, checks each HEX/ZIP/UF2 and manifest, and verifies
  the unchanged 110-name asset inventory before replacing release assets.
- All 24 normal release profiles still fit the fixed envelope. They are
  qualification builds and are not distributed as a new normal release.
  The tightest normal RAK4631 `auto` image has 10 bytes left before `0xFDF50`.
  This includes the flash load image for initialized RAM (`.data`): `.text`
  ends at `0xFDEA2`, and the 164-byte `.data` load image ends at `0xFDF46`.
  The linker's printed FLASH-region subtotal alone omits that `.data` load
  image and therefore overstates the executable-region headroom.
- Emulator checks against all 28 linked images and the full bootloader host suite
  passed. The checks exercise recovery with an invalid MSP, preserve the
  retained peer record, verify that non-`B1` faults do not request a reset,
  and check the shared reset priority-group behavior.

### Historical lab-only Nordic DFU qualification

On 1 October 2026, a RAK4631 running the exact published 1.17.1.7 application
was tested with Nordic nRF Connect 4.24.3 on an LG phone
running Android 5.1.1. USB data was connected during this test.

With the original published recovery 2.4.11, the application-to-bootloader
request failed before transferring application data. The phone reported
`Unable to write Op Code 1: device disconnected`, subsequent GATT errors
occurred, no DFU advertisement was observed in a supplemental scan, and the
application version remained unchanged.

With the lab-only 2.4.12 qualification candidate installed and the same old
application restored, the Nordic request produced `4631_DFU` at the same Bluetooth address
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

The physical-test bootloader was a lab-only 2.4.12 qualification artifact,
not an artifact built from the corrected production 2.4.11 source tag.
Its recorded version and checksums are retained as tested; this result must
not be relabeled as a physical test of the repaired 2.4.11 release assets:

| Qualification identifier | Value |
| --- | --- |
| Packed version | `0x02040CFF` |
| Bootloader manifest CRC32 | `5B8F3E90` |
| Make DFU ZIP SHA-256 | `949aba1f296340686edeab1e3bf8f4302c339cec4ce34f993cf292b4feb091fb` |

Use the corrected release archive inventory and checksums for production
downloads. The qualification identifiers above identify only
the tested lab candidate and do not describe the replacement 2.4.11 assets.

### Corrected 2.4.11 Nordic DFU qualification: PASS

On 2 October 2026, the first LG Android 5.1.1 phone ran Nordic nRF Connect
4.24.3/code 114 against the corrected 2.4.11 RAK4631 qualification image,
packed version `0x02040BFF` and manifest CRC `C2A4B64B`. The exact published
1.17.1.7 application was restored before the test. The local CLI `start ota`
returned the correct target Bluetooth address, and USB data was disabled
while USB power remained connected.

Nordic displayed application upload progress at 2%, 20%, 44%, 67%, and 88%,
at approximately 1.2 kB/s, then disconnected and the application restarted.
No Nordic INFO log was available on this phone, so this result uses captured
UI progress and final CLI checks rather than an exact transfer duration or a
captured 100% frame.

Post-update CLI queries confirmed `v1.17.1.8-ble-dfu-test`, bootloader OTAFIX
2.4.11, the saved radio tuple `869.6179809,62.5,8,5`, and all seven unchanged
settings digests. The raw radio reply differs only by the removal of the old
preamble suffix. No erase firmware was used. This qualifies the tested
application/bootloader/phone combination with USB data disabled and power
present; it does not qualify every board or battery-only operation. The
measurements used a qualification image; use the production archive inventory
to identify downloaded release assets.

### MeshCore Open physical qualification: PASS

The second LG phone previously reached the updater in MeshCore Open 9.5.5,
Android legacy build code 26, then `Enable radio updater` rejected a selected
route's hash width before sending the command. Open commit `03b0d707` fixes
that route validation and passes 81 focused tests. Its API 21/ARMv7 build
code 27 was installed with pairing data retained.

The second phone disappeared from the VM's USB inventory during re-enumeration,
before a completed Open transfer could be recorded. The automatic USB
configuration watcher was stopped. Testing then continued on the first LG
phone, also running Android 5.1.1, with Open 9.5.5/code 27 from the same commit.

For that test, the RAK4631 ran the corrected 2.4.11 qualification bootloader,
packed version `0x02040BFF` and manifest CRC `C2A4B64B`, with the exact old
1.17.1.7 application restored. USB data was disabled at the target while USB
power remained connected. The authenticated repeater command used forced
flood routing over a companion and temporary radio settings
`910.525,62.5,7,5`; `Enable radio updater` returned the correct target Bluetooth
address.

On 2 October 2026, Open's native Nordic DFU SDK 2.11.0 initially reported a
GATT 133 write failure and disconnect status 8 on opcode 1. Its automatic retry found bootloader
revision `0800`, negotiated MTU 247, and transferred all 531,708 application
bytes in 68,651 ms. Validation returned success and Open sent Activate/Reset.
Activation was logged at 03:27:16 America/Los_Angeles. Final CLI queries
confirmed `v1.17.1.8-ble-dfu-test (Build: 01-Oct-2026)`, bootloader OTAFIX
2.4.11, the saved radio tuple `869.6179809,62.5,8,5`, and unchanged digests
for all seven compared settings. USB data was restored for verification.
The raw radio reply differs only by the removal of the old preamble suffix,
as in the earlier Nordic comparison.
No erase firmware was used. This qualifies this corrected 2.4.11 image and
application/phone combination, not every board or a battery-only install.
These measurements used a qualification image; use the production archive
inventory to identify downloaded release assets.

Before this corrected 2.4.11 Open test, the RAK4631 was restored to published
normal bootloader 2.4.10 and the fixed qualification application. A supplemental
Linux Bluetooth check reached `4631_DFU` revision `0800` from application
revision `0100`, then returned to the application after enabling bootloader
control notifications and sending its exit request. Final CLI verification
confirmed both versions, the saved radio tuple, and all seven unchanged
settings digests. USB data was restored for those checks. This is a
handoff/exit check, not an Open payload-transfer qualification.

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

## Production publication verification: PASS

On 2 October 2026, [recovery workflow run 36997468388](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/actions/runs/36997468388)
completed all 37 jobs successfully: preparation, 35 board builds, and release
packaging/publication. The source-only tag `R_v0.11.0-OTAFIX2.4.11` resolves
to commit `de88c5fcae72bb00992ac9db7fd144fec150835e`.

The [existing recovery release](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/R_0.11.0-OTAFIX2.4.11)
was repaired using all 110 unchanged asset filenames. Its original
distribution tag remains unchanged: tag object
`b3784854e72b1d3d68e6bef04c1890f251256f59`, source commit
`d6b3edf7d8b58c15187ccae54ea212cfa806d01c`. The release remains a non-latest
prerelease; the normal latest release remains OTAFIX 2.4.10.

Downloaded asset verification passed for all 110 digests, the recovery
archive and its checksums, source/distribution provenance, and all 35
profile inventories. Every HEX, Legacy DFU ZIP, and updater UF2 reconstructs
the same raw bootloader for its profile, and every published
`bootloader_manifest_crc32` matches that reconstructed image. The six
hardware-unqualified profiles listed above remain marked as pending;
`thinknode_m8` remains excluded.

The published `OTAFIX-2.4.11-R_recovery.zip` SHA-256 is:

`803dffcfed20331205d1fbe581593865785a4e53988efd20d777e5fe19b05b3d`

### Production and physically tested RAK4631 images

The physical Bluetooth tests above used the qualification image, not the
subsequently published production file. Both images use packed version
`0x02040BFF` and identity `4631_DFU`, but their full raw images are not identical.

| RAK4631 `board` image | Manifest CRC32 | Raw bootloader SHA-256 |
| --- | --- | --- |
| Physically tested qualification | `C2A4B64B` | `239c23fabcee8478475b3bc3e1c2fc94daa79f386c5fd7ccf980c689220eda7a` |
| Published production | `AA30573D` | `13188cc150682a23bdee1ed7d2340a4ff0e6701b6d18dc347b75803c9ae53ae2` |

The 40,960-byte images differ in exactly eight data bytes: four bytes in the
`CURRENT.UF2` FAT create/update time fields and four bytes in the resulting
whole-image manifest CRC. The remaining 40,952 bytes match, including all
executable instructions, vectors, CF2, version, and update-policy guards.
The production timestamp matches the clean source commit's timestamp.
Production DFU ZIP, published HEX, and workflow artifact comparisons also
passed. This connects the tested implementation to the production image
without relabeling the qualification test as a physical test of the published
artifact or claiming that the complete raw binaries are identical.

### Test node restored

After qualification, the RAK4631 was restored to the published normal 2.4.10
bootloader and the fixed `v1.17.1.8-ble-dfu-test` application. Final CLI
verification confirmed those versions, the saved radio tuple
`869.6179809,62.5,8,5`, and all seven unchanged settings digests. USB data
was re-enabled. No erase firmware was used.

## Published production Bluetooth bootloader test: PASS

An additional [RAK4631 hardware test](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/feature/ota-delta-apply/docs/hardware-qualification-2.4.11-ble-bootloader.md)
on 2 October 2026 used an attached LG Android 5.1.1 phone and nRF Connect
4.24.3 to install the actual published recovery `board` ZIP over Bluetooth.
The phone recorded successful validation and Activate and Reset. Read-only
UF2 information and a subsequent phone firmware-revision read confirmed
`R_0x02040BFF`. The input ZIP SHA-256 was
`3ec67bba63dff7ed44dc1680d0f65b0b371ffd9505f5ed6540ec7de8e4999771`.

With host USB configuration blocked before restart and USB power retained,
recovery advertised as `4631_DFU` at the address ending A7. The previous
application connection used A6, so a cached nRF Connect reconnect to that
address produced GATT 133 after successful activation. A fresh scan and
connection to A7 worked. The same phone then successfully installed the
531,708-byte MeshCore application over Bluetooth. CLI checks confirmed both
versions, all seven unchanged settings digests, and the saved radio tuple.
No erase firmware was used.

This additional test uses the production file; the earlier qualification
image tests above retain their original artifact identities. It qualifies
the tested RAK4631 profile and phone, not every board, a physical charge-only
cable, or battery-only operation. The hardware report records the USB fixture
limits, a detected and restored hub authorization, and final restoration of
the node to normal 2.4.10. Release assets and tags were unchanged by this test.
