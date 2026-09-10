# OTAFIX 2.4.7-preview.2 qualification

The inherited USB READY hang is fixed in the bootloader and separately in
MeshCore. All 27 bootloader builds and host regressions pass. The debug-wired
RAK3401 passed application drive-copy and authenticated Bluetooth tests.
This is a test candidate, not an all-board or stable-release qualification.
The Pi's separate hub/controller fault is not claimed fixed.

## Sources and build gates

- Exact clean bootloader tag: `0.11.0-OTAFIX2.4.7-preview.2`.
- Bootloader source: `49099127b321edb6cc6496171dc9d74d969c53eb`.
- TinyUSB fix: `f03a62889f3bb3dd749111c29d9b95e4f20d5410` in the
  `mikecarper/tinyusb` fork, branch `otafix-0.12-nrf5x`.
- MeshCore source: `602dbfe3d9ad43630d9b4b6e8d9b6a73f4bc48b8`, branch
  `keymindCascade`. Its pre-build hook patches a build-local driver copy;
  the shared framework package was not changed.
- GCC remains 14.2.Rel1 / 14.2.1. No feature, storage profile, board identity,
  signing requirement, or compatible forward/reverse version policy was removed.
- These notes and the two host-runner corrections were committed after the
  exact-tag firmware builds, without moving the tag or changing firmware code.

| Gate | Result |
| --- | --- |
| All 27 Make board profiles | Pass; 137.56 seconds, two board workers |
| T096 CMake / ST7735S | Pass |
| T114 CMake / ST7789 | Pass |
| Full host `make -B -C test -j2 check` | Pass |
| Full ASan/UBSan suite | Pass; includes instrumented USB power handler |
| Host suite after runner corrections | Pass; 17 mounted-drive runner tests |
| All 27 embedded manifests | Packed version `0x02040702` and whole-image CRC verified |
| All 27 combined DFU ZIPs | ZIP integrity and embedded bootloader equality with HEX verified |
| All 27 dedicated bootloader UF2s | Family, blocks and bootloader payload equality with HEX verified |
| MeshCore Full Companion RAK3401 and XIAO builds | Pass with the build-local patched driver compiled |
| MeshCore USB power, BLE startup, UF2 CLI, MAC and settings regressions | Pass |
| nRF52 pre-build hook coverage | All 225 configured nRF52 environments inherit it |

The new power test compiles the real driver handler against simulated W1C
registers and clocks. It covers duplicate/nested READY callbacks, missing or
delayed clock/peripheral readiness, removal during either wait, retry, and
detached USB. Restoring the inherited READY prefix must hang under the test's
subprocess deadline. It is not just a source-text assertion. The same harness
also exercises MeshCore's patched, pinned-framework handler.

Docker builds used image
`sha256:f8bc8af57f8e210bee276b8cec4a3be1a5f5f1eb9c1f0e4a6c651a78593225c6`.
Builds ran on the VM without container network/device access, not on the Pi.

## Executable FLASH margin

These are Make's `TotalFlashUsed` symbols, including initialized data's flash
load image, against the 40,784-byte executable region. The fixed 176-byte
CF2/manifest tail is separate, not extra executable space.

| Board/profile | Used bytes | Free bytes |
| --- | ---: | ---: |
| MeshTower V2 SD | 40,745 | 39 |
| T114 | 40,592 | 192 |
| XIAO nRF52840 BLE | 40,213 | 571 |
| T096 | 40,191 | 593 |
| RAK4631 internal | 39,687 | 1,097 |
| RAK3401 internal | 39,559 | 1,225 |
| Mesh Pocket | 39,446 | 1,338 |
| T1000-E | 39,407 | 1,377 |

The tightest build remains MeshTower V2 SD: **39 bytes**. This is not useful
feature headroom. Long dirty-tree diagnostic version strings can exceed it;
do not remove features or expand the protected envelope to hide that overflow.

## RAK3401 physical evidence

Tests ran on 10 September 2026, Pacific daylight time, using the exact USB
serial `0B81C9C68D8D01B4` and the verified SWD wiring in the
[investigation](mercer-usb-investigation-2026-09-10.md).
The chip FICR identity was checked before every debug operation.

The initial application was Full Companion `...f778d14c`, with lab bootloader
`0x02040405`. Fresh full-flash capture matched the previously verified double
backup before any update. The fixed bootloader was copied through the real
Linux-mounted UF2 drive. The old bootloader's immediate `COPY_BL` activation
restarted the node before Linux's final `sync`, causing EIO. That transport
attempt is **not** recorded as a clean drive-copy pass. A subsequent complete
SWD readback proved that the installed bootloader exactly matched preview.2,
while the original application, filesystem region, MBR and SoftDevice were
unchanged. The dedicated bootloader COPY_BL path is separate from the deferred
application-UF2 completion path; this result must not be generalized to an
arbitrary failed copy.

The fixed Full Companion application was then copied over the mounted drive.
Copy and sync succeeded, the expected version replied over USB, and SWD
verified the complete application payload including EndF. MBR/SoftDevice,
UICR and the filesystem region still matched the pre-update backup at that
checkpoint. No node settings, trust keys or unread messages were cleared.

Two issues in the host runner were identified and corrected:

1. Pi util-linux 2.38.1 does not accept `dmesg --time-format=raw`.
   The runner now uses `dmesg --raw`, without the incompatible `--color` option.
2. A test-owned filesystem must be unmounted after sync, before waiting for
   the application to return. Unmounting only after the bootloader disappeared
   generated FAT errors during cleanup. The runner now checks this order;
   genuine copy, sync, unmount and kernel errors still fail the test.

With those corrections, the committed runner performed two further real
drive-copy updates without SWD entry: application A -> B -> A. Both used the
application's `uf2reset` command and the exact-device identity checks.

| Physical gate | Result / timing |
| --- | --- |
| A -> B: mounted copy, sync, unmount, automatic restart, version reply | Pass, 32.300 seconds; sync 21.179 seconds |
| B -> A: same gates, restoring the first fixed application | Pass, 32.836 seconds; sync 21.285 seconds |
| Kernel storage errors during either corrected run | None |
| Fresh authenticated BLE connection | Pass; exact FICR-derived factory address, Paired/Bonded, MTU 247 |
| Bonded reconnect | Pass; real device-info, core-statistics and full version replies |
| BLE-requested warm reboot and subsequent bonded reconnect | Pass; uptime changed from 450 to 8 seconds; version verified again |
| BLE held sessions | Both five-second holds returned another protected command reply |
| Application core error flags | Zero in all three BLE sessions |
| USB after the BLE reboot | Expected full version reply; factory MAC policy and stealth-off unchanged |

The BLE reboot raced its ATT acknowledgement. The test required an observed
disconnect plus a successful post-reboot authenticated query and decreased
uptime; it did not accept the write error alone as proof of success. Pairing
created a normal lab bond. Pyserial 3.5 was installed only in the Pi's existing
BLE test virtual environment to read the live PIN over the exact USB port;
the PIN was not logged. The node was left on application A with preview.2.

Artifact A: `RAK_3401_companion_radio_full-1.17.1.6-usbready-test-602dbfe3.uf2`,
SHA-256 `6c844934d28599fa762736bfadaf7536017a339bef9e02e30b970550ff6c91eb`.
Artifact B: `RAK_3401_companion_radio_full-1.17.1.6-usbready-retest-602dbfe3.uf2`,
SHA-256 `46783569ec9d0121b3940ff33abc15df87cf3cd50b3dcbfde37de0b9cc7198d2`.
The installed raw 40 KiB bootloader SHA-256 was
`299ba2df0ad551401463aeed9a533ab6d7fee7c452ba440fca486a0dc87d971e`.

## Limits and remaining gates

No other target was flashed. The XIAO build passed, but its earlier silent USB
state has not been independently diagnosed over SWD or physically retested.
Other-board hardware, Android/iOS DFU, LoRa bootloader updates, true battery-off
cold starts, and physical bootloader rollback remain open for this candidate.
The A/B/A test restores application builds; it is not a bootloader rollback test.

The Pi remained reachable and its throttling mask was zero. No hub/driver
reset, Pi reboot, kernel/boot-option change or power-plug operation was used.
ModemManager and the serial bridge were restored and both were active at the
final check. Earlier bridge restarts occurred while the RAK was unresponsive.
The earlier unattended hub losses and
Ethernet carrier drops still require separate host/cable/power investigation.

## Artifacts and private evidence

The local `OTAFIX-2.4.7-preview.2-test-kit.zip` and SHA-256 sidecar contain
81 exact-board bootloader artifacts, metadata and checksums. They contain no
private node backup, application restore or signed `.mota` files. No stable
GitHub release is created by this qualification.

Raw logs, applications and readbacks are private under
`/home/mesh/otafix-usb-ready.NH0xwi/` on the VM and
`/home/mikec/hwtest/otafix-usb-ready.gfb8mu/` on the Pi. Earlier verified backups
remain intact. Backups and pairing details are excluded from Git and the kit.
