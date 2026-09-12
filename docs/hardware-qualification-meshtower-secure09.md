# MeshTower SD Secure09 hardware qualification

Date: 2026-09-12. Source: `a33076da538f8d15702385051cb8fbef085f660b`.
Board: `heltec_mesh_tower_v2_sdcard`, connected to the MercerWoodMesh Pi.
Device identifiers, private keys and controller logs are omitted.

**Completed:** available physical transport/recovery checks and the host suites
passed. No new bootloader failure was found in the exercised paths. The known
bootloader-UF2 completion warning and the physical power-cut limit remain below.

This is the **Secure-only BLE qualification profile**, not a production release.
It retains CDC, UF2 and SD-backed mOTA; it does not offer Legacy BLE DFU.
The unsigned Secure application protocol checks board/SoftDevice compatibility
and SHA-256, but does not implement a signing trust policy. LoRa packages in
this campaign are signed and checked against the board's existing trusted key.

## Image under test

- Test version: `0x02040709`; S140 6.1.1 / FWID `00B6`.
- Bootloader BIN: 40,960 bytes, SHA-256
  `e9277fd84384bca98eb31519e187ae62d5cadba2a1f27d55d804096ec621ae32`.
- Whole-image BLMF CRC: `BD394C1F`.
- Executable use, including initialized data: 40,745 / 40,784 bytes;
  **39 bytes of executable headroom**.
- Board/target: `239A0071` / `1150F50E`; ABI 3, codecs `0x0005`, caps `0x09`.
- The existing Windows/Linux qualification compared all four artifact types
  across 27 boards: 108/108 hashes matched. This campaign uses those exact bytes.

The original repeater application is
`1.17.1.5-halo-keymind-cascade-marathon-hwtest-e26d48e4`, 487,344 bytes.
Its complete-image SHA-256 is
`61050508747cef3df4c77ed35f12de15fbf1cf34050f426b05b1e75b291257c5`;
the live body hash is `E9282D470AAC348B`.

## Completed physical checks

| Check | Result |
| --- | --- |
| Exact USB identity, current app, radio/settings, trusted key and idle staging preflight | Pass |
| Install the board-bound bootloader UF2; verify installed whole-image CRC and unchanged app/settings | Pass, with the completion warning below |
| Application UF2 through the real mounted USB drive, flush, unmount, app return and kernel storage-I/O gate | Pass |
| CDC serial-only DFU after the 1,200-baud touch; complete 487,344-byte application, reboot and live body-hash verification | Pass |
| Restore exact candidate09 following the bootloader mOTA fixture; original app/settings and `BD394C1F` confirmed | Pass, same bootloader-UF2 completion warning |
| Three command-triggered warm reboots, each followed by application/settings/bootloader verification | Pass |
| Individual USB hub port off for five seconds, then on; application/settings intact | USB reconnect passed; **not a CPU power cycle** |
| Application's buttonless BLE handoff to Secure service `FE59`; Legacy service absent | Pass |
| Wrong-board and wrong-SoftDevice command metadata | Rejected at COMMAND EXECUTE |
| Invalid DATA object size and premature EXECUTE | Rejected |
| Corrupt uncommitted object, then CREATE rollback | Offset/CRC reset correctly |
| Mid-object disconnect at byte 820 | Exact offset and CRC retained |
| Packet overrun at offset 4,090 | Rejected without advancing offset/CRC |
| Full unexecuted 4,096-byte object across reconnect | EXECUTE succeeds |
| Duplicate EXECUTE, including reconnect after a committed object | Accepted without corrupting progress |
| Complete 487,344-byte BLE upload using 20-byte writes; disconnect at byte 228,123 | Resumes at exactly 228,123 |
| All bytes received, final DATA EXECUTE deliberately omitted | Reconnect sends zero DATA bytes; final EXECUTE acknowledged |
| Boot following that BLE update | Original application/body hash, name, radio and key preserved; BL CRC `BD394C1F` |
| Correct metadata but one corrupted payload byte in a 512-byte valid-vector test image | Final DATA EXECUTE rejected; failure latched and further CREATE refused |
| Reconnect after 75 seconds idle/disconnected following that rejection | Failed session retained; no unexpected watchdog reset |
| Leave rejected session idle through the production DFU timeout | Fresh Secure session at the open-entry address, empty COMMAND/DATA offsets and CRCs; bad application did not boot |
| Restore all 487,344 bytes with negotiated ATT MTU 247 / 244-byte DATA writes, disconnecting at 8,192 bytes | Exact offset/CRC resume; original application subsequently verified |
| Withhold the successful final EXECUTE receipt at the host harness during that physical BLE upload | Sender reports **UNCONFIRMED** after 30 seconds; independent application hash/BL CRC checks pass |

The complete slow BLE run remained stable for more than eight minutes, including
reconnections and repeated flash writes. This exercises the real watchdog feed
paths; it is not a voltage-level measurement of the external watchdog signal.

The isolated USB-port test removed the target from USB, but its application
uptime advanced from 29 to 47 seconds. Another supply kept the CPU running.
No cold-power or physical mid-flash power-cut result is claimed for this board.

The missed-receipt test filtered the real notification at the host, not over
the air or through SWD. The board activated and disconnected after sending it,
so only one final EXECUTE was transmitted. Repeated final EXECUTE while a link
stays open is covered by the host suite, not claimed as a physical RF-loss test.
These BLE runs used the bench sender; no new phone-app test was performed.

The first buttonless discovery attempt did not immediately observe the new
advertisement. Subsequent scans did. A retained buttonless peer uses the app's
address; this must not be confused with the open-entry Secure address offset.
The Pi controller was power-toggled during bench diagnosis, with no other BLE
connections active. The eventual service and protocol checks passed.

A later buttonless run reproduced stale Legacy UUIDs in the Pi's scan result.
A read-only connection discovered the actual Secure GATT service (`FE59`,
with its Secure control/data characteristics), after which scan results also
showed Secure. No repeat buttonless write, controller reset or firmware change
was needed on that run. The advertisement-only prefilter was the bench issue;
the installed bootloader had successfully entered Secure DFU.

### Bootloader UF2 completion warning

The board detached after accepting the bootloader image, before Linux finished
its final FAT metadata writes. `sync` reported EIO and the kernel reported
offline/FAT errors. The installer did **not** blindly retry: the application
returned and independently reported the expected CRC `BD394C1F`, with unchanged
application and settings. This matches the previously documented MeshTower
bootloader-UF2 completion behavior. It is a successful installation, not a
clean host-filesystem completion result. The separate **application** UF2 copy
passed its storage-I/O-error gate.

## LoRa / SD campaign

All three signed LoRa/SD installation paths completed on the physical board.

- Full application package: 489,458 bytes, MID `78DBB512`, 476 data blocks.
- **Full application LoRa/SD apply: PASS.** The download reached 476/476,
  then `ota install` rebooted into body hash `C2CFC98C42CBEFDB`, with SD
  result `B8`, no active download and unchanged bootloader CRC `BD394C1F`.
  The whole download took 3,403 seconds, including the controlled interruptions.
- **In-place delta LoRa/SD return: PASS.** MID `28BEF4A3`, 15,314 bytes,
  15/15 blocks in 114 seconds. The trusted-signer delta applied from SD and
  restored body hash `E9282D470AAC348B`, result `B8`, with no download and
  unchanged bootloader CRC `BD394C1F`.
- **Bootloader LoRa/SD self-update: PASS.** MID `FC45BE4D`, 41,330 bytes,
  40/40 blocks in 284 seconds. The explicit MID/hash-bound install completed
  with result `C8` and installed CRC `CE2F2EF0`; the original application
  body hash remained unchanged and staging was cleared.
- During the full-image run, the sender was stopped at 5/476 blocks for 20 seconds,
  then reattached. The target retained 5/476 and progressed to 7/476.
- Further controlled sender/radio changes retained the same SD download.
- Both RAK3401 and the second available Heltec sender could serve the package.
  SF5 and SF7 at 500 kHz were tried; throughput was roughly 130–170 B/s in
  this setup (144 B/s overall for the full download, including interruptions).
  At SF5 the target reported RXPS level 8 and preamble 128.

For the bootloader mOTA test, a second image was built from the same source with
test version `0x0204070A`, because the running MeshCore application's version
gate refuses an equal-version install. Its CRC is `CE2F2EF0`, BIN SHA-256
`14054a204d45247f104e2624b383cc312c29efd33b4071d4dd1704e6d689e44b`.
This is a qualification fixture, not a release-version change. Exact candidate09
was restored afterward and used for the remaining physical tests.

## Host-only checks

The complete native suite was rebuilt and rerun with ASan/UBSan. The shared
CRC/SHA/watchdog helpers and Secure engine/BLE-adapter suites were separately
instrumented as well. All passed.

The exact hardware fixtures also passed the production SD apply code under
ASan/UBSan:

- Original application → signed full package → exact lower-version image.
- Lower-version image → signed in-place delta → exact original image.
- The signed `0x0204070A` bootloader package, including its `+365` SD payload
  geometry and the bootloader test's safety/failure-mode matrix.

Fine-grained scratch-page power cuts, readback faults, removable-media swaps,
flash-controller failures and BLE notification-queue fault injection are
**simulated**, not hardware claims. The MeshTower is not connected to the
RAK3401's SWD debugging wires. No full-flash/UICR SWD readback is claimed.

## Final state

Final verification passed:

- Original application version/body hash, name, saved radio and trusted key retained.
- Candidate09 installed, whole-image CRC `BD394C1F`; no bootloader staging.
- No active download; target serving off. Source folder detached, serving zero,
  and source radio restored to its original settings.
- ModemManager, the MQTT bridge and both unrelated soak services active.
- Target reported zero core errors and an empty queue.

No firmware source changes were required. Private evidence (69 JSON/log files)
was archived separately from Git, SHA-256
`ebb2d3309a33135089ef62b69d7ede4a0f756e6fe9fd9738ed35552a6c27ce93`.
