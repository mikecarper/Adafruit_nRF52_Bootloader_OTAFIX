# OTAFIX 2.4.12 qualification

[Current release: OTAFIX 2.4.12](release-2.4.12.md).

Qualification completed on 2026-10-22, America/Los_Angeles. Production artifacts
use clean exact tag `v0.11.0-OTAFIX2.4.12`, packed version `0x02040CFF`; the
hardware results below used separately identified test builds.

## Implementation and build evidence

- Firmware source: `d36504a767dcac1acccbb685ac85b8ce1b4f70f2`.
- TinyUSB: `98e77439e5109ee92761f84b995bd950e7b7a42d`.
- USB stress image: `TEST_0x02040C8D`.
- Nine-device deployment image: `TEST_0x02040C8E`.
- All 38 source profiles passed Make and CMake with Arm GNU 15.3.Rel1 and
  zero compiler warnings. Full features and fixed linker boundaries remained.
- Qualification executable loads: RAK4631 40,728/40,784 bytes; T096 39,756;
  T114 40,168. These measurements include initialized data, not just text.
- Host, sanitizer and USB regression tests passed. Stable-tag production
  builds and official signed bundles are generated and validated separately.

The release preparation retains these compiled firmware source bytes.
Qualification sizes and hashes are not relabelled as production output.

## USB stress on RAK4631

Target serial: `9AB3B64C641BA927`, USB path `1-1.1.3.2` on MercerWoodMesh Pi.

| Case | Completed | Result |
| --- | ---: | --- |
| Malformed-command concurrency transitions | 1,100 | Zero control failures; zero GET retries |
| USB-monitored overlapping critical cases | 100 | Overlap verified |
| Short reads | 10 | Pass |
| Phase errors | 10 | Pass |
| CDC recovery | 10 | Pass |
| Rejected OUT payload, 8,192 bytes | 10 | Pass |

This covers the reproduced Pi/RAK USB failures and the specified recovery
paths. It is not a universal claim about every USB host controller.

## Nine-device preservation and application return

Each device was bound to its USB chip serial and physical path. A fresh,
double-read `CURRENT.UF2` snapshot supplied that device's application backup.
One acknowledged bootloader-only serial DFU transferred 40,960 bytes without
a SoftDevice payload. The original application was then restored within its
validated flash bounds. Post-restore `CURRENT.UF2`, including the exported
SoftDevice span, matched the fresh baseline exactly.

| Hardware | USB serial | Original application role |
| --- | --- | --- |
| RAK3401 | `0B81C9C68D8D01B4` | Repeater/gateway |
| RAK4631 | `9AB3B64C641BA927` | Repeater |
| Heltec T096 | `EC2EFBE648195474` | Companion |
| Heltec Mesh Pocket | `93DA83ADF7B2092B` | Companion |
| Heltec MeshTower V2 | `9352162A72082314` | Repeater |
| Seeed T1000-E | `34A9141999729D5D` | Companion |
| RAK WisMesh Tag | `4D6F77FD74011872` | Companion |
| Seeed XIAO nRF52840 | `B35E71C1C3726CE7` | Repeater |
| SolarXiao 33S | `9EBCE8853076EE86` | Repeater |

All nine returned to their original application versions. Companions passed
an explicit binary-mode acknowledgement/query; repeaters passed their plain
version checks. The Tag and first XIAO DFU intervals overlapped for 2.201818
seconds. At most two programming transactions ran concurrently.

The preserved attempt history includes a RAK3401 final runtime serial-open
error, resolved by guarded read-only runtime verification, and a T1000 stale
TTY lease conflict after successful DFU, resolved by restoring its already
saved original application. The Tag's refused first attempt performed no
bootloader transfer. No bootloader transfer was repeated. Closed-operation
TTY leases then allowed the paired installs to complete. Original failure
reports and separate successful recovery proofs remain in the evidence.

The gateway was restored to its original active state. Final inspection found
all nine original runtime USB identities, no owned temporary udev rules or
mounts, and all coordinator/per-device leases released. Independent raw-byte
and report audits passed for every device, including both recoveries.

## Evidence and limits

The private evidence root is
`/home/mesh/otafix-usb-deploy-20261022-d36504a/`.

- All-board build proof SHA-256:
  `99f614e0b0a9331047e0beb023a33a489bc780ceae79e66b099e17ca7b28523a`.
- Final independent nine-device audit SHA-256:
  `a404f256bd7a60891ba655d7551b08963bf74f5ef55598b45c2940270074335c`.
- Metadata evidence archive SHA-256:
  `1b8cee8bbf8bfb8d690cc77da9dd1ce2497402b22fa30df9a04ccfabae75e533`.

Raw application backups remain private. `CURRENT.UF2` verifies its exported
application/SoftDevice span; it does not read back every persistent filesystem
byte, UICR, MBR, settings page or installed bootloader byte. Persistence safety
also rests on validated write/erase bounds. The package CRC, accepted DFU and
new INFO identity/version establish the installed bootloader evidence.

RAK15002 wiring and the official Arduino-to-physical GPIO mapping were checked
against RAK's GitHub example, BSP and datasheet. Nineteen SPI/NOR/SD driver
mock cases and fifteen SD apply/authentication/isolation cases passed with
ASan and UBSan. No physical RAK15002 card, removal, NOR interruption or power-cut
test is claimed. Those limits remain documented for the included RAK SD path.
Hardware-pending source ports remain outside production downloads.
