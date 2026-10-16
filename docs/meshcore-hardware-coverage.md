# MeshCore bootloader coverage audit

Current mapping checked on 2026-10-02: **55 explicit nRF52 hardware names**,
including PCA10056 and XIAO Sense beyond the 53-name 1.17.1.7 picker audit.
There are **40 names mapped to 23 normal OTAFIX 2.4.11 profiles**. Of the 15
unavailable names, **12 map to nine pending source ports**, two still require
hardware facts before implementation, and one is the retired internal-only Tower
identity requiring local migration to the combined SD/internal image.

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

These nine source ports have `OTAFIX_BOARD_QUALIFICATION_PENDING ON`.
Qualification CI builds them but production CI, normal release uploads, download
manifests and signed release bundles exclude them. Recovery release archives
also exclude pending profiles. Remove
that marker only after the checks below pass. They do not
add or replace binaries in the already published 2.4.11 release.

| New target | Confirmed difference from existing targets | Source contract |
| --- | --- | --- |
| `gat562_mesh_watch13` | GAT562 LED2 / P1.04 drives a vibration motor on Watch13. Its populated W25Q16 also needs external staging, not the non-watch GAT562 internal profile. | No PWM LEDs; hold motor output low. Buttons P0.09/10, QSPI P0.03/26/30/29/28/02. Preserve factory 239A:0029 with unique `GATW13_DFU`. |
| `lilygo_techo_card` | Card has WS2812 LEDs rather than Lite PWM LEDs, and its vendor bootloader preserves NFC. | No PWM LEDs; button P0.24; QSPI P0.04/12/06/08/P1.09/P0.26, rail P0.30 active high. `USE_NFCT=yes` in both build systems. Factory HEX CF2 confirms 239A:00DA; unique `LTECARD_DFU`. |
| `lilygo_t_impulse_plus` | Its flash IO1/IO2 are swapped relative to Lite and its flash rail and LED pins differ. | LED P0.17 active low; button P0.24; QSPI P0.04/12/06/P1.09/P0.08/26; rail P0.14 active high. Factory HEX CF2 confirms 239A:00DA; unique `LTIMP_DFU`. |
| `muzi_base` | Manufacturer bootloader has active-low LEDs and its own 239A:0081 identity, unlike GAT562/RAK. Uno/Duo/SuperIO share the Base PCB. | LEDs P1.04/03 active low; button P0.10; QSPI P0.03/26/30/29/28/02. Retain the manufacturer identity with unique `MUZIB_DFU`. |
| `nano_g2_ultra` | Designer schematic confirms a distinct flash layout, one user button and no ordinary LEDs. Factory HEX uses 4251:8695, unlike the generic application HWIDs. | No PWM LEDs; button P1.06; QSPI P0.08/P1.07/P0.06/26/P1.04/02; unique `NANOG2_DFU`. Preserve factory `nRF52840-BQ-rev1` identity. |
| `meshtiny` | Manufacturer specifies IS25LP080D and explicitly moves three flash pins away from encoder/buzzer pins. GAT562's flash and second button mappings cannot be reused. | LEDs P1.03/04 active high; side/down buttons P0.09/04; QSPI P0.03/22/27/29/21/02; factory 239A:0029 and `Meshtiny-MT001-Board`; unique `MT001_DFU`. |
| `thinknode_m8` | V0.3-tested source confirms M1's button is M8's display enable and M1's LED is M8's GPS PPS. | Compile-only draft: no PWM LEDs, button P0.12 active low, QSPI P1.14/15/12/13/P0.07/05; unique `TNM8_DFU`. Factory USB identity is unknown; invalid 0000:0000 fixtures prevent a valid bootloader update identity. |
| `meshtracker_x1` | Real factory USB/UF2 and active-high button differ from L1. External-flash rail/reset behavior remains unverified. | Internal-staging S140 7.3.0 qualification candidate; LEDs P0.03/24 active high, button P0.06 with pulldown; preserve factory 2886:0057/`nRF52840-MeshTracker-X1-v1`, unique `X1INT_DFU`. No QSPI or peripheral-rail outputs; explicit test-mode/version guards. |
| `heltec_mesh_solar` | Conflicting LED/flash BSP definitions cannot be copied safely; author-confirmed watchdog revision needs servicing throughout DFU. | Internal-staging S140 6.1.1 qualification candidate with no LED/QSPI/rail outputs, confirmed button P1.10 and DONE P0.09/1 ms pulse/60-second feed. Preserve factory HT-n5262 239A:0071 with unique `SOLARINT_DFU`; explicit test-mode/version guards. |

Primary references:
[Watch13 schematic](https://github.com/gat-iot/GAT562-family/blob/main/GAT562%20Mesh%20Watch13%20V1.0%20SCH.pdf),
[Card factory bootloader and NFC change log](https://github.com/Xinyuan-LilyGO/T-Echo-Card/tree/main/bootloader),
[T-Impulse Plus factory bootloader](https://github.com/Xinyuan-LilyGO/T-Impulse-Plus/tree/main/bootloader),
[Muzi manufacturer bootloader](https://github.com/muzi-works/Adafruit_nRF52_Bootloader/tree/master/src/boards/muzi_base).

The follow-up [seven-board pin provenance audit](seven-board-pin-provenance.md)
records manufacturer references, factory download inspection, git blame,
commit diffs and associated PR discussions for Nano, Meshtiny, M8 and the four
remaining omissions. It distinguishes source confirmation from hardware tests.
The new [X1 internal-staging qualification plan](meshtracker-x1-qualification.md)
avoids the unverified external rail while recording the remaining power/reset
and physical update gates. Internal staging supports exact-base application
deltas and signed bootloader self-update, **not full application images**.
The [Solar internal-staging qualification plan](meshsolar-qualification.md)
similarly avoids all conflicting LED/flash/rail definitions while reusing the
source-confirmed watchdog pulse and the established serviced DFU/apply path.

Verification on 2026-09-29: all four ports build successfully with GCC 14.2.1
using both Make and CMake and explicit test version `0x02040A05`. T096 and
T114 also pass both builds. The board-contract tests compile the actual header
macros and execute the motor/flash-power hooks; the release inventory test
confirms that pending profiles have no normal release downloads. These are
build and host-test results, not hardware qualification.
Nano and Meshtiny also pass both Make and CMake with the same explicit test
version; T096 and T114 were rebuilt with CMake after their addition. Their
compiled pin-contract tests and normal/recovery release inventory tests pass.
The complete bootloader `make -C test check` suite also passes. Its Secure DFU
inventory count now follows the actual board directories while continuing to
check every board's unique identity and SoftDevice layout.
M8 also passes Make and CMake with that explicit test version: 38748 of 40784
executable flash bytes used. T096 and T114 were rebuilt successfully with CMake.
The full host suite passes with M8 included. Its regressions check the V0.3 pins,
peripheral output order, build/version guards and production CI exclusion.

M8 is retained as a compile-only port until its factory USB identity is recorded.
It requires `MOTA_BOOTLOADER_TEST_BUILD=1` and an explicit test version with Make,
or the equivalent CMake options. Its zero USB IDs are invalid compiler fixtures,
not allocated IDs or a claim of factory UF2 compatibility. Do not flash its
generated images. The V0.3 pin contract holds display power, frontlight, GPS
power, ADC power and buzzer low, sets their latches before enabling output, and
leaves the disputed P0.13 rail/power-enable control untouched. It does not drive
GPS PPS, use the encoder press as an active-low button, or infer USB presence
from the marginal VBUS divider. Factory entry, power behavior and physical
flash/update testing remain promotion gates.

Verification on 2026-10-02: the X1 candidate builds with GCC 14.2.1 and CMake,
using explicit test version `0x02040B01`: **38,728/40,784 executable flash
bytes**, factory USB identity 2886:0057, S140 FWID 0x0123 and application base
0x27000. Its board-only held-button USB probe supports cold VBUS settling and
BLE fallback, preserving explicit transport requests. Solar builds at
**38,477/40,784 bytes**, S140 FWID 0x00B6 and application base 0x26000.
T096 and T114 pass the required CMake builds at 40,104/40,436 bytes, unchanged
by the opt-in X1 entry policy.
The X1-identity/S140-v7 and Solar-identity/S140-v6 host regressions exercise ordinary internal deltas,
optional authenticated retained-RAM staging, full-application rejection,
wrong-base/identity/geometry rejection and signed self-update power-loss gates.
They also pass AddressSanitizer/UndefinedBehaviorSanitizer. Compiled board
contracts, Solar's actual common watchdog waveform, X1 entry selection and the
existing USB settle/enumeration/fallback regressions pass. Both candidates fail
Make/CMake configuration without explicit test mode and test version.
These are host/build results, not physical qualification. An ordinary flash-only
application does not need to reserve the RAM arena unless it uses hybrid staging.

Most of these vendor bootloaders already use legacy Adafruit USB IDs. Nano G2
Ultra instead uses its factory 4251:8695 identity. The ports retain the exact
manufacturer identities for factory UF2 compatibility, rather than allocate
new Adafruit IDs. M8 has no verified factory identity and cannot use this claim.
OTAFIX whole-image manifests bind the board ID and unique
device name, including for boards that share a legacy USB identity.

### Hardware checks before promotion

For each new target: record factory INFO_UF2 and USB identity; install via the
supported factory route; verify UF2 disk, INFO/CURRENT reads, CDC and BLE DFU;
check cold USB startup, reset and timeout return to an application; exercise
every fitted button and supported DFU entry route; verify all flash
erase/write/read patterns over the full device; test supported full/delta
application updates and exact-board bootloader self-update
with power interruption; confirm motor, LEDs and power rails are safe in DFU
and after teardown. Cross-board bootloader packages must be rejected.

## Other omissions kept explicit

No speculative source variant was added for the following two boards. Their release
catalog entry has a specific reason instead of silently guessing another board.

| Hardware | Remaining evidence needed / observed mismatch |
| --- | --- | --- |
| ThinkNode M4 | The Meshtastic port author identifies a bespoke PCB rather than M3's module. Manufacturer specifies 2 MB external flash but both application variants omit its routing. Establish that routing, factory bootloader identity and safe rail states before adding a port. |
| Wio WM1110 | Exact Dev Kit installation is confirmed J-Link/SWD; CH340C UART0 is TX P0.08/RX P0.06. The official blank SES application spans address zero, not an identified Adafruit bootloader layout. Bootloader/SoftDevice identity, UART recovery and NFC configuration remain unresolved; native-USB UF2 reachability is unproven. Tracker 1110/XIAO are not aliases. |

## Complete released mapping

| OTAFIX profile | Explicit MeshCore hardware names |
| --- | --- |
| `gat562` | `GAT562_30S_Mesh_Kit`, `GAT562_Mesh_EVB_Pro`, `GAT562_Mesh_Tracker_Pro` |
| `heltec_mesh_pocket` | `Mesh_pocket` |
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
| `heltec_mesh_tower_v2` (retired; local migration only) | `Heltec_tower_v2` |
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
contain no files. Each includes a machine-checked `qualification` object with
source status, real storage backend, factory-identity status, explicit blockers
and primary evidence. `tools/check_board_coverage.py` checks every pending and
retired source port, refuses source/storage substitutions and prevents an
unavailable profile from claiming physical qualification or download files.
The download manifest includes the resulting source/qualification counts.
Duplicate aliases across either list fail generation. The
MeshCore regression fixture classifies every nRF52 hardware choice in 1.17.1.7.
New hardware must be audited before adding a download recommendation. Use the
optional `--hardware-json` list to fail on unclassified future catalog names.
