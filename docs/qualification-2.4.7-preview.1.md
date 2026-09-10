# OTAFIX 2.4.7-preview.1 qualification checkpoint

**Build/host tests passed. Physical update qualification is on hold.**
The connected RAK3401 exposed an application USB READY wait hang, and the Pi
had earlier unattended hub resets. See the [USB investigation](mercer-usb-investigation-2026-09-10.md).
This candidate does not fix either issue and must not be advertised as a
USB-fix release or as hardware-qualified.

## Candidate and provenance

- Local annotated tag: `0.11.0-OTAFIX2.4.7-preview.1`.
- Source commit: `437a82fac2cc97378b190a26ee57451edfe249cc`.
- Packed version: `0x02040701`.
- Arm compiler: GCC 14.2.Rel1, reporting 14.2.1.
- Source was clean and exactly tagged during all builds; no test-version
  override was needed. This report was added afterward, without moving the tag.
- Fresh Adafruit upstream fetch found no missing upstream commits.
- `src`, `lib`, `linker`, Makefile and CMakeLists.txt are unchanged from 2.4.6.
- No GitHub release or tag push was performed.

## Automated results

| Gate | Result |
| --- | --- |
| All 27 Make board builds | Pass, 115.05 seconds with two board workers |
| Full host `make -B -C test -j2 check` | Pass |
| Full `make -C test -j2 sanitize` | Pass with ASan and UBSan |
| T096 CMake build, ST7735S | Pass |
| T114 CMake build, ST7789 | Pass |
| All 27 embedded manifests | Version and whole-bootloader CRC verified |
| All 27 Legacy combined DFU ZIPs | ZIP integrity and bootloader payload equality with HEX verified |
| All 27 dedicated bootloader UF2s | Family, blocks and bootloader bytes verified against HEX |

The host checks include UF2 2.4.3 differential reproduction, mounted-drive
runner contracts, BLE cache/Legacy DFU policy, USB task budgets, rollback and
mOTA application/bootloader validation. They did not model the newly observed
USB READY wait hang; passing them does not cover that newly identified gap.

The Docker image used was
`sha256:f8bc8af57f8e210bee276b8cec4a3be1a5f5f1eb9c1f0e4a6c651a78593225c6`.
The container had no network, no device access and a read-only source mount.
Builds and native tests ran on the VM, not on the Pi.

## Firmware size

Figures below are Make's linker `TotalFlashUsed`: code plus the flash load
image for initialized data, against the 40,784-byte executable region.
The fixed 176-byte CF2/manifest envelope is separate. `build_all.py`'s aggregate
ELF Flash column is not this region's usage and must not be subtracted from
40,784 to calculate free space.

| Board/profile | FLASH used | Free bytes |
| --- | ---: | ---: |
| MeshTower V2 SD | 40,697 | 87 |
| T114 | 40,544 | 240 |
| XIAO nRF52840 BLE | 40,149 | 635 |
| T096 | 40,143 | 641 |
| RAK4631 internal | 39,639 | 1,145 |
| RAK3401 internal | 39,511 | 1,273 |
| Mesh Pocket | 39,382 | 1,402 |
| T1000-E | 39,359 | 1,425 |

The tightest of all 27 builds is MeshTower V2 SD: **87 bytes**, approximately
0.085 KiB. This is not useful feature headroom. CMake's separate T096/T114
builds used 39,979/40,380 bytes respectively; their results are not substituted
for the packaged Make artifact sizes.

## Physical inventory, not update results

The Pi enumerated all seven expected nRF52 boards plus the ESP32 Heltec V4.
Exact serial identities were kept in the private evidence. Duplicate VID/PID
values and the T096's extra CDC interface were not counted as extra boards.

| Board | Read-only result |
| --- | --- |
| RAK3401 | Text and framed USB silent; SWD proves the USB READY wait hang; matching double flash backup plus UICR/RAM captured. |
| RAK4631 | Text console responds; application `v1.15.0-dev-ea3f7acb`, reports bootloader `0.9.2-OTAFIX2.1-BP1.2`. Its old console lacks current OTA commands. |
| T096 | Companion `v1.17.1.6-ui2-f778d14c` responds; identifies internal mOTA apply support. One long `ota self` reply exceeded the initial one-second collection window, so no independent OTA-status result is claimed. |
| MeshTower V2 SD | Repeater `1.17.1.5-halo-keymind-cascade-marathon-hwtest-e26d48e4` responds; bootloader model `TOWER_V2_OTA`, SD apply support. |
| Mesh Pocket | Companion `v1.17.1.6-ui2-f778d14c` responds; OTA queries refused for insufficient free message-queue slots. No messages were discarded. |
| XIAO nRF52840 | USB identity present; both text and framed probes timed out without data. No SWD diagnosis or recovery attempted. |
| T1000-E | Companion `v1.17.1.6-f778d14c` responds; OTA queries refused for insufficient free message-queue slots. No messages were discarded. |
| Heltec V4 | Companion `v1.17.1.6-halo-keymind-cascade-dev-f778d14c` responds; reports OTA source-only support. Not an OTAFIX target. |

No candidate was flashed. Actual OS-mounted-drive application copy, serial/BLE
DFU, phone DFU, LoRa update, forward/reverse update and application-return
qualification remain open for this exact candidate. Earlier release test
results have not been carried forward as if they were new physical passes.

## Local test kit

`OTAFIX-2.4.7-preview.1-test-kit.zip` contains the exact-board combined
SoftDevice/bootloader Legacy DFU ZIP, dedicated bootloader `_mbr.uf2`, and
combined SWD HEX for all 27 profiles: 81 firmware files. It also contains
`manifest.json`, `SHA256SUMS`, these reports and a short README. Its adjacent
`.sha256` file checks the outer archive.

The kit is for controlled qualification, not field recovery: it does not
include a MeshCore application restore, private node backup or signed `.mota`
files. No mOTA signing/trust keys were changed. Local artifacts and raw build
logs are under `/home/mesh/otafix-247-test.KS9Dp5/`.
