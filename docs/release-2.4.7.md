# OTAFIX 2.4.7

Stable Legacy BLE DFU bootloaders for all 27 curated board profiles. Legacy
application, bootloader, and SoftDevice updates remain supported; the experimental
Secure-only resumable BLE profile is **not** included.

## Downloads

- `OTAFIX-2.4.7-bootloader-mota.zip`: 27 signed, exact-board bootloader `.mota`
  packages, with inventory, checksums, and the official signing public key.
- `OTAFIX-2.4.7-R_recovery.zip`: all 27 `R_` recovery profiles, kept separate
  from normal firmware, with HEX, Legacy DFU ZIP, UF2 updater, and instructions.
- Individual normal-board HEX, Legacy DFU ZIP, and `update-..._mbr.uf2` assets
  remain available. Match the exact board **and storage profile**.

## Changes and validation

The USB-file refresh restores working `CURRENT.UF2` firmware readback and lists
`INFO_UF2.TXT` / `INDEX.HTM` as zero-byte placeholders. The empty files contain
no board information or webpage redirect. USB drive flashing, Serial DFU,
Legacy BLE application/bootloader/SoftDevice updates, and the fixed partitions
are retained. Bootloader mOTA now covers every curated board/storage profile.

Replacement binaries use the immutable source tag
[`v0.11.0-OTAFIX2.4.7`](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/tree/v0.11.0-OTAFIX2.4.7).
The original `0.11.0-OTAFIX2.4.7` tag is unchanged, and the existing release
download links are retained. GitHub's automatic source archives on this release
refer to the original tag; use the linked source tag for the replacement builds.
The packed firmware version remains `0x020407FF`.

Hardened USB/UF2 handoff and flash programming, bootloader image validation,
Legacy BLE transitions, and update-helper behavior. Internal-only boards retain
the fixed 64 KiB hybrid mOTA arena; QSPI and microSD profiles keep their existing
storage-backed paths. Shared-code size reductions preserve the fixed bootloader
partition without removing normal release features.

Baseline 2.4.7 qualification includes Windows/Linux byte-for-byte artifact comparisons,
all-board CI builds, native and sanitizer tests, physical signed LoRa bootloader
updates, and a real flash-plus-retained-RAM application update. The debug-wired
RAK3401 additionally passed ten R_ UF2 recovery/negative tests, including complete
staging and installed-image readbacks. Hardware coverage is representative, not
an all-board or all-transport claim.

The USB-file refresh adds production GhostFAT host coverage of the empty
directory entries, both FATs, complete firmware readback, cached-write rejection,
and a new application transfer, plus the exact T-Echo Lite mOTA failure-mode
suite. Native and sanitizer tests pass; this is not an all-board hardware claim.

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

New QSPI mOTA profiles need a compatible MeshCore application and a locally
installed self-update-capable bootloader before their first remote update.
Their live application must fit below the temporary `0xE0000` bootloader scratch
range; an oversized application is rejected before erase. SenseCAP Solar P1
retains its own carrier identity and must not use the XIAO bootloader package.

Packed stable version: `0x020407FF`. Recovery text: `R_0x020407FF`.
