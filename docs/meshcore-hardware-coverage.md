# MeshCore bootloader coverage audit

Audited against the 1.17.1.7 firmware picker on 2026-09-29: **53 nRF52 hardware choices**.
There are **39 choices mapped to 24 released OTAFIX 2.4.10 profiles** and
**14 choices with no exact released profile**. PCA10056 and XIAO Sense are
additional release profiles not present in that firmware catalog.

This audit verifies source compatibility and download identity. It does not
claim that every carrier was physically tested. Sharing an nRF52840 or a
PlatformIO `board` setting does not establish bootloader compatibility.

## Missing aliases corrected

| Firmware hardware choices | Existing bootloader | Evidence |
| --- | --- | --- |
| Ikoka Stick 22/30/33 dBm; Ikoka Nano 22/30/33 dBm; Ikoka Handheld 30 dBm and 096 display | `xiao_nrf52840_ble` | All eight recipes select the Seeed XIAO module and S140 7.3.0. After resolving Arduino pin indices through `g_ADigitalPinMap`, QSPI is P0.21/25/20/24/22/23 and LEDs are P0.26/06/30. Radio PA and display changes do not change those module connections. |
| SolarXiao 30S / 33S | `xiao_nrf52840_ble` | Both inherit `Xiao_nrf52`; their differences are radio limits and RTC scanning. |
| WioTrackerL1-1W / WioTrackerL1Eink | `wio_tracker_l1` | Same L1 module, S140 7.3.0, QSPI P0.21/25/20/24/22/23, LED P1.01 and button P0.08. E-Ink uses the original L1 variant. |

The ordinary XIAO identity is used for these carriers. A physical XIAO Sense
module uses the separate Sense bootloader; do not substitute it based only
on the application recipe, which can share the same Arduino pin map.

Sources: [Ikoka designer](https://github.com/ndoo/ikoka-stick-meshtastic-device),
[Seeed L1 installation guide](https://wiki.seeedstudio.com/get_started_with_meshtastic_wio_tracker_l1/),
and [MeshCore board variants](https://github.com/mikecarper/MeshCore/tree/keymindCascade/variants).

## New variants with confirmed need

These four source ports have `OTAFIX_BOARD_QUALIFICATION_PENDING ON`. CI builds
them but normal release uploads, download manifests and signed release bundles
exclude them. Remove that marker only after the checks below pass. They do not
add or replace binaries in the already published 2.4.10 release.

| New target | Confirmed difference from existing targets | Source contract |
| --- | --- | --- |
| `gat562_mesh_watch13` | GAT562 LED2 / P1.04 drives a vibration motor on Watch13. Its populated W25Q16 also needs external staging, not the non-watch GAT562 internal profile. | No PWM LEDs; hold motor output low. Buttons P0.09/10, QSPI P0.03/26/30/29/28/02. Preserve factory 239A:0029 with unique `GATW13_DFU`. |
| `lilygo_techo_card` | Card has WS2812 LEDs rather than Lite PWM LEDs, and its vendor bootloader preserves NFC. | No PWM LEDs; button P0.24; QSPI P0.04/12/06/08/P1.09/P0.26, rail P0.30 active high. `USE_NFCT=yes` in both build systems. Factory HEX CF2 confirms 239A:00DA; unique `LTECARD_DFU`. |
| `lilygo_t_impulse_plus` | Its flash IO1/IO2 are swapped relative to Lite and its flash rail and LED pins differ. | LED P0.17 active low; button P0.24; QSPI P0.04/12/06/P1.09/P0.08/26; rail P0.14 active high. Factory HEX CF2 confirms 239A:00DA; unique `LTIMP_DFU`. |
| `muzi_base` | Manufacturer bootloader has active-low LEDs and its own 239A:0081 identity, unlike GAT562/RAK. Uno/Duo/SuperIO share the Base PCB. | LEDs P1.04/03 active low; button P0.10; QSPI P0.03/26/30/29/28/02. Retain the manufacturer identity with unique `MUZIB_DFU`. |

Primary references:
[Watch13 schematic](https://github.com/gat-iot/GAT562-family/blob/main/GAT562%20Mesh%20Watch13%20V1.0%20SCH.pdf),
[Card factory bootloader and NFC change log](https://github.com/Xinyuan-LilyGO/T-Echo-Card/tree/main/bootloader),
[T-Impulse Plus factory bootloader](https://github.com/Xinyuan-LilyGO/T-Impulse-Plus/tree/main/bootloader),
[Muzi manufacturer bootloader](https://github.com/muzi-works/Adafruit_nRF52_Bootloader/tree/master/src/boards/muzi_base).

Verification on 2026-09-29: all four ports build successfully with GCC 14.2.1
using both Make and CMake and explicit test version `0x02040A05`. T096 and
T114 also pass both builds. The board-contract tests compile the actual header
macros and execute the motor/flash-power hooks; the release inventory test
confirms that pending profiles have no normal release downloads. These are
build and host-test results, not hardware qualification.
The complete bootloader `make -C test check` suite also passes. Its Secure DFU
inventory count now follows the actual board directories while continuing to
check every board's unique identity and SoftDevice layout.

These vendor bootloaders already use legacy Adafruit USB IDs. The ports retain
those exact identities for factory UF2 compatibility, rather than allocate new
Adafruit IDs. OTAFIX whole-image manifests bind the board ID and unique device
name, including for boards that share a legacy USB identity.

### Hardware checks before promotion

For each new target: record factory INFO_UF2 and USB identity; install via the
supported factory route; verify UF2 disk, INFO/CURRENT reads, CDC and BLE DFU;
check cold USB startup, reset and timeout return to an application; exercise
both physical buttons; verify all flash erase/write/read patterns over the full
device; test full/delta application updates and exact-board bootloader self-update
with power interruption; confirm motor, LEDs and power rails are safe in DFU
and after teardown. Cross-board bootloader packages must be rejected.

## Other omissions kept explicit

No speculative source variant was added for the following boards. Their release
catalog entry has a specific reason instead of silently guessing another board.

| Hardware | Remaining evidence needed / observed mismatch |
| --- | --- | --- |
| Heltec Mesh Solar | MeshCore has LED P0.12, button P1.10 and omits physical QSPI pins. Heltec HT-n5262 and solar BSP definitions found during this audit instead use LED P1.03 and different buttons. Obtain the exact revision schematic and factory identity before choosing flash/power pins. |
| MeshTracker X1 | Its source specifies LED P0.03/24/28, active-high button P0.06, powered QSPI P0.19/20/21/22/23/P1.00 with rail P0.15, and USB 2886:0057. Confirm against the exact manufacturer revision before promoting a port. L1 is not a substitute. |
| Nano G2 Ultra | QSPI P0.08/P1.07/P0.06/26/P1.04/02; button P1.06 and no ordinary LEDs. Confirm the exact factory CF2 identity and reset behavior. |
| ThinkNode M4 | LED P0.13/P1.09 and button P0.04, with separate GPS and I2C power controls. Firmware USB HWIDs include multiple legacy alternatives, so establish the actual factory bootloader identity and power states first. |
| ThinkNode M8 | Flash pin tuple matches M1, but M1 button P1.10 is M8 display enable, and M1 LED P0.14 is M8 GPS PPS. M8 buttons have mixed polarity. Confirm factory identity, correct entry button and rails before adding a port. |
| Wio WM1110 | The application uses a XIAO PlatformIO setting but a different physical map: LED P0.13/14, LR1110 P1.08/10/11/12/13/14/15 and sensor power P0.07. Factory Wio SDK and Tracker variants also have different LED/button layouts. Establish which carrier this firmware targets; neither XIAO nor L1 should be guessed. |
| Meshtiny | Shares some GAT LED/button pins, but has its own manufacturer MT001 identity. Its application does not expose a QSPI pin map, while some product descriptions mention external flash. Verify actual populated flash and board revision; a different name alone is insufficient reason for a new port. |

## Complete released mapping

| OTAFIX profile | Explicit MeshCore hardware names |
| --- | --- |
| `gat562` | `GAT562_30S_Mesh_Kit`, `GAT562_Mesh_EVB_Pro`, `GAT562_Mesh_Tracker_Pro` |
| `heltec_mesh_pocket` | `Mesh_pocket` |
| `heltec_mesh_tower_v2` | `Heltec_tower_v2` |
| `heltec_mesh_tower_v2_sdcard` | `Heltec_tower_v2_sdcard` |
| `heltec_t096` | `Heltec_t096` |
| `heltec_t1` | `Heltec_t1` |
| `heltec_t114` | `Heltec_t114`, `Heltec_t114_without_display` |
| `keepteen_lt1` | `KeepteenLT1` |
| `lilygo_techo` | `LilyGo_T-Echo` |
| `lilygo_techo_lite` | `LilyGo_T-Echo-Lite`, `LilyGo_T-Echo-Lite_non_shell` |
| `minewsemi_mx25le01` | `Minewsemi_me25ls01` |
| `pca10056` | `PCA10056` |
| `promicro_nrf52840` | `ProMicro` |
| `sensecap_solar_p1` | `SenseCap_Solar` |
| `t1000_e` | `t1000e` |
| `thinknode_m1` | `ThinkNode_M1` |
| `thinknode_m3` | `ThinkNode_M3` |
| `thinknode_m6` | `ThinkNode_M6` |
| `wio_tracker_l1` | `WioTrackerL1`, `WioTrackerL1-1W`, `WioTrackerL1Eink` |
| `wiscore_rak3401_auto` | `RAK_3401` |
| `wiscore_rak4631_auto` | `RAK_4631`, `R1Neo` |
| `wismesh_tag` | `RAK_WisMesh_Tag` |
| `xiao_nrf52840_ble` | `Xiao_nrf52`, `ikoka_handheld_nrf_e22_30dbm`, `ikoka_handheld_nrf_e22_30dbm_096`, `ikoka_nano_nrf_22dbm`, `ikoka_nano_nrf_30dbm`, `ikoka_nano_nrf_33dbm`, `ikoka_stick_nrf_22dbm`, `ikoka_stick_nrf_30dbm`, `ikoka_stick_nrf_33dbm`, `solarxiao_30S`, `solarxiao_33S` |
| `xiao_nrf52840_ble_sense` | `Xiao_nrf52_Sense` |

## Complete unavailable mapping

| Proposed / pending profile | MeshCore hardware names |
| --- | --- |
| `gat562_mesh_watch13` | `GAT562_Mesh_Watch13` |
| `heltec_mesh_solar` | `Heltec_mesh_solar` |
| `lilygo_t_impulse_plus` | `LilyGo_T_Impulse_Plus` |
| `lilygo_techo_card` | `LilyGo_T-Echo_Card` |
| `meshtiny` | `Meshtiny` |
| `meshtracker_x1` | `MeshTracker_X1` |
| `muzi_base` | `muzi_base_duo`, `muzi_base_duo_superIO`, `muzi_base_uno`, `muzi_base_uno_superIO` |
| `nano_g2_ultra` | `Nano_G2_Ultra` |
| `thinknode_m4` | `ThinkNode_M4` |
| `thinknode_m8` | `ThinkNode_M8` |
| `wio_wm1110` | `wio_wm1110` |

The release manifest publishes these unavailable entries as metadata only. They
contain no files. Duplicate aliases across either list fail generation. The
MeshCore regression fixture classifies every nRF52 hardware choice in 1.17.1.7.
New hardware must be audited before adding a download recommendation.
