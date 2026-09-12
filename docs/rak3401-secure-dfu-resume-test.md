# RAK3401 resumable BLE DFU laboratory profile

This is an opt-in, application-only implementation of the Nordic Secure DFU
**wire protocol**, for testing resume with the unmodified Nordic phone app.
It is not a production release and does not implement signed-package trust or
anti-rollback. Packages are explicitly unsigned; a mandatory whole-image
SHA-256 and the existing application-vector policy are checked before activation.
Signed envelopes are rejected rather than accepted without verification.

The default profile is unchanged. `SECURE_DFU_RAK3401_TEST` replaces Legacy BLE
DFU only on `wiscore_rak3401`, retaining USB CDC/UF2 recovery and the existing
LoRa mOTA path. Other boards, signed builds, dual-bank builds and recovery
profiles cannot enable this option. An explicit laboratory version is required.

## Resume behavior and limits

The bootloader keeps command metadata, cumulative offset/CRC, and a partial
4 KiB data object in static RAM across BLE disconnects. Executed objects have
already been written to flash. SELECT and CHECKSUM let the phone validate the
same package and continue from the confirmed byte offset, including a partial
object. Repeated EXECUTE is idempotent. CREATE can discard an unexecuted object,
but cannot reuse a buffer after a flash failure or completed image.
Rejected packets leave the accepted bytes and CRC unchanged, so protocol
mistakes can be retried without resetting. Flash/validation failures remain
latched; a timeout may leave an asynchronous flash operation owning the buffer.

Resume lasts only within the same powered bootloader session. Reset, loss of
power or DFU timeout loses that state; there is no persistent resume journal.
This remains a single-bank update: do not remove power during the test. Recovery
after an interrupted invalid image requires restarting the complete upload.

The BLE adapter preserves session state but clears connection-specific receipt
queues on disconnect. It waits for the successful final DATA EXECUTE receipt to
finish transmission before activation. A repeated COMMAND EXECUTE on reconnect
must not activate prematurely. Flash operations are bounded, feed the watchdog,
and do not recursively dispatch BLE writes while flash owns an object buffer.
Transiently blocked receipts are retried from the existing main loop, at
100 ms intervals, even if there is no pending transmission-complete event.
The shared Legacy/Secure bonded cache-change path initializes system/user
attributes once per connection. Retrying the Service Changed indication does
not reset DFU notification subscriptions established by the peer. Failed
attribute initialization remains retryable until both setup calls succeed.

Receipt-queue overflow requests a link disconnect without closing the DFU
transport or clearing resumable data. Until reconnect, all writes (including
CCCD re-subscription), receipt retries and transmit-complete activation are
blocked. Outstanding notification counters are retained until DISCONNECTED;
an old completion cannot be mistaken for a new final EXECUTE receipt. The
ordinary disconnect handler restarts advertising for resume.

Receiving all data bytes is not activation. If final DATA EXECUTE is missed,
the last object remains in RAM and the application is not activated. Reconnect
with the same package before the DFU timeout and repeat EXECUTE to finish;
no firmware bytes need to be resent when the full-image offset/CRC matches.
If EXECUTE ran but its notification was lost while the device remained in DFU,
repeating it is idempotent. Reset/power loss/DFU timeout still requires a full
upload. If the board already activated and booted, verify the application
instead of assuming that an absent DFU advertisement indicates failure.

The Python bench sender (Python 3.11 or newer) retries only the final DATA
EXECUTE when its notification is missing: one attempt immediately, then at
least two seconds between attempts, within a single 30-second deadline that
includes GATT writes. A valid EXECUTE receipt stops retries. A rejected or
malformed response aborts; a failed or stalled ATT write is not overlapped or
retried. No firmware data or CREATE is resent by this retry loop.
A valid DFU EXECUTE receipt is authoritative even when the concurrent ATT
write fails or remains pending. After a write error, a queued or late receipt
can still confirm within the original deadline; a write error alone cannot.
If the link closes, no more writes are sent; a receipt already being dispatched
may still confirm within the original deadline. Without confirmation the
sender logs `UNCONFIRMED` and exits unsuccessfully, never `PASS`. It does not
automatically reconnect or verify the application after boot. This change is
in the bench sender, not the Nordic phone app or the XIAO transmitter firmware.

The service is `FE59` with standard Secure DFU control/data characteristics.
The advertised name remains `3401_DFU`. The open DFU address uses factory address
plus two instead of the Legacy profile's plus one to avoid stale phone GATT
caches. Do not infer authentication from the protocol's name or service UUID.

## Build

Use Arm GCC 14.2.Rel1, and a separate build directory:

```sh
cmake -S . -B cmake-build-rak3401-secure-test \
  -DBOARD=wiscore_rak3401 \
  -DSECURE_DFU_RAK3401_TEST=ON \
  -DMOTA_BOOTLOADER_TEST_BUILD=ON \
  -DMOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040707
cmake --build cmake-build-rak3401-secure-test
```

The equivalent Make variables use `1` instead of `ON`. The test flag is included
in Make's build-profile fingerprint, preventing reuse of stale normal-profile
objects. Do not use this version override for production releases.

The review-fix executable uses 40,074 of 40,784 flash bytes, leaving 710 bytes.
Static RAM usage is 35,564 bytes, excluding the separate fixed 64 KiB mOTA arena.
This implementation adds a small static object buffer; it does not repurpose
the retained mOTA arena or require a late heap allocation.

## Phone package and test

Generate a package from an application-only BIN or validated Legacy DFU ZIP:

```sh
python tools/generate_secure_dfu_test.py \
  --application application.bin --output RAK3401-secure-test.zip
```

The generator is fixed to RAK3401 hardware ID `0x3401`, S140 firmware ID `0xB6`
and application base `0x26000`. It does not accept bootloader or SoftDevice
payloads. The ZIP contains only `application.bin`, `application.dat` and
`manifest.json`. Use this new Secure DFU package, not the earlier Legacy ZIP.

In the Nordic DFU phone app:

1. Keep the RAK3401 powered and enter BLE DFU; select `3401_DFU`.
2. Choose the Secure DFU test ZIP. **Disable resume must be OFF.** If packet
   receipt notification settings are exposed, use PRN 8.
3. Start the upload, move the phone out of range after progress is visible,
   then return within the bootloader's approximately six-minute idle timeout.
4. Allow reconnection, or retry the same ZIP if the app asks. Do not reset the
   board or select a different image. Check that progress continues from the
   retained offset rather than uploading the entire image again.

Phone progress UI may briefly reset while reconnecting; the negotiated offset
and skipped data, rather than that initial display alone, determine true resume.
Stock-phone interoperability requires a manual acceptance test, not something
the custom bench sender alone can prove. The user-observed phone run is recorded
below separately from the instrumented bench tests.

## Qualification on 2026-09-11

Source baseline: `2b138473ace88dff24006af108a6ed9566e6168f` plus this uncommitted
laboratory change. Test version: `0x02040704`; build timestamp pinned with
`SOURCE_DATE_EPOCH=1789119612` for cross-platform comparison.

- Windows and Linux builds of RAK3401 Secure DFU, T096 normal and T114 normal
  matched SHA-256 for all 12 BIN/HEX/MBR-HEX/MBR-UF2 artifacts.
- Linux `make -C test -j2 check` passed, including the actual C protocol core.
- Protocol tests exercise partial command resume, byte/object boundaries,
  repeated execution after receipt loss, CRC rollback, PRN, malformed metadata,
  10,000 randomized parser inputs, hash rejection and flash-failure latching.
- The protocol tests passed with AddressSanitizer and UndefinedBehaviorSanitizer.
  Existing sanitizer targets also passed. A separate source guard checks the
  final DATA-only receipt/activation condition; it is not a mocked SoftDevice test.
- Native Windows protocol tests and BLE policy/layout source guards passed.
  The existing Windows build-profile fixture requires unavailable symlink
  privileges; that fixture was run successfully on Linux instead.
- CMake rejection tests passed for another board, missing test-version settings,
  signed firmware, dual-bank firmware and the recovery profile.

Final bootloader BIN SHA-256:
`05c63b402d8adc8089b3f7612b1167e1280fdb36d2b6b682e8b983784bc6ad8c`.
The board-bound 40,960-byte image has manifest CRC32 `0xFFF03483`.

The application-only test ZIP SHA-256 is
`d2137451d3655343de319e9edfd5d0dc707f12a3fb0554ac606f35c9be1d6a59`.
Its 582,828-byte application SHA-256 is
`5212fbbfafa579897a604f20e10f976907bb1307c146514e4c23ab6a68a22ca0`.
It reinstalls the Pi RAK3401's existing Full Companion image unchanged.

An earlier candidate completed a real BLE transfer with a deliberate disconnect
at byte 131,195 (22.5%). Reconnection reported exactly that offset and CRC32
`0xCA51A01A`, and the remainder completed. Full SWD readback matched the expected
application; the original name, radio, filesystem region, MBR, SoftDevice and
UICR were preserved.

The final candidate repeated the real 582,828-byte BLE test successfully using
244-byte packets and PRN 8. It disconnected at byte 131,195, reconnected with
that exact offset and CRC, transferred only the remainder, delivered the final
receipt and performed the expected target-initiated disconnect. Full SWD
readback confirmed the exact application and bootloader hashes above. The
Companion returned normally with its saved name/radio and source-only OTA role;
the entire `0xD4000..0xF4000` filesystem region, MBR, SoftDevice and UICR matched
the baseline. Temporarily stopped Pi services were restored after application
return.

### Manual phone resume acceptance

After the idle DFU entry timed out, the same verified candidate was put back
into a fresh DFU session. The user uploaded the new Secure DFU ZIP using their
phone, moved out of Bluetooth range until the transfer paused, and reported
that it came back around 44%, followed by successful completion. This is a
successful user-observed phone resume test; no phone-side packet trace or exact
resume byte count was captured. The phone model, OS and app version were not
recorded, so this is not a claim of coverage across all phone/app combinations.

An independent post-phone-test readback on the identified RAK3401 matched all
582,828 application bytes and the exact bootloader hash above. MBR, SoftDevice,
UICR and the entire `0xD4000..0xF4000` filesystem region matched the pre-test
baseline. Saved name/radio and the original source-only Companion role were
unchanged. The readback did not halt or reset the CPU, and serial health checks
passed both before and after it. Both temporarily affected Pi services were
restored and confirmed active. The board was left running its application,
not in DFU. This result does not add power-loss/reset-persistent resume support.

Only the identified Pi RAK3401 was flashed. Its factory ID was checked before
every debug write. Bootloader-only programming was verified by full flash/UICR
readback, and a pre-test recovery backup was copied off the Pi. Private device
identities, keys, backups and raw logs are not committed to Git. The default
profiles' LoRa OTA hardware qualification is recorded separately; this new
profile's LoRa path has not been re-qualified on hardware in this test.

## Review-fix validation on 2026-09-11

The three review fixes use laboratory version `0x02040705`; the earlier phone
and hardware qualification above applies to `0x02040704`, not this revision.
No device was flashed during the review-fix work.

- Invalid-connection and GATT-timeout notification errors discard only the
  connection's receipts, preserving the protocol session. Races when closing
  after final receipt delivery or handling a GATT timeout are also tolerated.
  Unexpected SoftDevice errors still fault; Legacy behavior is unchanged.
- Packet rejection and receipt-queue overflow no longer poison the flash
  buffer. A reconnect can retry from the last accepted offset. Flash failures
  and timeouts still block buffer reuse, including after a late callback.
- The bench sender re-executes a complete final object on resume even when
  its length is less than 4 KiB. No firmware bytes are resent at 100%.
- All 29 Secure DFU tests passed on Windows and Linux: 15 protocol/source-guard
  tests, 9 BLE/transport tests, and 5 bench-sender tests. The BLE tests compile
  the complete production adapter using SDK event types and mocked hardware;
  the sender tests run the real Python sender against that adapter. The shared
  close/timeout paths are extracted and executed with both profile settings.
- Linux AddressSanitizer/UndefinedBehaviorSanitizer runs passed for the native
  protocol and BLE adapter, including the bench-sender scenarios. Leak detection
  was disabled for the Python-hosted sanitizer runs.
- Windows USB-helper tests (18), Legacy BLE client tests (83), and BLE
  policy/cache/advertising/DIS and Legacy bounds guards passed.
- Arm GCC 14.2.Rel1 Windows builds passed for RAK3401 Secure DFU, T096 normal
  and T114 normal. Flash use was 39,914 / 40,014 / 40,415 bytes respectively,
  within each board's 40,784-byte executable envelope. RAK3401 static RAM
  remained 35,560 bytes plus the separate retained 64 KiB mOTA arena.

The review-fix RAK3401 BIN SHA-256 is
`d34ae16a06a07968b042c04469c95717eae321661509ac8ced6a3c255172a7a9`;
manifest CRC32 is `0xBBB58C6A`. Builds used `SOURCE_DATE_EPOCH=1789119612`.
These builds have not yet been re-qualified over physical BLE or LoRa.

Run the new host regressions with:

```sh
python3 test/secure_dfu_test.py
python3 test/secure_dfu_ble_test.py
python3 test/secure_dfu_uploader_test.py
```

All three are included in `make -C test check`.

## Receipt/completion follow-up validation on 2026-09-11

Laboratory version `0x02040706` fixes two further review findings:

- A blocked first receipt is retried by a rate-limited main-loop poll without
  relying on another peer write or HVN completion. The poll runs after scheduled
  work and exit checks, and does not run after transport teardown. It allocates
  no heap or additional timer and adds one 4-byte timestamp. It does not refresh
  the peer-activity timeout.
- The bench uploader requires a valid final DATA EXECUTE acknowledgment before
  PASS, plus an observed disconnect. Disconnect after the last data packet,
  before EXECUTE, or without its receipt cannot pass. EXECUTE response length
  is checked. PASS means an acknowledged DFU transfer, not independent proof of
  application boot; the log now says `disconnect_observed`, not that the device
  initiated it. Missing confirmation requires retry/verification, not assuming
  success.

All 39 Secure DFU tests (15 protocol/source, 14 BLE/transport, 10 sender) passed
on Windows and Linux, including Linux ASan/UBSan runs with leak detection
disabled. New tests cover readiness recovery without TX events, retry rate
limiting and RTC wraparound, disabled CCCDs/disconnect, final-receipt activation
ordering, missed EXECUTE and lost acknowledgments, malformed receipts, and
missing final disconnect. Recovery tests finish the same upload without
resending firmware after either missed EXECUTE or a lost EXECUTE receipt.
The 18 USB-helper tests, 83 Legacy BLE client tests, and related BLE/bounds
guards also passed on Windows.

Arm GCC 14.2.Rel1 Windows builds passed for RAK3401 Secure DFU, T096 normal and
T114 normal. Their executable flash sizes are 40,042 / 40,014 / 40,415 bytes.
RAK3401 static RAM is 35,564 bytes plus the unchanged 64 KiB retained arena.
With `SOURCE_DATE_EPOCH=1789119612`, RAK3401 BIN SHA-256 is
`7d2477c50a7f16da258187cac8b4b1628041223ee871ef35a64ac8d61080288d`;
manifest CRC32 is `0x8EB5F155`.
No hardware was flashed and no physical BLE/LoRa re-qualification was performed
for this revision. Changes remain uncommitted.

## Bounded sender EXECUTE retry validation on 2026-09-11

The bench sender now has the final-only 30-second retry policy described above.
All 48 Secure DFU tests passed on Windows and Linux (15 protocol/source,
14 BLE/transport, 19 sender). The 19 sender tests also passed with the real C
core and BLE adapter instrumented by Linux ASan/UBSan. Added coverage includes
missed EXECUTE, multiple lost receipts, late receipt plus disconnect, the retry
deadline, stalled GATT write, explicit rejection, unchanged nonfinal execution,
and cancellation cleanup. Recovery does not resend image data or repeat image
validation/activation. Timing tests use shortened intervals while checking the
production constants separately.
A separate Windows check with production timing and a silent mocked peer sent
15 EXECUTE attempts and reported `UNCONFIRMED` after 30.004 seconds.

T096, T114 and RAK3401 Secure CMake build checks passed with no work needed:
this follow-up changes only the bench Python sender, its tests and these notes.
The bootloader images and hashes above are unchanged. No hardware was flashed
and the changes remain uncommitted.

## Bonded subscription and final receipt race validation on 2026-09-11

Laboratory version `0x02040707` adds the shared per-connection attribute guard.
The bench sender observes the final protocol receipt independently of the ATT
write result, without overlapping or retrying an uncertain write. Valid receipt
plus write error, a late receipt after write error, and receipt plus hung write
all complete correctly. Malformed/rejected receipts still abort, missing
receipts remain unconfirmed, and cancellation cleans up both asynchronous tasks.

All 53 Secure DFU tests passed on Windows and Linux (15 protocol/source,
14 BLE/transport, 24 sender), also under Linux ASan/UBSan. The expanded GATT
cache test compiles the actual shared helper and connect/disconnect cases for
Legacy and Secure configurations. It passed on both hosts and under Linux
sanitizers, covering indication backpressure, preserved subscriptions, failure
in either attribute setup step, reconnect initialization, and unbonded links.
The 83 Legacy client tests and BLE policy/advertising/DIS/bounds guards also
passed on Windows.

Fresh Arm GCC 14.2.Rel1 Windows builds passed for RAK3401 Secure DFU, T096 normal
and T114 normal. Their executable flash sizes are 40,074 / 40,062 / 40,463 bytes;
static RAM is 35,564 / 31,220 / 31,320 bytes, plus each unchanged 64 KiB arena.
With `SOURCE_DATE_EPOCH=1789119612`, the RAK3401 BIN SHA-256 is
`92bdbcd57852868a1446ad4fde277b62770d3f6b9f0db506bcb7e6717228d871`;
manifest CRC32 is `0x9C2EAA70`. Artifacts are in
`cmake-build-review-final-races/<board>/`.
No hardware was flashed during this software-validation step. Subsequent
physical qualification is recorded below. Changes remain uncommitted.

## Secure07 SWD/BLE hardware qualification on 2026-09-11

The MercerWoodMesh Pi's RAK3401 was identified independently by USB serial and
both FICR device-ID words before debug writes. Laboratory bootloader
`0x02040707` (SHA-256 above) was installed with a bootloader-only SWD write.
Full flash and UICR readback matched the candidate and proved all bytes outside
`0xF4000..0xFE000` unchanged from the pre-test baseline.

The test application is Companion `v1.17.1.6-cli3-test-bc0fb2c3`, 617,216 bytes
at `0x26000`, SHA-256
`5d0c3cc8fa49bb57cfd451b3c1a434246fb71edf9b5d89a280d952935d99376c`.
Transfers use a generated unsigned Secure DFU package containing exactly this
existing application, not a new application build.

- **Blocked first notification:** four real-BLE SELECT transactions passed
  after SWD injected one `sd_ble_gatts_hvx` return of BUSY, RESOURCES,
  INVALID_STATE or SYS_ATTR_MISSING. A hardware breakpoint checked the actual
  call site and skipped only that SVC call, leaving the candidate flash intact.
  Each reply arrived in 180-186 ms with one control write, an empty receipt
  queue afterward, and no failed session. These were injected API errors, not
  naturally reproduced SoftDevice resource failures.
- **Full image received, final EXECUTE omitted:** the unmodified bench sender
  transferred all 617,216 bytes using its selected 20-byte packets and PRN 8.
  The harness stopped immediately before final EXECUTE and disconnected.
  Direct SWD reads showed 614,400 bytes committed, the complete 2,816-byte
  final object still staged, and `executed=completed=failed=0`. Reconnection
  selected offset 617,216 / CRC32 `0x73F578E7`, received the final acknowledgment,
  and observed disconnect. A write counter proved **zero DATA-characteristic
  bytes resent**, including metadata. No reset was used during this recovery.
  Subsequent full flash/UICR readback and ASCII CLI queries passed: application
  and bootloader were exact; MBR/SoftDevice, filesystem, MBR parameters and UICR
  were unchanged; configured name and radio settings matched the baseline.
- **Mid-object link interruption:** with a reported 244-byte write capacity,
  the sender disconnected at byte 131,195 (123 bytes into a 4 KiB object).
  Reconnection verified precisely offset 131,195 / CRC32 `0xC7444042` and
  continued the same image. The private harness allowed BlueZ's asynchronous
  capacity property to settle before selecting packet size; no oversized
  probing or speculative write capacity was used.
- **Production 30-second unconfirmed deadline:** after the second full-image
  transfer, the harness omitted all final EXECUTE writes while keeping the
  actual BLE link open. The production sender made 15 attempts and reported
  `UNCONFIRMED` after 30.005 seconds, never PASS. SWD then confirmed that the
  last object remained staged with `executed=completed=failed=0`.
- **Retry recovery and late receipt after a write error:** without resending
  data or resetting, a new completion attempt omitted three more EXECUTEs.
  SWD again confirmed the unexecuted final object. The fourth EXECUTE was
  actually transmitted, after which the harness raised an ATT completion
  error. The production sender logged that error, accepted the subsequent
  real DFU acknowledgment, observed disconnect and passed. Recovery took
  8.273 seconds including debug inspection. The omitted commands and host
  error were deliberate harness injections, not claimed radio/BlueZ failures.

The second transfer also passed independent full flash/UICR readback and ASCII
CLI health/configuration checks. The application and Secure07 bootloader are
byte-exact, and MBR/SoftDevice, filesystem, MBR parameters and UICR still match
the baseline. No additional production firmware fix was needed during these
runs. This hardware qualification does not re-test a bonded phone's GATT-cache
transition, stock-phone acceptance or LoRa OTA; the compiled bonded-cache
regressions and earlier phone/LoRa records remain separate evidence.
The board was left running its original application with Secure07 installed;
both paused Pi services (`mctomqtt` and `ModemManager`) were restored to active.
Results and harness sources are also retained locally under the ignored
`cmake-build-review-final-races/hardware-07/` directory. No commit or PR was made.

Private baseline captures, SWD logs and test reports are retained on the Pi in
`/home/mikec/hwtest/runs/secure-dfu-07.ov1uXZ/`; memory captures are not committed.
An initial harness permission problem and an OpenOCD target-algorithm failure
were resolved before qualification. Programming used reset-and-halt; live SWD
inspection used direct memory reads rather than target-side CRC execution.

## Extended Secure07 physical qualification on 2026-09-11

The same identity-gated RAK3401 and byte-exact Secure07 image were used for
these additional tests. BLE tests used the 617,216-byte CLI3 fixture identified
above; LoRa used the receiver fixtures described below, then restored CLI3.
All fault injections below ran against the physical board, not the native
protocol model.

- **Lost receipt after completed final EXECUTE:** a hardware breakpoint at the
  actual `sd_ble_gatts_hvx` call injected INVALID_CONN_HANDLE (`0x3002`) for
  the final receipt. SWD confirmed all 617,216 bytes committed and
  `executed=completed=1`, `failed=0`, with no remaining data object. After
  disconnect/reconnect, the same package completed with zero DATA bytes resent.
  Full flash/UICR readback and application CLI checks passed.
- **Reset during incomplete transfer:** 8,192 bytes were committed and another
  123 bytes staged in RAM, with an intentionally invalid initial stack pointer
  actually written to application flash. An ordinary SWD reset, without a DFU
  entry marker, returned to DFU instead of launching that damaged image. Live
  session state was cleared; a real BLE SELECT returned `(4096, 0, 0)`.
- **Real idle timeout:** the same incomplete-transfer condition was left alone
  for 390 seconds, exceeding the actual 360-second timeout. No accelerated
  timer, target halt or target protocol traffic was used during the wait. The
  board again remained recoverable, with fresh session state and SELECT offset
  zero. This proves recovery after timeout, not persistent resume across reset.
- **USB recovery after reset and timeout:** the physical UF2 drive accepted the
  original application, synchronization completed without kernel I/O errors,
  and the board returned to the application. Each recovery passed full
  flash/UICR readback, exact application/bootloader checks, and name/radio/CLI
  checks; MBR, SoftDevice, filesystem and UICR matched the baseline.
- **XIAO sender regression:** the physical XIAO nRF52840 ran its previously
  qualified active/confirmed updater image
  `d848a3b6191911878089e1898e5aa31232148977a83907ffe9c1f9ca6a1707cb`.
  A ZIP_STORED repack preserved all Secure package members byte-for-byte, and
  the package was read back from the XIAO before use. The XIAO itself sent all
  617,216 application bytes over BLE to the Secure07 RAK3401 on its first
  attempt, taking 57.800 seconds. Its terminal result was correctly
  `DONE / BOOT_UNVERIFIED` (16). Independent SWD and application CLI checks then
  proved the exact application had booted and all protected regions matched.
  The sender was returned to IDLE with `auto_flash=0`.
- **Corrupt image through actual flash/hash validation:** one bit at application
  offset `0x5000` was flipped while the init packet retained the original
  application's expected SHA-256. All 617,216 bytes traversed real BLE and
  flash writes with valid transport CRCs. Final EXECUTE returned `600405`
  (invalid object), with `committed=617216`, `failed=1`, `completed=0`.
  Direct flash readback matched the deliberately corrupt image SHA-256
  `ba01f3f9d6e26b703d73749ab9c8a51c13dd271a8bbf9f503f7a033734401ba6`.
  Thus rejection came from the physical final-image validation path, not a
  mocked flash result or an earlier host-side package check.
  USB recovery then passed exact full flash/UICR and application CLI checks.
- **Physical power interruption:** after committing 8,192 bytes and staging
  another 123 bytes, the VM's existing `Xmas tree` control cut power to the
  Pi and USB hub. The operator had confirmed that the RAK3401 had no alternate
  supply. SSH became unreachable; after power restoration, the Pi had a new
  boot ID and the USB devices re-enumerated. SWD showed the incomplete BLE
  session cleared, while the deliberately invalid application vector remained
  in flash. Real BLE SELECT returned `(4096, 0, 0)`; UF2 recovery and exact
  full flash/UICR plus CLI/configuration checks passed again. The soak logger
  was stopped and synchronized before the cut, then returned to active.

The physical power test passed, but its automatic switch-control wrapper did
not: Google Home's displayed state lagged the actual switch, causing its
15-second confirmation deadline to expire. The initial fail-safe `on` was a
no-op against stale UI state. Once the page reported off, an explicit existing-
CLI `on` restored power, independently verified by SSH, a changed boot ID and
target readback. No control/fail-safe process was left running. A displayed
Google Home state alone is not reliable evidence of physical power here.

**Bonded application-to-DFU handoff passed on both profiles.** The Pi used the
real application's stored bond and successfully executed a protected NUS
device-info command before requesting buttonless DFU. It then reused that
same bonded address without unpairing, deleting BlueZ cache files or removing
the device. SWD confirmed valid peer data, initialized per-connection attributes
and no pending Service Changed indication. The Secure service was discovered
and three SELECT replies were received, including after MTU acquisition. The
Legacy build likewise exposed DFU revision 8 at its new handle (20 instead of
the application's 36) and returned three valid received-size notifications.
The application returned successfully after each test. These are physical
BlueZ handoff/subscription checks; the precise indication-retry-after-CCCD
interleaving remains covered by the compiled fault-injection regression, not
claimed as a naturally reproduced hardware race or a stock-phone test.

The temporary Legacy07 RAK3401 build used 39,430 executable flash bytes and
31,224 static RAM bytes, plus the unchanged 64 KiB retained arena. Its BIN
SHA-256 is `826f438b35471dc54b005bbc258eac17a8fec61514286282be3d8d9d5681ec6d`
and manifest CRC32 is `0xF87344A7`. Programming was limited to the bootloader
region; Secure07 was restored before the LoRa regression.

The LoRa fixture uses the previously qualified receiver A image
`72678107e14e34ef7614677467106245d438f4b5558c4cfced1c4befdeb5d4b4`
(490,032 bytes), because the original Companion image is seeder-only. The
T114 sender is USB serial `651F8E496197F882`, application base hash
`541784A9C1DA62EB`. Both use temporary 909.950 MHz / 500 kHz / SF5 / CR5
settings; the receiver reports effective RXPS level 8 and preamble 128.

The first LoRa attempt is not counted as a pass: the receiver reset while
the initial download was being started. Its subsequent `powerlog` reported
Watchdog, with the stored system-watchdog preference off and reboot interval
disabled. A direct SWD read subsequently confirmed `WDT.RUNSTATUS=0`, and the
next qualification attempt reused that settled application without reflashing
it. Another preflight attempt stopped on an empty serial identity reply;
bounded retries were added only for read-only CLI queries. Neither attempt
reached bootloader delta application, and no production source change was made
to classify either as a successful LoRa transfer.

**The subsequent physical hybrid LoRa update passed.** The T114 delivered the
154,802-byte signed package (MID `01565E66`, 76 blocks) in 941.368 seconds.
Direct SWD reads verified that its 90,112 flash bytes and 64,690 retained-RAM
bytes matched the package exactly before installation. The receiver verified
the trusted signer and installed the update; its new 571,952-byte application
booted with base hash `B8B060400AAB9077` and bootloader result `B8` (success).
Full flash readback matched application SHA-256
`728160e89c4fe833a96065c5c9307210d976a0d0fb28ee281d06e1d731fba1e6`.
The Secure07 bootloader remained byte-exact, and MBR/SoftDevice, MBR parameters
and UICR were unchanged. The source and receiver were returned to their normal
909.5 MHz / 62.5 kHz / SF7 / CR5 radio settings, and the original CLI3 Companion
application was restored through USB and verified by full readback and CLI.
The successful run is recorded in `extended-lora3.json`.

The private USB harness initially assumed a CDC port already existed in BLE
DFU. It was corrected to enter UF2 through the FICR-gated debug connection
before waiting for USB enumeration; no firmware change was involved. A separate
Pi Bluetooth-controller command timeout interrupted package staging onto the
XIAO before target DFU was triggered. Reloading the Pi's `hci_uart` driver
restored the host controller without resetting the RAK3401; the package staging
and readback were then repeated successfully. These are harness/host events,
not counted as target firmware failures or successful DFU transfers.

The 53 Secure host tests and compiled Legacy/Secure GATT-cache regression were
also rerun successfully on Windows. T096 and T114 CMake verification reported
no rebuild necessary. Fresh Linux Arm GCC 14.2.Rel1 CMake builds were then run
for Secure RAK3401, Legacy RAK3401, T096 and T114 with test version
`0x02040707` and `SOURCE_DATE_EPOCH=1789119612`. All sixteen resulting image
files (`bootloader.bin`, `bootloader.hex`, `bootloader_mbr.hex` and
`bootloader_mbr.uf2` for each profile) matched the Windows SHA-256 hashes
exactly. Linux used Unix Makefiles; Windows used Ninja. ELF debug information
is not part of this byte-identity claim. The full Linux `make -C test check`
suite also passed against this synchronized source tree.

No production firmware source fix was needed for these runs. All five requested
extended hardware categories are covered: lost final receipt; bonded Secure
and Legacy handoff; reset, timeout and physical power-cut recovery; corrupt
image rejection; and XIAO BLE, USB and hybrid LoRa transport regressions.
Stock-phone acceptance was not repeated, and the exact GATT-cache race remains
separate compiled fault-injection evidence as noted above.

Final cleanup (`extended-final.json`) confirmed the original Companion and
Secure07 bootloader byte-for-byte, with unchanged MBR/SoftDevice, MBR parameters
and UICR. After an ordinary reset, plain ASCII `ver` succeeded without a
terminal-mode negotiation. The configured name and normal radio settings were
correct, OTA seeding was idle with no folder attached, and the active Companion
reported no trusted signer keys. LoRa staging and fixture configuration writes
are not claimed byte-identical to the original filesystem; in particular this
check does not prove removal of a signer from a different role's configuration.
The XIAO was independently checked again after the power cycle: IDLE and
`auto_flash=0`. Both `mctomqtt` and `ModemManager` were restored to active, and
the memory-soak logger was active. No commit or PR was made.

## Post-commit receipt-overflow hardening (host-verified)

Review of `c3f51cd` reproduced a same-link re-subscription race: queue overflow
cleared counters while older notifications still existed in the SoftDevice.
Re-enabling notifications and repeating final EXECUTE could then activate on
an older CHECKSUM notification's completion. The fix quarantines that link and
requests only its disconnect, preserving the session for a real reconnect.

The expanded compiled-adapter regressions failed before the fix and pass after
it. They cover a final receipt already queued or still blocked, 12 outstanding
notifications, late completions, same-link writes/re-subscription, partial-object
resume, idempotent final completion after reconnect, and benign versus unexpected
disconnect errors. All 56 Secure protocol/adapter/sender host tests and the
compiled Legacy/Secure GATT-cache checks pass on Windows.

A separate RAK3401 candidate built with Arm GCC 14.2.Rel1 and explicit test
version `0x02040708` uses 40,186 of 40,784 executable flash bytes (598 free) and
35,564 static RAM bytes, plus the unchanged 64 KiB retained arena. T096 and T114
CMake checks also pass. This candidate has not been flashed or physically
re-qualified; the Secure07 hardware and cross-platform records above describe
the preceding image, not this overflow fix.

## Protocol references

- [Nordic Android SecureDfuImpl](https://github.com/NordicSemiconductor/Android-DFU-Library/blob/main/lib/dfu/src/main/java/no/nordicsemi/android/dfu/SecureDfuImpl.java)
- [Nordic iOS SecureDFUExecutor](https://github.com/NordicSemiconductor/IOS-DFU-Library/blob/main/Library/Classes/Implementation/SecureDFU/DFU/SecureDFUExecutor.swift)
- [Nordic DFU protobuf definition](https://github.com/NordicSemiconductor/pc-nrfutil/blob/master/nordicsemi/dfu/dfu-cc.proto)
