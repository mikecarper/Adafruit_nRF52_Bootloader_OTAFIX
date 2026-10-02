# Published recovery 2.4.11 Bluetooth bootloader qualification

Date: 2026-10-02, America/Los_Angeles.

## Result: PASS

An attached LG LGL51AL running Android 5.1.1 and nRF Connect
4.24.3/code 114 installed the published, repaired RAK4631 `board` recovery
bootloader over Bluetooth. The same phone then installed MeshCore over
Bluetooth from that bootloader. This is a test of the published production
ZIP, separate from the earlier qualification-image application tests.

| Check | Result |
| --- | --- |
| Normal 2.4.10 to published recovery 2.4.11 over phone BLE | PASS |
| Reinstall published recovery 2.4.11 over phone BLE | PASS |
| Recovery advertises with USB host configuration blocked and VBUS present | PASS, `4631_DFU` at `C3:C6:A8:FC:AD:A7` |
| Phone reads installed bootloader firmware revision | PASS, `R_0x02040BFF` |
| Following MeshCore application installation using the same phone | PASS |
| Seven queried settings digests and saved radio tuple | Unchanged |
| Erase firmware | Not used |
| Final node restoration | Normal 2.4.10 and the original fixed test application restored |

This qualifies the tested RAK4631 profile, phone, packages, and USB scenario.
It is not an all-board, physical charge-only-cable, or battery-only test.
No LoRa payload transfer was performed in this test.

## Device and packages

- RAK4631 serial: `9AB3B64C641BA927`.
- Phone serial: `LGL51AL2814416e`.
- Starting bootloader: published normal OTAFIX 2.4.10.
- Starting and restored application: `v1.17.1.8-ble-dfu-test (Build: 01-Oct-2026)`.
- Saved radio: `869.6179809,62.5,8,5`.

The bootloader package was downloaded from the repaired existing release:

https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/R_0.11.0-OTAFIX2.4.11

Filename:
`R_wiscore_rak4631_board_bootloader-0.11.0-OTAFIX2.4.11_s140_6.1.1.zip`.
Its 192,834-byte ZIP matched the published GitHub asset digest:

`3ec67bba63dff7ed44dc1680d0f65b0b371ffd9505f5ed6540ec7de8e4999771`

The combined SoftDevice/bootloader payload is 191,976 bytes: 151,016
SoftDevice bytes and 40,960 bootloader bytes. The verified package's
bootloader manifest CRC is `AA30573D`; this value identifies the input
image and was not separately read back from target flash. Production source
is `R_v0.11.0-OTAFIX2.4.11` at
`de88c5fcae72bb00992ac9db7fd144fec150835e`.

The following application ZIP has SHA-256:

`9d5854435305666be54f494411a0a32c851a0f416a07566e8634e60bf36f2fa0`

Its 531,708-byte application payload has SHA-256:

`2673a456760c70489ba745b5c91dc6cbd3bb398c8d9640aa455dfbf61e405a06`

## Transfer and activation evidence

Local CLI `start ota` exposed the application at `C3:C6:A8:FC:AD:A6`.
nRF Connect selected the distribution ZIP and performed the application-to-
bootloader handoff and bootloader transfer. Its log recorded validation
success, `Op Code = 4, Status = 1`, followed by Activate and Reset.
The three bootloader runs recorded Activate and Reset at 13:20:51,
13:30:57, and 13:40:20 America/Los_Angeles.

After the first installation, read-only `INFO_UF2.TXT` verification showed
`R_0x02040BFF`, `WisBlock-RAK4631-Board`, and build date 2 October 2026.
The application was reinstalled by UF2 for the repeat setup. CLI checks
confirmed recovery 2.4.11 and unchanged settings and radio.

For the final repeat, host USB configuration was blocked before the
replacement bootloader's USB device appeared. It appeared unauthorized
with an empty `bConfigurationValue`; the host default policy was then
restored immediately. The board subsequently left USB and advertised
`4631_DFU` at `C3:C6:A8:FC:AD:A7`. A fresh scan on the phone found it, and
the phone read firmware revision `R_0x02040BFF` from characteristic `0x2A26`.
The code permits a 30-second USB enumeration window when VBUS is present;
this test did not measure the first advertising instant.

The same phone selected the application ZIP from that DFU connection.
Progress reached 96% in the captured UI; the log then recorded validation
success and Activate and Reset at 13:51:27 America/Los_Angeles.
Final CLI queries confirmed the fixed application, bootloader OTAFIX 2.4.11,
the saved radio, and all seven unchanged settings digests. A captured 100%
frame or exact Nordic transfer duration is not claimed.

## Reconnection and USB test limits

The nRF Connect device tab attempted to reconnect to the previous address
after activation and logged GATT 133. The successful validation and
Activate and Reset preceded that error. The old application tab used A6;
the newly installed DFU bootloader advertised at A7. A fresh DFU scan and
connection to A7 worked. After the application installation, CLI checks
confirmed that the application had restarted successfully.

The first two runs did not qualify the power-only case: host USB
authorization returned during re-enumeration, or a software blocker acted
after configuration could begin. A UF2 drive appearing with a configured
USB host is expected. The final repeat prevented initial host configuration
while USB power remained present. It did not physically replace the cable.

The bounded host default-authorization guard was active for about 23 seconds.
A separate USB hub, `1-1.3`, reset during that window and remained
unauthorized, which the guard's trailing audit detected. Its normal access
was restored; the host default returned to 1, and every remaining non-target
USB authorization was checked as 1. The guard audit failure is retained in
the evidence. It is not recorded as a passing guard audit. No firmware was
written to another board and no hub power command was issued by this test.

## Cleanup and speed observation

The RAK4631 was restored using the verified normal 2.4.10 DFU package and
the original fixed application UF2. Final queried identities, all seven
settings digests, and the saved radio exactly matched the initial baseline.
USB data, the USB default policy, and the affected hub's authorization
were restored. No erase firmware was used.

nRF Connect displayed approximately 1.5 kB/s. A separate earlier test on
this same phone using MeshCore Open transferred the same 531,708 application
bytes in 68,651 ms, approximately 7.7 kB/s, with negotiated MTU 247.
That establishes a faster working application-transfer path, not an automatic
speed-fallback qualification. Current Open enables packet receipt checks and
five retries; it does not explicitly switch to a slower transfer profile
after failure.

Evidence is retained under
`/tmp/meshcore-ble-dfu-qualification/ble-bootloader-211-nordic-20261002/`,
including `test-metadata.json`, phone UI XML/screenshots, node verification
JSON, the guard log, and `SHA256SUMS`.
