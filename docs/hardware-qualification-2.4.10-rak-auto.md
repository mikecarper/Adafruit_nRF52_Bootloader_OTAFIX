# RAK adaptive bootloader update qualification

Development qualification for the next release, performed on 2026-09-29.
The images below use explicit test versions; they are not release artifacts.

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

## Software verification

The full host bootloader suite and sanitizers pass, including adaptive internal,
external, hybrid, privileged bootloader, rejection, and startup-vector tests.
Both display-controller variants build. MeshCore native OTA tests passed 169
cases; Python package validation passed 49 cases. Both unified RAK applications
build, and the adaptive-store and storage-policy host tests pass.

The Rust package suite passes, including deployed identity aliases and malformed
optional-capability rejection. Normal releases select 24 profiles, with one RAK
image per model; historical RAK profiles remain in the recovery archive.
Adaptive recovery images retain historical `*_AUTO_DFU` identities and omit
LoRa bootloader self-update to fit the temporary allow-all recovery policy.

MeshCore Open's full current suite passed 838 tests with two skips. The Bluetooth
reply and compatible RAK application-storage tests pass; changed-file analysis
reports no issues. Published source commits:

- MeshCore: `346cf2fd` on `keymindCascade`.
- motatool: `97431e56` on `codex/rak-lora-bootloader-recovery`.
- MeshCore Open: `5fee33f` on `android-5.1.1-compat`.
