# Secure BLE DFU all-board qualification

`SECURE_DFU_TEST=ON` replaces the Legacy **BLE** DFU service with the resumable
Nordic Secure DFU wire protocol on the curated nRF52840 board configurations.
USB CDC serial DFU, UF2 recovery, the display and LoRa mOTA are retained. Normal
builds retain Legacy BLE DFU. The old `SECURE_DFU_RAK3401_TEST` option remains a RAK3401-only
compatibility alias.

This is an unsigned, application-only **test profile**, not signed Secure Boot:
SHA-256 and application vectors are verified before activation; signed envelopes,
SoftDevice/bootloader packages, signed firmware builds, dual-bank builds and
cross-board recovery profiles are rejected. An explicit test version is required.

Resume retains metadata, CRCs and the partial 4 KiB object in static RAM during
the same powered DFU session. Disconnect/reconnect resumes the byte offset;
reset, power loss or expiration of the existing idle timeout loses that state.
No heap allocation or change to the 64 KiB mOTA arena is involved.

## Build and package

```sh
cmake -S . -B cmake-build-secure-t096 -DBOARD=heltec_t096 \
  -DSECURE_DFU_TEST=ON -DMOTA_BOOTLOADER_TEST_BUILD=ON \
  -DMOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040709
cmake --build cmake-build-secure-t096

python tools/build_all.py --secure-dfu-test --test-version 0x02040709 \
  --build-root _build-secure-test --keep-build --jobs 3

python tools/generate_secure_dfu_test.py --board heltec_t096 \
  --application application.bin --output t096-secure.zip
```

Use the application built for that board and its configured SoftDevice. The
generator derives the stock board's S140 FWID and application base from the
checked-in SoftDevice image. Custom SoftDevice overrides are not inferred.
The ZIP uses STORE compression for compatibility with the Zephyr sender and
Nordic phone apps. It is not a Legacy BLE or serial-DFU package.

The board-name CRC32 is the Secure `hw_version` compatibility ID, except that
`wiscore_rak3401` retains `0x3401` for existing phone packages. USB VID/PIDs are
not used because some boards share them. Tests check all current IDs for
collisions, both SoftDevice versions and wrong-board rejection. These IDs are
not cryptographic authentication.

The identity-gated bench sender accepts `--board`, `--name`, `--address` and an
exact package `--sha256`. Defaults preserve the original RAK3401 lab invocation.
It does not enter DFU or infer permission to flash another device.

## Shared-code cleanup follow-up — 2026-09-12

All **27/27** Secure-only configurations now link on Windows and Linux with
Arm GNU 14.2.1, the same `0x02040709` test version and
`SOURCE_DATE_EPOCH=1789119612`. Their BIN, HEX, MBR HEX and MBR UF2 files match
byte-for-byte: **108/108 artifact hashes** agree.

| Board | Before (bytes) | After (bytes) | Saved | Free |
| --- | ---: | ---: | ---: | ---: |
| SD MeshTower | 41,317 | 40,745 | 572 | 39 |
| T096 | 40,747 | 40,287 | 460 | 497 |
| T114 | 41,148 | 40,656 | 492 | 128 |

The fresh SD baseline measured 41,317 bytes, four more than the earlier report
below. This comparison uses the fresh before/after linker maps, including the
initialized-data load image. The 40,784-byte limit, CF2/manifest locations,
bootloader origin, RAM layout and enabled features did not change.

**The requested 1–2 KiB savings target has not been reached.** SD MeshTower
now fits, but 39 bytes is not a useful growth margin or a release qualification.
No feature shedding, buffer-size reduction or larger flash envelope was used.

The retained changes share CRC-32 and inherited-watchdog reload implementations,
share the mOTA streaming SHA loop while keeping live-flash reads distinct from
staging, simplify SHA padding/length serialization, and selectively outline
SHA initialization, object transitions, UF2 dispatch and board initialization.
Broad inlining/compiler experiments and individually larger variants were
discarded; global compiler flags and vendor submodule revisions are unchanged.

Validation for this follow-up:

- Full Linux `make -B check` with native C harnesses rebuilt under ASan/UBSan:
  pass. Includes internal/SD/QSPI apply, hybrid handoff, flash readback, malformed
  images, UF2 state and recovery policy tests.
- Shared-helper tests (5), Secure protocol tests (15) and BLE adapter tests (17):
  pass on Windows and again with instrumented production code on Linux.
  Independent CRC/SHA oracles cover unaligned input, chunk/padding boundaries,
  64-bit length encoding, masked-CRC edge cases and every watchdog channel mask.
- Normal Legacy control builds for SD MeshTower/T096/T114 also fit on both
  systems; their BIN hashes match. Free space is 368/826/457 bytes respectively.
- No hardware flashing or fresh hardware qualification was performed for this
  cleanup. Earlier hardware results below apply to the earlier image, not this
  newly linked image.

## Initial fit results, before shared-code cleanup — 2026-09-12

Arm GNU 14.2.1, CMake MinSizeRel, test version `0x02040709`, source base `8f55f28`
plus the accompanying changes. `SOURCE_DATE_EPOCH=1789119612` was identical on
Windows and Linux. All 27 configurations were attempted on both systems;
24 linked successfully and their BIN, HEX, MBR HEX and UF2 hashes matched exactly.

Flash below includes initialized data as well as code/read-only data. The
linker's printed `FLASH Used Size` omits the data load image and must not be
used by itself to decide whether a nearly-full image fits. The fixed executable
limit is **40,784 bytes**; no CF2/manifest boundary or bootloader origin moved.

| Board | Executable flash (bytes) | Remaining (bytes) |
| --- | ---: | ---: |
| gat562 | 40236 | 548 |
| heltec_mesh_pocket | 39986 | 798 |
| heltec_mesh_tower_v2 | 40185 | 599 |
| heltec_t096 | 40747 | 37 |
| heltec_t1 | 40746 | 38 |
| keepteen_lt1 | 39985 | 799 |
| lilygo_techo | 40544 | 240 |
| minewsemi_mx25le01 | 40073 | 711 |
| pca10056 | 40560 | 224 |
| promicro_nrf52840 | 40095 | 689 |
| sensecap_solar_p1 | 40448 | 336 |
| t1000_e | 39963 | 821 |
| thinknode_m1 | 40444 | 340 |
| thinknode_m3 | 39979 | 805 |
| thinknode_m6 | 40460 | 324 |
| wio_tracker_l1 | 40400 | 384 |
| wiscore_rak3401 | 40115 | 669 |
| wiscore_rak3401_rak13302_w25q16 | 40628 | 156 |
| wiscore_rak4631_board | 40243 | 541 |
| wiscore_rak4631_board_rak15001_slot_c | 40732 | 52 |
| wiscore_rak4631_w25q16 | 40708 | 76 |
| wismesh_tag | 40238 | 546 |
| xiao_nrf52840_ble | 40689 | 95 |
| xiao_nrf52840_ble_sense | 40695 | 89 |

Not fitting yet (including the initialized data load):

| Board | Required flash (bytes) | Over limit (bytes) |
| --- | ---: | ---: |
| lilygo_techo_lite | 40788 | 4 |
| heltec_t114 | 41148 | 364 |
| heltec_mesh_tower_v2_sdcard | 41313 | 529 |

Do not flash failed/partial builds or treat these results as an all-board release.
The very small margins on several successful boards also warrant more room
before production. Omitting serial/CDC DFU from the test profile is a possible
next tradeoff, but has not been implemented or silently selected.

The code-size reductions bound LTO inlining at the protocol interfaces, use
direct little-endian receipt stores and check fixed canonical protobuf wrapper
and SHA-256 prefixes without repeated general-purpose parsing. SHA-256, CRC,
offset checks, flash-error latching, receipt queues and final-EXECUTE activation
guards remain in place.

## Validation

- All 61 host protocol, BLE adapter, sender and target/package tests pass on
  Windows and Linux; the six all-board build-helper tests pass on Windows.
- The complete existing Linux `make -C test check` suite passed; the 56 core,
  adapter and sender tests also passed with AddressSanitizer/UBSan.
- Linux Make compiled and packaged the Secure RAK3401 profile as well as the
  CMake matrix above. Make and CMake are separate build products; only the
  Windows/Linux CMake products are claimed byte-identical.
- The unchanged Legacy T096 and T114 control profiles both compiled. The
  build-profile mock harness requires symlink privileges unavailable on this
  Windows host; its eight tests passed on Linux instead.

## MercerWoodMesh Pi hardware results

The SWD-connected RAK3401 was identity-checked before programming. Only its
`0xF4000..0xFE000` bootloader region was replaced, then read back independently.
The installed 40,960-byte Secure09 image has SHA-256
`43f61fc6de13adb4849edc74b1bfab721e75cb1f8c81207acd86cfebf41610a4`.
The existing independently qualified Pi BLE sender drove the actual receiver;
these tests did not simulate the bootloader's state machine.

Passed on this physical board:

- Secure FE59 advertised/discovered; the Legacy BLE DFU service was absent.
- Wrong-board metadata rejected before erase/write; full flash remained identical.
- Correct metadata with deliberately corrupted payload rejected at final SHA-256
  verification; new CREATE requests stayed blocked until reset.
- A partial 820-byte transfer was measured by SELECT/CRC, then reset through the
  debugging wires. Both command and data offsets returned to zero.
- The real 617,216-byte application upload was disconnected at byte **228,123**.
  Reconnection reported exactly that offset and CRC `D0E8D281`, then continued.
- After every image byte had arrived, the sender deliberately omitted the final
  DATA EXECUTE and disconnected. Reconnection reported offset **617,216** and CRC
  `73F578E7`; it sent **zero** DATA bytes, re-executed and received confirmation.
- Independent final SWD readback matched the full original application and the
  new bootloader. MBR, SoftDevice, filesystem, MBR parameters and UICR were
  unchanged. The original companion application booted with its original name
  and radio configuration.

The RAK3401 is left running that original application with the Secure09 test
bootloader installed. The paused MQTT bridge and ModemManager services were
restored. The unrelated memory-soak service remained active. Private flash/UICR
captures stay on the Pi; no keys or full-node captures are included here.

Two harness-only issues were corrected during the run: ownership of root-created
SWD captures, and consuming a queued PRN receipt as an explicit checksum reply.
The latter reset case was rerun with an independently measured pre-reset cursor;
the failed harness attempt is not counted as a passing test.

This is hardware evidence for **RAK3401**, not hardware certification of the
other 26 boards. No new phone-app test or LoRa mOTA transfer was performed in
this run. Reset loses resume state by design; no cross-power-cycle resume is
claimed. Three oversized configurations still block an all-board release.
