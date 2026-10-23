# Update feature audit: OTAFIX 2.4.12

The [current 2.4.12 release](release-2.4.12.md) contains 23 normal profiles
and a separate 28-profile recovery archive. Nine source ports remain pending
and excluded. This is an inventory of compiled update capabilities and
package coverage, not physical qualification of every storage module.

## Findings

- Every normal profile supports application in-place deltas and signed
  bootloader `.mota` self-update. The five historical dedicated RAK profiles
  remain recovery-only. Historical internal-only MeshTower is source-only.
- Full application `.mota` installs require active external NOR or microSD.
  Internal flash and retained RAM support deltas, not full application images.
  Bootloader `.mota` is a separate full 40 KiB image and remains supported on
  internal-only profiles.
- RAK3401 and RAK4631 have one compatible normal `*_auto` image each. They
  retain `3401_DFU` / `4631_DFU`, ABI 3 and primary flags `0A`.
  Bootloader packages always stage internally. RAK4631 additionally supports
  authenticated RAK15002 application apply through its `MOTASDRA` capability;
  it rejects SD bootloader packages. Matching application support is required.
- MeshTower has one normal combined SD/internal profile,
  `heltec_mesh_tower_v2_sdcard`. It retains primary SD flags `09` and adds a
  validated optional internal capability. Existing internal-only installations
  require a one-time local migration; the shared target ID does not authorize
  cross-profile LoRa updates.
- Populated `INFO_UF2.TXT` and `INDEX.HTM`, `CURRENT.UF2` readback, CDC serial,
  application/bootloader UF2 writes, Legacy serial/Bluetooth DFU, and detailed
  Heltec T096/T114/T1 recovery screens remain enabled. The USB fixes do not
  remove these features.
- Standard releases use Legacy BLE DFU, with optional Secure DFU, dual-bank,
  and signed-only Legacy DFU modes disabled. Signed bootloader `.mota`
  authentication remains required independently of `SIGNED_FW`.

Every LoRa path requires a matching OTA-enabled MeshCore application, exact
package identity, trusted signing key and sufficient staging space. Internal
deltas also require the exact running base image. An oversized delta needs
another update path. The retained RAM arena increases delta capacity without
adding internal full-image installation.

## Normal 2.4.12 profiles

`App full` means a full application image. `Yes` describes compiled support,
subject to the application, storage and identity requirements above.

| Exact board/profile | Application staging | App delta | App full | Bootloader mOTA |
| --- | --- | --- | --- | --- |
| `gat562` | Internal / retained RAM | Yes | No | Yes |
| `heltec_mesh_pocket` | Internal / retained RAM | Yes | No | Yes |
| `heltec_mesh_tower_v2_sdcard` | microSD or internal | Yes | microSD only | Yes |
| `heltec_t096` | Internal / retained RAM | Yes | No | Yes |
| `heltec_t1` | Internal / retained RAM | Yes | No | Yes |
| `heltec_t114` | Internal / retained RAM | Yes | No | Yes |
| `keepteen_lt1` | Internal / retained RAM | Yes | No | Yes |
| `lilygo_techo` | External NOR | Yes | Yes | Yes |
| `lilygo_techo_lite` | External NOR | Yes | Yes | Yes |
| `minewsemi_mx25le01` | Internal / retained RAM | Yes | No | Yes |
| `pca10056` | External NOR | Yes | Yes | Yes |
| `promicro_nrf52840` | Internal / retained RAM | Yes | No | Yes |
| `sensecap_solar_p1` | External NOR | Yes | Yes | Yes |
| `t1000_e` | Internal / retained RAM | Yes | No | Yes |
| `thinknode_m1` | External NOR | Yes | Yes | Yes |
| `thinknode_m3` | Internal / retained RAM | Yes | No | Yes |
| `thinknode_m6` | External NOR | Yes | Yes | Yes |
| `wio_tracker_l1` | External NOR | Yes | Yes | Yes |
| `wiscore_rak3401_auto` | Internal / retained RAM or supported NOR | Yes | NOR only | Yes |
| `wiscore_rak4631_auto` | Internal / retained RAM, supported NOR or RAK15002 | Yes | NOR / microSD only | Yes |
| `wismesh_tag` | Internal / retained RAM | Yes | No | Yes |
| `xiao_nrf52840_ble` | External NOR | Yes | Yes | Yes |
| `xiao_nrf52840_ble_sense` | External NOR | Yes | Yes | Yes |

The standard T114 image does not enable its optional external flash footprint.
The combined Tower application selects SD or internal mode explicitly; its
current SD application uses flash-only staging in internal mode. See
[MeshTower migration and qualification](meshtower-dual-storage.md).

## Evidence and limits

- All 38 source profiles passed Make and CMake qualification builds and fit
  their fixed regions. Nine connected nRF52840 devices received the C8E test
  bootloader, with their original applications and SoftDevices read back
  unchanged. Those test images are distinct from the clean-tag production
  packages.
- The RAK4631 USB malformed-command/control-concurrency qualification completed
  1,100 transitions with zero errors and no GET-request retries. Short reads,
  rejected OUT data, phase errors and CDC recovery also passed their targeted
  hardware checks. Host and sanitizer regressions passed.
- RAK15002 wiring agrees with the vendor examples and 34 focused mock cases
  passed. Physical card compatibility, supported NOR wiring and destructive
  power-cut recovery remain untested. See the
  [2.4.12 release notes](release-2.4.12.md) and
  [RAK storage qualification](rak4631-all-in-one-qualification.md).
- Earlier physical Bluetooth and signed LoRa results for compatible RAK
  identities are recorded in the
  [RAK 2.4.10 qualification](hardware-qualification-2.4.10-rak-auto.md).
  The historical 2.4.8/2.4.9 adaptive `*_AUTO_DFU` images lacked bootloader
  self-update and still require the [local recovery bridge](recovery-allow-all.md).
  No older filename proves the new RAK15002 capability.
