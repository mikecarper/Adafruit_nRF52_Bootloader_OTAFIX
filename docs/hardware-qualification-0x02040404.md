# OTAFIX 2.4.4 hardware qualification (`0x02040404`)

> **Disqualified:** this candidate changed the historical Device Information
> attribute layout. The model value moved from cached handle `0x001A` to
> `0x0018`, so a bonded Legacy DFU client could receive `Invalid Handle` before
> START. Candidate `0x02040405` restores the layout; see
> [`hardware-qualification-0x02040405.md`](hardware-qualification-0x02040405.md).

This is the reproducibility record for the 3 September 2026 lab candidate. It
is not a release artifact. The build came from the intentionally dirty
`92e5c17` qualification tree, used the explicit packed test version
`0x02040404`, and was compiled with Arm GNU Toolchain 14.2.Rel1 (GCC 14.2.1).
Production artifacts must still come from a clean exact release tag.

## Compatibility scope

OTAFIX continues to use the nRF5 SDK Legacy DFU service, control/data packet
format, and standard nRF Util ZIP manifest. Nordic's current Android and iOS
DFU libraries both state that they remain backward compatible with Legacy DFU:

- [Android DFU library](https://github.com/NordicSemiconductor/Android-DFU-Library#requirements)
- [iOS DFU library](https://github.com/NordicSemiconductor/IOS-DFU-Library#legacy-dfu)

The host and XIAO tests below qualify that wire protocol, ZIP format, service
discovery, Device Information model check, MTU negotiation, receipts,
validation, activation, reconnect, and application return. They are not a
literal Android/iOS user-interface test. A release candidate should still get
one phone smoke test with Nordic's nRF Device Firmware Update app before
publication.

## Image size

The nRF52840 executable region is 40,784 bytes. The fixed CF2 and BLMF/BLM2
tail is outside these figures.

| Board | FLASH used | Free bytes | Free |
| --- | ---: | ---: | ---: |
| `heltec_t096` | 39,296 | 1,488 | 3.65% |
| `wiscore_rak3401` | 38,572 | 2,212 | 5.42% |
| `xiao_nrf52840_ble` | 40,084 | 700 | 1.72% |
| `heltec_mesh_tower_v2_sdcard` | 40,584 | 200 | 0.49% |
| `heltec_mesh_pocket` | 38,460 | 2,324 | 5.70% |
| `t1000_e` | 38,420 | 2,364 | 5.80% |

These corrected figures use the linker's `TotalFlashUsed` and include the
flash load image for initialized `.data`. MeshTower V2 with microSD is the
tightest build. Its 200-byte margin is a hard
release constraint, not spare feature budget.

## Completed hardware results

The controller was the MercerWoodMesh Raspberry Pi with the six named USB
devices connected. All packages and identities were SHA-256 or exact-string
gated before a write. USB checks also bound the expected device serial and
VID/PID. The RAK3401 was the only target with SWD diagnostics.

| Path | Result | Important checks |
| --- | --- | --- |
| Host to RAK3401 application | Pass | 473,312-byte application, MTU 247, exact post-write SWD readback |
| Host RAK3401 `0x02040404` to `0x02040403` | Pass | Combined SoftDevice/bootloader rollback accepted and exact readback |
| Host RAK3401 `0x02040403` to `0x02040404` | Pass | Combined forward update accepted and exact readback |
| Repeated RAK3401 DIS connections | Pass | Five fresh connections returned the exact retained model string |
| Patched XIAO updater to RAK3401 | Pass | XIAO owned the complete BLE DFU transport; no USB reset/error in the kernel log |
| XIAO QSPI post-success state | Pass | Consumed ZIP remained deleted after reinstall/reboot; `CONFIG.TXT` was unchanged |

The RAK diagnostic wires were used to bind device identity, force the
successful XIAO run into BLE DFU, and obtain exact readback. They were not used
to carry or recover that transfer. On the earlier failed XIAO attempt, no DFU
START packet was sent and the RAK returned to its application on its own after
the inactivity interval. Thus that failure did not depend on SWD recovery.
The successful run does not, however, qualify application-side buttonless entry
as wire-free because the lab deliberately forced entry for measurement.

The first XIAO attempt exposed a separate updater-app bug: the eject callback
released host-media ownership and touched shared QSPI/SdFat state while Linux
MSC callbacks were still active. The updater now closes an MSC I/O gate, waits
for active callbacks to drain, refreshes the filesystem, and only then gives
firmware ownership to the DFU worker. Both XIAO and RAK4631 updater builds pass
after that change.

## Measured timings

Times are wall-clock measurements from the hardware logs, not protocol
estimates. `DATA` covers confirmed payload bytes only. End-to-end includes
package verification, scan, connect, START, INIT, DATA, VALIDATE, ACTIVATE, and
the target-initiated disconnect.

| Operation | Payload | DATA time | Payload rate | End-to-end |
| --- | ---: | ---: | ---: | ---: |
| Host to RAK3401 application | 473,312 B | 221.909 s | 2,133 B/s | 247.310 s |
| RAK3401 reverse `04` to `03` combined image | 191,976 B | 91.212 s | 2,105 B/s | 114.729 s |
| RAK3401 forward `03` to `04` combined image | 191,976 B | 91.261 s | 2,104 B/s | 114.748 s |
| Host final RAK3401 application restore | 473,312 B | 224.640 s | 2,107 B/s | 248.172 s |
| XIAO updater to RAK3401 application | 473,312 B | 45.146 s | 10,484 B/s | 49.894 s from device eject trigger to success |

For the successful XIAO run:

- safe media handoff found the target 601 ms after the device observed eject;
- the complete supervised run took 66.105 s, including service stop/start,
  forced entry, application return, and post-run stability checks;
- the RAK application USB identity was stable 3.088 s after the XIAO reported
  success;
- reinstalling the updater and verifying the persisted QSPI state took
  26.946 s, including 23.024 s from stable serial bootloader discovery through
  `nrfutil` completion.

## Timeout and clock behavior

The DFU bank inactivity interval is 360,000 ms (six minutes). It starts when
DFU initializes and restarts on valid peer packets. Keeping this near five
minutes is intentional: it gives a slow or reconnecting sender room to recover,
while an abandoned session eventually exits instead of holding a valid
application in DFU indefinitely.

USB entry has separate, shorter timing:

- an explicit serial/UF2 application request gets a 30,000 ms host-enumeration
  window;
- MakeCode-style single-tap entry gets 3,000 ms;
- physical double-reset recovery waits for user action rather than applying a
  startup timeout;
- a no-application device probes an active USB host for up to 30,000 ms before
  falling back to BLE.

A board's external low-frequency crystal setting cannot permanently remove
this recovery path. `board_init()` selects `CLOCK_LFCLKSRC_SRC_RC`, and
`ble_stack_init()` independently enables the SoftDevice with
`NRF_CLOCK_LF_SRC_RC`, calibration intervals 16/2, and 250 ppm accuracy. The
RTC timers and BLE recovery therefore use the calibrated internal LFRC on every
board. A physical high-frequency oscillator failure is different: the nRF52
radio requires that hardware and cannot be repaired by a bootloader policy.

The host regression `dfu_timeout_test` checks the full-range millisecond-to-RTC
tick conversion, including the 3 s and 30 s entry values. The six-minute bank
interval uses Nordic's constant-expression `APP_TIMER_TICKS`, which performs
64-bit arithmetic. `lfclk_source_test` pins both internal-RC selections and the
SoftDevice calibration settings.

## Disposition

No additional hardware rows can qualify this candidate for release. The live
cached-handle failure above is an ABI regression even though its completed RAK
and XIAO transfers remain useful transport evidence. Candidate `0x02040405`
supersedes it and carries the complete six-device install/restore matrix.
