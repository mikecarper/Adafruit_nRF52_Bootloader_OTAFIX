# Full normal OTAFIX 2.4.11 qualification

Date: 2026-10-02, America/Los_Angeles. Result: PASS.

## Production artifacts

Normal source tag: `v0.11.0-OTAFIX2.4.11`.
Commit: `c63b00d88ea9322c9d1c73a8dd505550f479c5fe`.
Packed version: `0x02040BFF`.

https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/actions/runs/37066565552

All 33 production build/validation jobs passed. The build-only dispatch
intentionally skipped its publication job; the verified artifacts are
published separately. Gates include Make/CMake on all 29 production profiles,
T096 and T114 signed/dual-bank/recovery variants, host/sanitizer suites,
official signed mOTA packaging, and the recovery archive.

Independent downloaded-artifact inspection passed for 24 normal
HEX/Legacy ZIP/UF2 sets, 24 signatures, and 29 recovery sets. Identities,
versions, whole-image CRCs, payload hashes, SoftDevices, UF2/UICR framing,
archive inventories and checksums match. Every normal image retains ABI 3,
the delta codec and bootloader self-update. Both RAK adaptive images retain
standard `*_DFU` identities and internal bootloader storage flags `0A`.

## Actual normal production RAK4631 package over LoRa

Target: USB serial `9AB3B64C641BA927`, starting on official normal 2.4.10
with `4631_DFU`, CRC `9D4C29ED`. Test application:
`v1.17.1.7-halo-keymind-cascade-dev-2724bab5 (Build: 25-Sep-2026)`.
Application body: 618,604 bytes, base hash prefix `66A839756DF3D845`.

| Package field | Value |
| --- | --- |
| Filename | `update-wiscore_rak4631_auto_bootloader-v0.11.0-OTAFIX2.4.11.mota` |
| Size | 41,330 bytes |
| SHA-256 | `8d638b34213eecbd0ea2b55a0a3e5d63f3a16fa38fac429c2bf16ffa05001937` |
| MID | `C415BED1` |
| Bootloader SHA-256 | `be184563b863b0c9f0f8915e425ce8bcf9bdfdca3ab575c74c3d482df31fcb62` |
| Manifest CRC32 | `CD0863E0` |
| Identity | `NRF_BL_239A0029_4631_DFU` |

The Heltec T096 Companion, serial `651F8E496197F882`, running
`v1.17.1-t096-full-head-fdd67ce1`, served the actual production package.
Source and target used temporary `910.525,500,5,5` settings. All 40 blocks
arrived; the target confirmed the signed MID/hash and installed using the
ordinary `ota bootloader install` command. No recovery, identity migration,
external bootloader staging or application erase was used for this update.

After reboot the target reported normal `v0.11.0-OTAFIX2.4.11`, `4631_DFU`,
CRC `CD0863E0`, ABI 3/caps `0A`, `blup:C8`, and no pending download.
The application body/hash prefix, application version, radio reply and all
seven queried settings digests matched the pre-update baseline.

An earlier BW62.5/SF7 attempt using the RAK3401 Companion source stalled at
1/40 blocks and was stopped before approval or installation. Its receive
session was cancelled and its normal radio restored. That incomplete attempt
is retained as a transport limitation, not a passing slow-link test. The
successful fast attempt used the T096 source.

## Cleanup and scope

The temporarily enrolled official signer was removed and the initially empty
trusted-key list verified. Both source radios returned to their original
`910.5250244,62.5,7,5` settings; folder processes were stopped. The target
was restored to normal 2.4.10 and its original `v1.17.1.8-ble-dfu-test`
application. Final versions, saved radio `869.6179809,62.5,8,5`, and all seven
settings digests exactly matched the initial baseline. Target, host default
and hub USB authorization were 1. No erase firmware or backup was used.

This physically qualifies the normal production RAK4631 package over LoRa.
The RAK3401 package passed signature/image/capability verification but was
not physically installed in this run. Its earlier 2.4.10 LoRa result remains
separate. Earlier Android BLE results identify their exact recovery and
qualification images; they are not relabelled as normal 2.4.11 BLE tests:

https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/feature/ota-delta-apply/docs/hardware-qualification-2.4.11-ble-bootloader.md

Hardware-pending ports remain excluded from normal downloads. No all-board,
physical charge-only-cable or battery-only qualification is claimed.
Evidence: `/tmp/otafix-2.4.11-full-release-20261002/` and the Pi's
`/home/mikec/hwtest/rak4631-downgrade-20260930/normal-211-*` files.

