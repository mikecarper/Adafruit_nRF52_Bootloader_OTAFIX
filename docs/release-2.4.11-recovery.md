# OTAFIX 2.4.11 recovery only

This is a standalone recovery prerelease for all 38 source board profiles.
It is not marked latest; the normal 2.4.10 release remains latest.

## Recovery policy

- Local BLE DFU, serial DFU, and UF2 bootloader installation no longer require
  matching board identity, version, BLMF/BLM2 manifests, or manifest layout
  declarations while running a recovery image.
- The original RAK4631 `0.9.2-OTAFIX2.3-BP1.4` SoftDevice + bootloader ZIP can
  be installed directly after entering the new recovery bootloader's DFU mode.
  No manifest wrapper or bootloader padding is needed.
- Valid startup vectors, flash bounds, transfer integrity, and SoftDevice
  compatibility checks still apply. Select firmware suitable for the actual
  hardware; permissive recovery does not make another board's pins compatible.
- Remote signed LoRa `.mota` updates retain their exact-board and image checks.
  This release provides local recovery packages, not a new signed mOTA bundle.

## Downloads and order

Download `OTAFIX-2.4.11-R_recovery.zip` and select the image under
`boards/<your-board-profile>/`. Each profile includes a SoftDevice + bootloader
DFU ZIP, merged HEX, and bootloader updater UF2. The same files are also
available individually on the release.

1. Install the recovery image appropriate for the currently installed profile
   using its supported local transport.
2. Enter recovery DFU again and install the desired final bootloader package.
3. Continue using the final normal bootloader; recovery is a temporary bridge.

Do not use an adaptive RAK `_auto` recovery ZIP as the first step on a normal
`*_DFU` device if the installed bootloader requires matching identity. Use the
matching `wiscore_rak4631_board` or `wiscore_rak3401` recovery package first.

## Coverage and verification

All 38 profiles are included. Seven source ports remain pending hardware
qualification: `gat562_mesh_watch13`, `lilygo_t_impulse_plus`,
`lilygo_techo_card`, `meshtiny`, `muzi_base`, `nano_g2_ultra`, and `thinknode_m8`.
The archive inventory identifies them as `qualification_pending_boards`.

Recovery policy tests cover the original 2.3 payload, manifest-free images,
normal-policy rejection, bounds, and invalid startup vectors. Every release
profile is compiled and its version, manifest CRC, and matching HEX/DFU/UF2
payloads are checked. Both Heltec display variants are included. This is build
and package verification, not a new all-board or nRF Connect hardware test.

The release uses exact source tag `R_0.11.0-OTAFIX2.4.11` and packed version
`0x02040BFF`. The archive includes an inventory and per-file SHA256 checksums;
a separate checksum is supplied for the archive itself.
