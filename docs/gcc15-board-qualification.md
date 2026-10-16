# GCC 15.3 compiler qualification by board

Date: 2026-10-16. Firmware source: `26940db65469b786e95886f89dc8cf399ed1b5a3`.

## Decision

All 38 current board profiles select Arm GNU 15.3.Rel1 for future builds.
Every profile produced smaller normal and recovery images with both Make and
CMake. The combined `wiscore_rak4631_auto` already required 15.3; its 14.2
comparison builds exceeded the fixed flash region. New profiles default to
14.2 until their compiler is qualified in `tools/compiler_policy.json`.

This changes the compiler selection and explicitly fixes C sources to GNU C17.
It preserves source features, board identities, storage modes, signing policy,
and the release eligibility of pending or retired profiles. It does not replace
previously published release assets or qualify untested hardware.

## Method

- Official complete Arm toolchains: 14.2.Rel1 (GCC 14.2.1 20241119) and
  15.3.Rel1 (GCC 15.3.1 20260627), including their matching binutils/Newlib.
- Same firmware and initialized libraries, packed test version `0x02040B7E`,
  `SOURCE_DATE_EPOCH=1792111302`, optimization flags, linker script, and features.
- Both compilers use `-std=gnu17`; GCC 15's newer default C dialect is not part
  of this comparison. The final build policy excludes this option from assembly.
- The isolated comparison lowered only the combined RAK minimum compiler guard
  to permit the deliberately failing 14.2 baseline. Production retains that guard.
- 304 builds: 38 boards x 2 compilers x normal/recovery x Make/CMake.
- Another 24 builds cover both display controllers with signed, dual-bank,
  and signed plus dual-bank configurations under both build systems/compilers.
- Sizes below count code/rodata and initialized data loaded from flash:
  `TotalFlashUsed = (__etext - ORIGIN(FLASH)) + (__bss_start__ - __data_start__)`.
  The executable limit is 40,784 bytes. Fixed CF2 and manifest envelopes are
  excluded from that region; padded BIN/HEX file sizes are not code sizes.

## All-board results

All numbers are bytes from the qualification version, not measurements of the
existing release assets. Make and CMake agree in every row. The 14.2 overflow
rows use the completed linker map, including initialized data.

| Board | Normal 14.2 | Normal 15.3 | Saved | Recovery 14.2 | Recovery 15.3 | Saved |
|---|---:|---:|---:|---:|---:|---:|
| `gat562` | 38,682 | 38,442 | 240 | 38,489 | 38,249 | 240 |
| `gat562_mesh_watch13` | 39,359 | 39,167 | 192 | 39,198 | 39,006 | 192 |
| `heltec_mesh_pocket` | 38,464 | 38,240 | 224 | 38,287 | 38,047 | 240 |
| `heltec_mesh_solar` | 38,417 | 38,193 | 224 | 38,224 | 38,000 | 224 |
| `heltec_mesh_tower_v2` | 38,607 | 38,383 | 224 | 38,430 | 38,206 | 224 |
| `heltec_mesh_tower_v2_sdcard` | 40,579 | 40,387 | 192 | 40,386 | 40,194 | 192 |
| `heltec_t096` | 40,044 | 39,804 | 240 | 39,852 | 39,596 | 256 |
| `heltec_t1` | 40,060 | 39,816 | 244 | 39,864 | 39,608 | 256 |
| `heltec_t114` | 40,376 | 40,216 | 160 | 40,180 | 40,004 | 176 |
| `keepteen_lt1` | 38,437 | 38,213 | 224 | 38,260 | 38,020 | 240 |
| `lilygo_t_impulse_plus` | 39,618 | 39,426 | 192 | 39,457 | 39,281 | 176 |
| `lilygo_techo` | 39,521 | 39,345 | 176 | 39,376 | 39,184 | 192 |
| `lilygo_techo_card` | 39,320 | 39,128 | 192 | 39,159 | 38,983 | 176 |
| `lilygo_techo_lite` | 39,735 | 39,559 | 176 | 39,590 | 39,398 | 192 |
| `meshtiny` | 39,639 | 39,447 | 192 | 39,494 | 39,302 | 192 |
| `meshtracker_x1` | 38,668 | 38,492 | 176 | 38,475 | 38,299 | 176 |
| `minewsemi_mx25le01` | 38,560 | 38,336 | 224 | 38,383 | 38,143 | 240 |
| `muzi_base` | 39,624 | 39,432 | 192 | 39,463 | 39,271 | 192 |
| `nano_g2_ultra` | 39,239 | 39,047 | 192 | 39,094 | 38,902 | 192 |
| `pca10056` | 39,554 | 39,362 | 192 | 39,409 | 39,217 | 192 |
| `promicro_nrf52840` | 38,579 | 38,355 | 224 | 38,402 | 38,162 | 240 |
| `sensecap_solar_p1` | 39,444 | 39,252 | 192 | 39,283 | 39,091 | 192 |
| `t1000_e` | 38,504 | 38,264 | 240 | 38,311 | 38,071 | 240 |
| `thinknode_m1` | 39,421 | 39,245 | 176 | 39,276 | 39,084 | 192 |
| `thinknode_m3` | 38,472 | 38,232 | 240 | 38,279 | 38,039 | 240 |
| `thinknode_m6` | 39,453 | 39,261 | 192 | 39,308 | 39,116 | 192 |
| `thinknode_m8` | 38,720 | 38,512 | 208 | 38,163 | 37,971 | 192 |
| `wio_tracker_l1` | 39,395 | 39,219 | 176 | 39,250 | 39,042 | 208 |
| `wiscore_rak3401` | 38,599 | 38,391 | 208 | 38,422 | 38,198 | 224 |
| `wiscore_rak3401_auto` | 40,364 | 40,172 | 192 | 40,192 | 40,000 | 192 |
| `wiscore_rak3401_rak13302_w25q16` | 39,589 | 39,413 | 176 | 39,444 | 39,268 | 176 |
| `wiscore_rak4631_auto` | 41,080 (fails) | 40,776 | 304 | 40,908 (fails) | 40,636 | 272 |
| `wiscore_rak4631_board` | 38,704 | 38,480 | 224 | 38,527 | 38,287 | 240 |
| `wiscore_rak4631_board_rak15001_slot_c` | 39,677 | 39,501 | 176 | 39,532 | 39,356 | 176 |
| `wiscore_rak4631_w25q16` | 39,654 | 39,478 | 176 | 39,509 | 39,333 | 176 |
| `wismesh_tag` | 38,737 | 38,545 | 192 | 38,560 | 38,352 | 208 |
| `xiao_nrf52840_ble` | 39,408 | 39,216 | 192 | 39,263 | 39,055 | 208 |
| `xiao_nrf52840_ble_sense` | 39,419 | 39,227 | 192 | 39,274 | 39,066 | 208 |

The combined RAK4631 has the smallest GCC 15.3 qualification margins: 8 bytes
normal and 148 bytes recovery. Release labels can change these totals; every
actual release must still pass the unchanged linker envelope assertions.

## Display feature results

Make and CMake produced identical totals in all six comparisons.

| Board | Variant | GCC 14.2 | GCC 15.3 | Saved |
|---|---|---:|---:|---:|
| `heltec_t096` | Signed | 39,720 | 39,400 | 320 |
| `heltec_t096` | Dual-bank | 40,188 | 39,948 | 240 |
| `heltec_t096` | Signed + dual-bank | 38,903 | 38,582 | 321 |
| `heltec_t114` | Signed | 40,040 | 39,832 | 208 |
| `heltec_t114` | Dual-bank | 40,520 | 40,360 | 160 |
| `heltec_t114` | Signed + dual-bank | 39,208 | 38,984 | 224 |

## Safety and package checks

All 152 GCC 15 all-board builds and all 12 GCC 15 display feature builds
passed. The only failures among the 328 attempted builds were four expected
GCC 14 combined RAK4631 overflows (normal/recovery under Make/CMake).
Successful builds emitted no compiler warnings.

All 300 successful all-board artifact sets passed BLMF/BLM2 CRC, version,
board identity, and UF2 framing/address/payload checks. All 150 Make-generated
local DFU ZIPs also passed payload checks.
For all 148 successful compiler pairs, CF2 configuration, manifest metadata
apart from CRC, and advertised update ABI/capabilities were byte-identical.
The four GCC 15 RAK configurations also passed the package checks; their GCC 14
counterparts did not link.

The frozen-source host suite passed both ordinary and ASan/UBSan runs: 383 Python
cases and 48 native executables per run, with required fault-handler emulation
and no skipped cases. Another 42 optional sanitized cases covered secure DFU,
secure BLE transport, CRC/SHA/watchdog behavior, and binary admission; the GATT
cache retry assertions also passed. The integrated build-policy host check passed
393 Python cases plus 48 native invocations, including required emulation and
linked RAK binary admission; subsequent compiler-selection regressions also passed.

All 164 actual GCC 15 ELFs (152 main plus 12 display feature builds) passed
1,640 actual-code reset/fault emulator scenarios. They were checked for vector
targets, strong handlers, retained peer data, stack/heap and mOTA RAM arena
bounds, stackless fault/reset paths,
and naked SVC portal instruction bodies. Make final-LTO stack reports were
compared against 14.2 in 82 pairs. There were no unbounded frames. The largest
individual frame was 928 bytes against an 8,192-byte allocated stack. The largest
matched-function increase was 40 bytes (`thinknode_m8` image validation: 16 to 56).
Individual frame sizes are not a proof of maximum runtime call depth.
CMake does not emit final-LTO stack reports with its current link flags.

These checks provide automated compiler qualification. They do not constitute
new end-to-end BLE/LoRa/USB tests on every physical board. Existing hardware
qualification restrictions remain in force.

## Build integration

`tools/compiler_policy.json` is shared by Make, CMake, all-board builds, normal
CI, recovery CI, and display feature CI. Docker installs both checksum-pinned
compiler releases; native installations may set `ARM_GNU_TOOLCHAIN_14_2` and
`ARM_GNU_TOOLCHAIN_15_3`.

Default builds require the selected compiler family. Explicit compiler overrides
remain available for qualification and retain minimum-version checks. The
all-board helper resolves every compiler before removing outputs. CMake rejects
a stale cached compiler; use a fresh build directory after changing selection.

The official 15.3 x86_64 archive SHA-256 was
`563bebb2b97d53382b956d6ee1fe61e2cae26699901417234a37df505ef9b5fa`.
Raw build logs, maps, ELF files, update packages, and automated audit reports were
retained locally under `/home/mesh/otafix-gcc14-15-ecru0045/`.
