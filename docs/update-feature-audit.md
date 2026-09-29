# Update feature audit: OTAFIX 2.4.9 and 2.4.10

Audited on 2026-09-29. This is an inventory of compiled update capabilities and
published packages, not a claim of new physical testing on every board.

## Findings

- All 29 normal 2.4.9 profiles include application in-place delta support.
- 27 include signed bootloader self-update. Only `wiscore_rak3401_auto` and
  `wiscore_rak4631_auto` omit it. The compatible normal RAK images in 2.4.10
  restore that capability.
- Full application `.mota` installation requires an external source: NOR flash
  or microSD. The 14 internal-only profiles reject full application packages.
  The adaptive RAK profiles also reject them when using internal staging.
  Retained RAM enlarges delta staging; it does not enable full application
  installation from internal staging.
- The 27 released profiles with bootloader self-update expose empty
  `INFO_UF2.TXT` and `INDEX.HTM` files to save code space. `CURRENT.UF2` readback,
  application/bootloader UF2 writes, and Legacy serial/Bluetooth DFU remain.
  The two released adaptive profiles retain populated info/index files. The
  2.4.10 images restore both files on every profile while retaining fixed
  directory metadata to reduce code size.
- In 2.4.9, Heltec T096, T114 and T1 show only a white `DFU` mark in USB and Bluetooth
  recovery. The richer display with model, version, USB instructions and a
  distinct `BLE OTA` label is compiled out to fit internal bootloader updates.
  The opt-in signed-plus-dual-bank build suppresses even that mark and uses
  the status LED. Normal releases do not select that special combination.
  In 2.4.10, normal, signed-only and dual-only builds restore model/version,
  USB versus Bluetooth mode, and update instructions or the DFU device name.
- Standard releases use Legacy Bluetooth DFU and do not include the experimental
  Secure DFU resume implementation. That separate laboratory option replaces
  Legacy BLE DFU; it is not an extra transport in the release images.
- Normal releases also leave the optional dual-bank and signed-only Legacy DFU
  build modes disabled. Signed bootloader `.mota` authentication remains
  required; it is independent of the `SIGNED_FW` Legacy DFU build option.

Every usable LoRa path also requires a matching OTA-enabled MeshCore application,
matching package identity, trusted signing key where required, and enough staging
space. A bootloader capability does not add LoRa OTA to a non-OTA application.
Internal application deltas need the exact running base image and must fit;
an oversized delta still requires another update path.

## Released 2.4.9: every board/profile

`App full` below means a full **application** image. A signed bootloader package
contains a full 40 KiB bootloader even on internal-only profiles; these are
separate update paths. A `Yes` records compiled support, subject to the matching
application and storage requirements above.

| Exact board/profile | Application staging | App delta | App full | Bootloader mOTA | ABI / storage flags |
| --- | --- | --- | --- | --- | --- |
| `gat562` | Internal | Yes | No | Yes | 3 / 0A |
| `heltec_mesh_pocket` | Internal | Yes | No | Yes | 3 / 0A |
| `heltec_mesh_tower_v2` | Internal | Yes | No | Yes | 3 / 0A |
| `heltec_mesh_tower_v2_sdcard` | microSD | Yes | Yes | Yes | 3 / 09 |
| `heltec_t096` | Internal | Yes | No | Yes | 3 / 0A |
| `heltec_t1` | Internal | Yes | No | Yes | 3 / 0A |
| `heltec_t114` | Internal | Yes | No | Yes | 3 / 0A |
| `keepteen_lt1` | Internal | Yes | No | Yes | 3 / 0A |
| `lilygo_techo` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `lilygo_techo_lite` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `minewsemi_mx25le01` | Internal | Yes | No | Yes | 3 / 0A |
| `pca10056` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `promicro_nrf52840` | Internal | Yes | No | Yes | 3 / 0A |
| `sensecap_solar_p1` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `t1000_e` | Internal | Yes | No | Yes | 3 / 0A |
| `thinknode_m1` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `thinknode_m3` | Internal | Yes | No | Yes | 3 / 0A |
| `thinknode_m6` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `wio_tracker_l1` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `wiscore_rak3401` | Internal | Yes | No | Yes | 3 / 0A |
| `wiscore_rak3401_auto` | Internal or external NOR | Yes | External NOR only | No | 2 / 16 |
| `wiscore_rak3401_rak13302_w25q16` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `wiscore_rak4631_auto` | Internal or external NOR | Yes | External NOR only | No | 2 / 16 |
| `wiscore_rak4631_board` | Internal | Yes | No | Yes | 3 / 0A |
| `wiscore_rak4631_board_rak15001_slot_c` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `wiscore_rak4631_w25q16` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `wismesh_tag` | Internal | Yes | No | Yes | 3 / 0A |
| `xiao_nrf52840_ble` | External NOR | Yes | Yes | Yes | 3 / 0E |
| `xiao_nrf52840_ble_sense` | External NOR | Yes | Yes | Yes | 3 / 0E |

The T114 standard image does not enable its optional external flash footprint.
The MeshTower internal and microSD profiles remain separate; the internal image
does not automatically use an inserted card. Dedicated NOR profiles require
that exact supported storage hardware; only the RAK adaptive profiles select
internal versus external application storage automatically.

## OTAFIX 2.4.10 and recovery builds

Normal release packaging now selects 24 profiles, including one compatible
`*_auto` image for each RAK model. Every selected normal profile requires signed
bootloader mOTA support in both Make and CMake. The release inventory no longer
has an adaptive-profile exception. Five legacy RAK profiles remain buildable
and available in the recovery archive rather than as competing normal downloads.

The normal compatible RAK images retain `3401_DFU` / `4631_DFU`, ABI 3 and flags
`0A`, and always stage bootloader packages internally. Optional application NOR
is advertised separately. Existing standard board installations can update
normally; released `*_AUTO_DFU` identities still need the local recovery bridge.

The separate adaptive `R_` recovery builds deliberately retain those historical
identities and omit LoRa bootloader self-update. They are temporary local
recovery tools. No recovery `.mota` bundle is published.

## Evidence and limits

- Downloaded the published `OTAFIX-2.4.9-bootloader-mota.zip` and verified its
  SHA-256: `6fd7d799873ba6016d37679d9ef3610e62105c2477b49a71933eec12756e625c`.
- Checked all 27 package hashes and embedded image hashes against the released
  inventory; decoded each image's aligned `MOTABLDR` capability record. All
  report ABI 3, codec mask `0005`, and the bootloader-update flag.
- Separately downloaded both normal adaptive 2.4.9 HEX files. Their capability
  records report ABI 2, codec mask `0005`, flags `16`, without bootloader update.
- Compared Make/CMake board definitions at `v0.11.0-OTAFIX2.4.9` and the current
  compatible source. Checked application dispatch in `src/ota_delta.c`: full
  application handling requires an active SD/QSPI source, while internal full
  application packages are explicitly rejected. The shared codec mask alone
  must not be interpreted as support for full applications on internal storage.
- Checked compact-volume selection in `src/usb/uf2/ghostfat.c` and the separate
  Secure DFU build option, and compact display selection in `src/screen.c`.
  No normal board disables Legacy BLE, CDC or UF2 in its Make/CMake profile.

See [the RAK hardware qualification](hardware-qualification-2.4.10-rak-auto.md)
for actual Bluetooth and signed LoRa update results, including direct updates
from the released standard board images on both RAK models.
