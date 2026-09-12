# OTAFIX 2.4.7

Stable Legacy BLE DFU bootloaders for all 27 curated board profiles. Legacy
application, bootloader, and SoftDevice updates remain supported; the experimental
Secure-only resumable BLE profile is **not** included.

## Downloads

- `OTAFIX-2.4.7-bootloader-mota.zip`: 17 signed, exact-board bootloader `.mota`
  packages, with inventory, checksums, and the official signing public key.
- `OTAFIX-2.4.7-R_recovery.zip`: all 27 `R_` recovery profiles, kept separate
  from normal firmware, with HEX, Legacy DFU ZIP, UF2 updater, and instructions.
- Individual normal-board HEX, Legacy DFU ZIP, and `update-..._mbr.uf2` assets
  remain available. Match the exact board **and storage profile**.

## Changes and validation

Hardened USB/UF2 handoff and flash programming, bootloader image validation,
Legacy BLE transitions, and update-helper behavior. Internal-only boards retain
the fixed 64 KiB hybrid mOTA arena; QSPI and microSD profiles keep their existing
storage-backed paths. Shared-code size reductions preserve the fixed bootloader
partition without removing normal release features.

Qualification includes Windows/Linux byte-for-byte artifact comparisons,
all-board CI builds, native and sanitizer tests, physical signed LoRa bootloader
updates, and a real flash-plus-retained-RAM application update. The debug-wired
RAK3401 additionally passed ten R_ UF2 recovery/negative tests, including complete
staging and installed-image readbacks. Hardware coverage is representative, not
an all-board or all-transport claim.

## Recovery and upgrade cautions

R_ images are temporary manual recovery bridges, **not routine upgrades**.
First install R_ for the currently installed bootloader identity, then the normal
image for the physical board. Recovery waives only manual board-identity checks;
CRC, bounds, and compatibility checks remain, and remote `.mota` stays strict.
Do not leave R_ installed. Its UF2 sequence was hardware-qualified; no new
BLE/serial recovery qualification is claimed.

Linux `sync -f` reported I/O errors during the recovery tests; debug readbacks
confirmed the intended outcomes. Verify the active image before retrying a copy.
Combined SoftDevice/bootloader Legacy DFU may require application reinstallation.
UF2 does not migrate the SoftDevice. Existing OTAFIX 2.4.3 users should update
the bootloader before using mounted-drive application UF2 installation.

Packed stable version: `0x020407FF`. Recovery text: `R_0x020407FF`.
