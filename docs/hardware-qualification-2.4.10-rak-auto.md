# RAK adaptive bootloader update qualification

Qualification performed on 2026-09-29. The production-tag checks are listed
first; the later preview sections describe separate development images.

## Final production tag: 2.4.10

Source tag `v0.11.0-OTAFIX2.4.10` points to
`936c4174f6d115cd64a0430c7b44af3edab1a533`.
[Production workflow 36561372143](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/actions/runs/36561372143)
passed all 33 jobs: Make/CMake for all 29 boards, host/sanitizer tests, both
display-controller feature families, signed mOTA packaging and recovery
archive validation. Independent local production builds of both RAK images
match the downloaded CI bootloader bytes exactly.

The downloaded and uploaded artifacts were checked for all 24 normal profiles,
24 signed exact-profile bootloader packages and 29 separate recovery profiles.
Every archive checksum, package signature, image hash, identity, capability
record and packed version was verified. All 80 original release asset sizes
and GitHub SHA-256 digests match the verified local files.

### Official signed LoRa packages: both RAK boards PASS

The T114 served the official release packages; both boards fetched all 40
blocks and authenticated the official public signing key before installation.

| Device | Package MID | Image hash prefix | Installed CRC | Preserved application hash |
| --- | --- | --- | --- | --- |
| RAK3401 | 7EA13BD2 | 6106857BE49670DB | 3053C49A | 5CA252565696C1D4 |
| RAK4631 | 168DB259 | E0839208859B0C6A | 9D4C29ED | CE03698DC21A151D |

Both report `v0.11.0-OTAFIX2.4.10`, their standard `3401_DFU` / `4631_DFU`
identities, ABI 3 and caps `0A`. RAK3401 retains its 590,176-byte application
body and internal store. RAK4631 retains its 620,244-byte application body and
returns to its fitted 2 MB QSPI application store after internal bootloader
staging. Read-only SWD verification matched all 40,960 RAK3401 release bytes.

### Final bootloader applying a successor: RAK3401 PASS

The application correctly refused a same-version reinstall with
`candidate bootloader is not newer`. To exercise the final bootloader apply
code, a separate temporary-key-signed qualification image used packed version
`0x02040B01` (2.4.11-preview.1), MID `4A36605C`, image hash prefix
`64DF995881858CA3`. The device fetched all 40 blocks over LoRa, authenticated
and installed it through the ordinary bootloader command, and reported CRC
`D50E0B92` while retaining application hash `5CA252565696C1D4`.

That successor is a disposable hardware test, not a published release. The
RAK3401 was restored to official 2.4.10 through identity-guarded SWD and its
application hash checked again. The temporary trusted key and local signing
seed were removed.

### Physical USB information: RAK3401 PASS

In UF2 mode, the actual drive exposed a 114-byte `INFO_UF2.TXT` with the
2.4.10 version, RAK3401 model, `3401A` board ID, build date and S140 FWID
`0x00B6`. Its 52-byte `INDEX.HTM` redirects to `https://rakwireless.com`.
`CURRENT.UF2` is present with size 1,908,736 bytes. The independent host
volume tests also verify FAT chains, readback and guarded writes.

### Final-tag Nordic Bluetooth DFU: RAK4631 PASS

Nordic nRF Connect 4.24.3 on the Android 5.1.1 phone installed the 620,300-byte
unified application ZIP on the official 2.4.10 RAK4631 bootloader. The first
attempt timed out before the first DFU opcode (GATT connection timeout/error
133); reconnecting and retrying the same file completed initialization,
transfer, validation response `10-04-01`, and activate/reset opcode `05`.

After reboot the device still reports the official bootloader CRC `9D4C29ED`,
ABI 3/caps `0A`, application body 620,244 bytes, hash `CE03698DC21A151D` and
`QSPI store:2048K`. The earlier exact standard 1.17.1.5-to-1.17.1.7 and
MeshCore Open phone tests below remain separately labelled prototype checks.
The Open test used the fixed local APK; the published RC2 APK does not contain
that app-side reply fix.

The folder source was stopped, temporary signer keys were removed from both
boards, normal radios were restored, RAK4631 OTA reach returned to three hops,
and the T114 advertisement interval returned to 1440 minutes. Both RAKs were
left on official 2.4.10 with their verified applications.

## Recovery information restoration for 2.4.10

The final release preparation also restores populated USB info/index files and
the Heltec T1/T096/T114 model/version/transport screens. Fixed directory entries
and direct display-line rendering avoid the previous empty-file/DFU-only tradeoff.
The restored screen code was rendered for all three actual board definitions in
USB and Bluetooth modes and checked with ASan/UBSan; these are software renders,
not photographs of physical screens.

Space is recovered by looping over the five bounded delta geometry fields,
copying the contiguous byte-only manifest identity once, sharing rejection
cleanup, and using equivalent single-pass USB string/SHA output loops. The
full host and sanitizer suites pass after these changes, including image hashes,
signatures/identity rejection, metadata, USB FAT chains/readback/writes, delta
geometry and all update backends. Both display controllers also pass normal,
signed, dual-bank, signed-plus-dual-bank and recovery CMake builds.

A Make qualification using the production-length 2.4.10 strings and explicit
test packed version `0x02040AFF` fits RAK4631 in 40,777 executable/data bytes,
leaving seven bytes before CF2. It is a size check, not a release artifact.
The final production artifacts must come from the clean exact release tag.
Qualification builds of this restoration use `0x02040A05`; the earlier physical
preview.1 through preview.4 results below describe their respective images.

## Image contract and size

The compatible images keep `3401_DFU` / `4631_DFU`, ABI 3, codecs `0x0005`,
and privileged storage flags `0x0A`. Optional application QSPI and header W25
capabilities are in a separate 16-byte `MOTASTOR` record appended to the
unchanged 16-byte `MOTARAMA` record. The updated application sees effective
application flags `0x1E` while bootloader update validation still sees `0x0A`.
Bootloader packages always use internal `0xE2000..0xED000` staging.

GCC 14.2, CMake, production size options, compatible test version `0x02040A03`:

| Profile | Executable flash including initialized data | Bytes free |
| --- | ---: | ---: |
| wiscore_rak3401_auto | 40,612 | 172 |
| wiscore_rak4631_auto | 40,772 | 12 |
| heltec_t096 | 39,437 | 1,347 |
| heltec_t114 | 39,790 | 994 |

A separate RAK4631 size build with the production-length
`v0.11.0-OTAFIX2.4.10` strings and packed version `0x02040AFF` uses 40,777 bytes
(seven bytes free). It is a size qualification, not a tagged release artifact.
The executable limit remains 40,784 bytes; no flash regions moved.

The earlier preview.1/preview.2 Bluetooth and LoRa tests below used the initial
`*_AUTO_DFU` / `0x1E` prototype. The compatible preview.3/preview.4 checks are
listed separately so prototype results are not mistaken for final-image tests.

## Direct standard board update: RAK3401 PASS

Released OTAFIX 2.4.9 was installed on the identified RAK3401 via guarded SWD.
The new unified application reported `3401_DFU`, target `23818A80`, ABI 3,
caps `0A`, and released loader CRC `FEEB920F` before the test.

- The T114 served a normally signed package over LoRa, MID `A81B7173`.
- All 40 blocks were fetched through `ota pull A81B7173 flash`.
- `ota bootloader install A81B7173 4AA4DD4AFE440327` authenticated the package
  and queued the normal bootloader reset; no migration command was used.
- Installed version: `OTAFIX2.4.10-preview.3`; identity unchanged `3401_DFU`;
  caps unchanged `0A`; whole-image CRC `7A008AEC`.
- Application body 590,208 bytes and hash `0132AC4EF3532FE3` were unchanged.
- Read-only SWD verification matched all 40,960 installed bootloader bytes.

## Direct standard board update: RAK4631 PASS

Released OTAFIX 2.4.9 `4631_DFU`, target `2D0DF000`, CRC `A957950E`, was
installed locally before this test. The new unified application initially used
`internal store:252K` despite the fitted header W25Q16, as required by that old
loader's capabilities.

- The T114 served signed package MID `488B8649`; all 40 blocks arrived over LoRa.
- The ordinary install command authenticated image hash `D3CB96E58DCB1D2B`.
- The loader advanced to `OTAFIX2.4.10-preview.3`, CRC `74AE5D02`, retaining
  `4631_DFU`, ABI 3 and caps `0A`.
- Application body 620,260 bytes and hash `D839E39490D0D6C2` were unchanged.
- After reboot, the same application selected `QSPI store:2048K` by reading
  the new optional application-storage capability. No identity migration or
  application reinstall was required for this transition.

The local baseline setup first used a hand-generated DFU package with the
wrong Nordic device type. Serial nrfutil reported completion without activation.
After the bootloader's DFU timeout reset, a correctly labelled `0x0052` package
installed the recovery bridge, then the released board loader. Those local
setup retries were not LoRa failures; all results above were checked on-device.
Final source rebuilds of both compatible RAK binaries match the tested bytes.

## Hardware and applications

- RAK3401 USB serial `0B81C9C68D8D01B4`, without external NOR.
- RAK4631 USB serial `9AB3B64C641BA927`, with header W25Q16 fitted.
- Heltec T114 Companion `B861B9C8`, used as the LoRa folder source and as the
  phone's Companion. Source firmware: `v1.17.1-dev-687896fa`.
- Android 5.1.1 phones used for Nordic nRF Connect and MeshCore Open.
- No device backup was taken.

## Prototype: Nordic nRF Connect Bluetooth application update: PASS

The RAK4631 ran the new auto bootloader `OTAFIX2.4.10-preview.1` and the
standard, non-LoRa-OTA application
`v1.17.1.5-halo-keymind-cascade-dev-26303793`.

Nordic nRF Connect 4.24.3 installed the unmodified standard RAK4631 application
ZIP for `v1.17.1.7-halo-keymind-cascade-dev-2d03e098`. The phone performed the
application-to-bootloader handoff, streamed the image, received validation
success `10-04-01`, and sent Activate and Reset. USB `ver` subsequently reported
the exact 1.17.1.7 build, with the bootloader still at preview.1.

The app's subsequent ordinary GATT reconnect reported error 133 after the
successful reboot. This is not a transfer or validation failure. The repeater's
normal application does not continuously advertise the DFU service. This could
explain an apparent update failure report, but does not prove the cause of the
original user's report. Nordic 4.29.1 could not start on this Android 5.1.1 phone;
the test therefore used the official 4.24.3 APK.

## Prototype: MeshCore Open Bluetooth application update: PASS after app fix

The same RAK4631 was restored to the exact standard 1.17.1.5 application. The
official MeshCore Open `v9.5.5-rc.2` legacy APK loaded the standard 1.17.1.7 ZIP,
but its repeater Bluetooth update page timed out on `start ota`. The page created
a command service without subscribing to the Companion's response frames.

A local test APK from `android-5.1.1-compat` at `3170d3f` plus the response
subscription fix received the expected address `C3:C6:A8:FC:AD:A6` over LoRa.
The update was then started entirely through the phone's Bluetooth update page.
Nordic's embedded DFU library transferred 543,656 bytes in 74,774 ms, received
success for both Receive Firmware Image and Validate, then activated and reset.
MeshCore Open displayed completion at 100%. USB `ver` confirmed the exact
1.17.1.7 application and `get bootloader.ver` confirmed preview.1.

The APK SHA-256 is
`1136a961c621c7ead4bee216f86e12a71086e20991152379349123887127cacd`.
The full legacy Flutter suite passed 837 tests with two skips. New tests cover
both Companion reply formats, unrelated senders, stale command prefixes,
malformed frames, and listener cleanup. Analysis of the changed files is clean;
full analysis reports three existing style notices in `rans_coder.dart`.
The fixed APK is a local test build, not a published replacement for rc.2.

## Prototype: RAK3401 signed bootloader update over LoRa: PASS

The new `RAK_3401_repeater_unified_lora_ota` application fetched a genuinely
signed bootloader package from the T114 folder source over LoRa. A temporary lab
signing key was enrolled through the application's normal trust-key command.
Neither the application signature check nor its approval procedure was bypassed.

- Package MID: `D1F441E6`; payload: 40 blocks / 40,960 bytes.
- Confirmed image hash: `B36D748B37B689A4`.
- Source bootloader: `0x02040A01`; installed successor: `0x02040A02`.
- Application EndF body: 589,968 bytes; hash `6382AB031D71E80A` before and after.
- Result: `3401_AUTO_DFU`, ABI 3, capabilities `0x1E`, CRC `DB5C5D37`.
- SWD read-only verification matched every byte of the installed 40 KiB successor.

Earlier bootloader-only hardware checks also rejected a RAK4631 payload on the
RAK3401 and survived reset during the first compaction page with the old loader
and application intact. Those checks used a preapproved lab handoff; the real
LoRa test above separately exercises application authentication and approval.

## Prototype: RAK4631 bootloader update with external application storage: PASS

The unified RAK4631 application reported `QSPI store:2048K` before the transfer.
It fetched the signed package from the same T114 over LoRa, switched to internal
staging for the 40 bootloader blocks, and reported `bl:internal` at completion.
The normal `ota bootloader install` command authenticated and approved it.

- Package MID: `06A5C0B3`; confirmed image hash: `20248C30E2BBF9E7`.
- Bootloader advanced from preview.1 to preview.2.
- Installed whole-image CRC `0645D8BF` matches the signed successor's manifest.
- Identity remained `4631_AUTO_DFU`, ABI 3, capabilities `0x1E`.
- Application body remained 619,988 bytes with hash `1809003428588E08`.
- After reboot the application automatically returned to `QSPI store:2048K`.

## Compatible image: Nordic nRF Connect Bluetooth update PASS

After the direct board update, Nordic nRF Connect 4.24.3 installed the corrected
unified RAK4631 application on compatible preview.3 using the phone's real DFU
flow. The package contained 620,300 application bytes. The phone received
validation response `10-04-01`, sent Activate and Reset, and observed the device
reboot. The bootloader remained preview.3; the installed application reported body
620,244 bytes, hash `CE03698DC21A151D`, and `QSPI store:2048K`. This separately
checks Bluetooth against the final compatible identity/capability design; the
earlier standard 1.17.1.5-to-1.17.1.7 tests remain recorded above.

## Compatible successor gate found during hardware testing

The first preview.3 successor pull with the application using external NOR was
rejected by a remaining application CLI guard: it compared the bootloader's
internal `0A` capability against the current external application store. No
package was staged or activated. The CLI now applies that application-storage
check only to application packages; bootloader packages still pass their
separate exact-identity, signed-format, ABI, codec and boot-capability checks,
and the adaptive store selects internal staging before writing their payload.
The regression test executes the actual CLI gate for internal, external and
unsafe application stores, including rejection of unsupported application
updates.

## Compatible successor with external application storage: PASS

With the corrected application using `QSPI store:2048K`, the RAK4631 fetched
signed successor MID `251EF1DE` from the T114 over LoRa. All 40 bootloader
blocks were staged in internal flash, independently of application storage.
The ordinary `ota bootloader install 251EF1DE 6F58B09DBB64E4B9` command
reported trusted bootloader verification and rebooted the device.

- Installed version: `OTAFIX2.4.10-preview.4`.
- Whole-image CRC: `D3F6A50A`, matching the signed successor manifest.
- Identity remained `4631_DFU`, target `2D0DF000`, ABI 3, caps `0A`.
- Application body remained 620,244 bytes, hash `CE03698DC21A151D`.
- After reboot, application storage automatically returned to `QSPI store:2048K`.
- No staged bootloader package remained.

This verifies the final compatible contract through a second signed update,
including the corrected CLI guard and the internal/external storage transition.

## Hardware cleanup

The temporary lab signing key was removed from both RAK boards. Their final
trust-key lists are empty, and the local temporary signing seed and Bluetooth
PIN file were deleted. Both boards retain the corrected unified applications;
RAK3401 runs compatible preview.3 and RAK4631 runs compatible preview.4.

The folder server was stopped. Normal radio settings were restored on both RAK
boards and the T114. OTA reach was restored to 0 hops on RAK3401 and T114 and
3 hops on RAK4631; the T114 advertisement interval was restored to 1,440 minutes.

## Software verification

The full host bootloader suite and sanitizers pass, including adaptive internal,
external, hybrid, privileged bootloader, rejection, and startup-vector tests.
GitHub build run `36554377582` passed all 31 jobs, including all 29 board
profiles, host tests, sanitizers, and signed/dual-bank/recovery display builds.
MeshCore native OTA tests passed 169 cases; Python package validation passed
49 cases. Both unified RAK applications build, and the adaptive-store,
CLI guard and storage-policy host tests pass.

The Rust package suite passes, including deployed identity aliases and malformed
optional-capability rejection. Normal releases select 24 profiles, with one RAK
image per model; historical RAK profiles remain in the recovery archive.
The originally published adaptive recovery images retained historical
`*_AUTO_DFU` identities and omitted LoRa bootloader self-update. A subsequent
in-place repair adds that feature while keeping the same historical identity.
The hardware results above describe the original build and do not establish
physical qualification for the repaired recovery images.

MeshCore Open's full current suite passed 838 tests with two skips. The Bluetooth
reply and compatible RAK application-storage tests pass; changed-file analysis
reports no issues. Published source commits:

- Bootloader: `b561e4b` on `feature/ota-delta-apply`.
- MeshCore: `346cf2fd` plus CLI gate fix `5c4b6d63` on `keymindCascade`.
- motatool: `97431e56` on `codex/rak-lora-bootloader-recovery`.
- MeshCore Open: `5fee33f` on `android-5.1.1-compat`.
