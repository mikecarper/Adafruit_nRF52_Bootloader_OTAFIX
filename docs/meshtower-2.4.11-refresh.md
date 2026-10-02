# MeshTower 2.4.11 combined-storage refresh verification

Date: 2026-10-02, America/Los_Angeles. Production validation: PASS.

Source tag: `0.11.0-OTAFIX2.4.11`.
Source commit: `39177b9bbaa894352141734350d6ef2fab18dc4f`.
Original normal release tag: `v0.11.0-OTAFIX2.4.11`, unchanged.
Original recovery release tag: `R_0.11.0-OTAFIX2.4.11`, unchanged.
Packed version: `0x02040BFF`.

[Production workflow](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/actions/runs/37072081200)
passed all 33 build/validation jobs: Make/CMake for 29 production profiles,
T096/ST7735S and T114/ST7789 feature variants, native tests, ASan/UBSan,
ARM DFU emulation, signed mOTA packaging and the recovery archive. The
build-only dispatch intentionally skipped automatic publication.

Eight clean-tag CMake images (normal/recovery combined Tower, internal-only
Tower, T096 and T114) reproduce byte-for-byte on Windows and the Linux VM:
BIN, HEX and UF2. Independently built VM Make Tower normal/recovery outputs
match GitHub Make outputs: addressed HEX contents, Legacy ZIP contents and
UF2 bytes. Make and CMake are distinct variants; no equality between build
systems is claimed. CMake combined normal flash use is 40,763 / 40,784 bytes
(21 spare); recovery uses 40,578 bytes (206 spare).

The release uses the GitHub Make artifacts. Its two refreshed Tower
HEX/Legacy DFU ZIP/UF2 sets agree on bootloader and SoftDevice bytes, vectors,
BLMF/BLM2 CRC, UF2 framing/UICR, identity and version. Both retain SD primary
capability `0x09`, exact adjacent optional internal capability `0x02`, and
the 64 KiB bootloader RAM-arena contract. All 24 newly generated CI mOTA
signatures independently verify against the official public key; only the
combined Tower package is substituted into the existing release bundle.

| Refreshed Make artifact | Manifest CRC32 | Raw bootloader SHA-256 |
| --- | --- | --- |
| Normal combined Tower | `AAC09D85` | `4be75f3be7c43305a53df3e78f397165828b69e7268e5e737e63dcbfc3394f67` |
| Optional recovery combined Tower | `A13E591E` | `a048be3bda901fe7474482b468dd57c441adae793ef515befaaffd30c7719950` |

The exact normal 41,330-byte production signed package has SHA-256
`bb607b2ee01af28d8492b40fcc20d2e655538c8bb0c0db3ac12aa8aa3b113553`.
Both SD-only and combined-profile host validators accept its unaligned
payload at offset 365 and reach the simulated MBR handoff with `C8`;
the incorrect zero-base SoftDevice lookup is rejected with `C5`.

The refresh preserves every unaffected firmware file byte-for-byte,
including the other 23 normal profiles, the other 23 signed packages, and
the other 28/34 recovery profiles in the normal/standalone recovery bundles.
Original asset names and URLs are retained. Bundle inventories record the
Tower source override; other entries retain their original provenance.
Checksums, download metadata and instructions are regenerated for the repair.

The SD-card update path does not need an `R_` recovery image or bridge.
Existing authenticated SD self-update bootloaders install the normal combined
package directly. Optional recovery files remain repair tools, not part of
that installation flow. USB/UF2, serial and Nordic Legacy BLE remain enabled.

Physical combined-storage tests on 2026-09-29 used preview artifacts, not
these exact production files. They covered the SD-only to combined bootloader
transition, SD full/delta application updates, internal deltas, internal
bootloader replacement and persistent storage selection on the Pi's MeshTower.
See [the original hardware evidence](meshtower-dual-storage.md).
No new physical, phone, card-removal or install-time power-cut test is claimed
for this refresh. The earlier RAK4631 2.4.11 physical evidence remains unchanged.
