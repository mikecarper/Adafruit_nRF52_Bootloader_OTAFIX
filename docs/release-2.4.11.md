# OTAFIX 2.4.11

Full normal bootloader release. Packed version: `0x02040BFF`.

## Downloads

- `OTAFIX-2.4.11-bootloader-mota.zip`: 24 signed, exact-profile bootloader
  packages, the official public key, inventory and checksums.
- `OTAFIX-2.4.11-R_recovery.zip`: separately labelled temporary recovery
  bridges for the 29 qualified historical/current profiles.
- Individual bootloader UF2, combined SoftDevice/bootloader DFU ZIP and SWD
  HEX files for the 24 normal profiles, plus `bootloader-manifest.json` for
  exact-board firmware pickers.
- RAK3401 and RAK4631 each have one normal image, named `*_auto`, retaining
  the standard `3401_DFU` / `4631_DFU` identity. Existing standard `board`
  devices use that matching normal image without identity migration.
- MeshCore Open is distributed separately. No Open kit or APK is bundled.

## Bluetooth DFU correction

Both normal and recovery bootloaders include the narrow reset fallback for
the unsafe Bluetooth handoff in older MeshCore applications. When that
handoff faults with `GPREGRET=0xB1`, stackless recovery requests reset-based
Bluetooth DFU with marker `0xA8`. Other fault markers keep their previous
behavior. Installing a MeshCore application with the corrected assembly
handoff remains the lasting application repair.

This preserves Nordic Legacy BLE DFU and USB/serial DFU. If USB is configured
by a computer after bootloader installation, a UF2 drive is expected. With
USB power present but no host configuration, recovery can wait up to 30
seconds before advertising Bluetooth. A combined SoftDevice/bootloader
installation can change the Bluetooth address from the application's A6 to
the bootloader's A7 on the tested RAK4631. Scan again for `4631_DFU` instead
of reconnecting to a cached application address.

## LoRa update features and limits

Every normal profile retains application delta support and signed bootloader
`.mota` self-update. Both RAK adaptive images retain internal bootloader
staging, ABI 3, and the standard identities. External flash is not required
for RAK bootloader updates. Optional external application storage remains
separate from the internal bootloader staging contract.

Full application `.mota` installs require external NOR or microSD. Internal
application deltas must match their base and fit the available staging
space, including the retained RAM arena where supported. A matching
LoRa-enabled MeshCore application is required to receive remote packages.

Installed `*_AUTO_DFU` recovery/historical identities and dedicated external
RAK identities still use a local identity-matching recovery bridge before
moving to the normal image. Recovery's permissive manual-install policy
does not bypass remote signed `.mota` identity, integrity, or layout checks.
Recovery is a temporary tool; restore the normal physical-board image after
repair. There is no automatic LoRa identity migration in this release.

## Application UF2 and settings

This release adds no automatic filesystem erase. A normal application UF2
preserves settings stores; a separate erase image deliberately removes them.
The reported setup-page failure's original state was lost after an erase,
so its cause was not established. Current MeshCore also restores the
four-field radio reply expected by the setup application.

The bootloader UF2 updater still requires valid hash-bound application
`EndF` metadata before erasing its fixed staging range. For an application
without that metadata, use the combined DFU ZIP through a working serial or
Bluetooth connection, then reinstall the application. Use the board's
hardware DFU entry procedure if the installed application's handoff cannot
start DFU. Do not interpret a completed file copy as proof of activation.

## Verification scope

The production build gates include Make and CMake for all 29 production
profiles, T096/ST7735S and T114/ST7789 feature variants, host and sanitizer
tests, signed package verification, and a separate recovery archive audit.
Normal release policy excludes the seven hardware-pending ports, including
`thinknode_m8` with its unverified factory USB identity. They are not added
as normal downloads by this release.

The corrected recovery implementation passed Android nRF Connect and
MeshCore Open application-update qualification. An additional physical test
installed the actual repaired recovery 2.4.11 bootloader ZIP over Bluetooth
with nRF Connect, then installed MeshCore using the same phone. Seven queried
settings and the saved radio tuple were preserved without an erase.

Those tests identify their exact recovery/qualification artifacts; they
are not relabelled as tests of the normal release artifacts. They cover the
tested RAK4631 and phones, not all boards, physical charge-only cables, or
battery-only operation. The earlier normal 2.4.10 release separately passed
signed LoRa bootloader installation on both RAK models.

Recovery correction and physical test details:

https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/feature/ota-delta-apply/docs/release-2.4.11-recovery-correction.md

https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/feature/ota-delta-apply/docs/hardware-qualification-2.4.11-ble-bootloader.md

The separately published all-board recovery-only 2.4.11 prerelease remains
available with its hardware-pending profiles explicitly identified. Its
original tag and repaired asset provenance remain unchanged.

