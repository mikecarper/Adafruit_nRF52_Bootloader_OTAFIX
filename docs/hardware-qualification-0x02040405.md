# OTAFIX 2.4.4 hardware qualification (`0x02040405`)

This is the reproducibility record for the 4 September 2026 lab candidate. It
is not a release artifact. The build came from the intentionally dirty
`92e5c17` qualification tree, used the explicit packed test version
`0x02040405`, and was compiled with Arm GNU Toolchain 14.2.Rel1 (GCC 14.2.1).
Production artifacts must still come from a clean exact release tag.

Candidate `0x02040404` is disqualified. Its compact Device Information Service
removed the historical manufacturer and firmware characteristics, moving the
model value from handle `0x001A` to `0x0018`. A bonded client with the legacy
GATT layout cached therefore received `Invalid Handle` when it read the model.
This candidate restores the historical manufacturer/model/firmware order at
value handles `0x0018`, `0x001A`, and `0x001C`, and stores all three values in
SoftDevice-owned memory.

## Compatibility scope

OTAFIX continues to use the nRF5 SDK Legacy DFU service, control/data packet
format, and standard nRF Util ZIP manifest. Nordic's current Android and iOS
DFU libraries both state that they remain backward compatible with Legacy DFU:

- [Android DFU library](https://github.com/NordicSemiconductor/Android-DFU-Library#requirements)
- [iOS DFU library](https://github.com/NordicSemiconductor/IOS-DFU-Library#legacy-dfu)

The host tests below qualify that wire protocol, ZIP format, service discovery,
the cached Device Information layout, model checking, MTU negotiation,
receipts, validation, activation, reconnect, and application return. They are
not a literal Android/iOS user-interface test. A release candidate should still
receive one phone smoke test with Nordic's nRF Device Firmware Update app.

## Image size

The nRF52840 executable FLASH region is 40,784 bytes. "FLASH used" below is
the linker's `TotalFlashUsed`, so it includes the load image for initialized
`.data` as well as code and read-only data. The fixed CF2 and BLMF/BLM2 tail is
outside these figures.

| Board | FLASH used | Free bytes | Free |
| --- | ---: | ---: | ---: |
| `heltec_t096` | 39,444 | 1,340 | 3.29% |
| `heltec_t114` | 39,860 | 924 | 2.27% |
| `wiscore_rak3401` | 38,720 | 2,064 | 5.06% |
| `xiao_nrf52840_ble` | 40,216 | 568 | 1.39% |
| `heltec_mesh_tower_v2_sdcard` | 40,716 | 68 | 0.17% |
| `heltec_mesh_pocket` | 38,592 | 2,192 | 5.37% |
| `t1000_e` | 38,568 | 2,216 | 5.43% |

MeshTower V2 with microSD is the tightest build. Its 68-byte margin is a hard
release constraint, not spare feature budget. Earlier figures that reported
244 bytes for this candidate omitted the 176-byte flash load image for
initialized `.data`; the linker map and overflow assertion include it.

## Candidate artifacts

Every write was gated against the complete SHA-256 digest shown here.

| Board | Combined SoftDevice/bootloader ZIP SHA-256 |
| --- | --- |
| `heltec_t096` | `ddbb099b5e642751a5b0017279c0d52a4cf50291fb905c02ad66794ffcc00f82` |
| `heltec_t114` | `d16bf00220ba8f709c6c55bdb9ce61f132075cc32c71dccd47bce7de3c287281` |
| `wiscore_rak3401` | `29298e4c432034c5599d2cf7c764b80aea4c9fa4863d6888675a52c0f6fbe574` |
| `xiao_nrf52840_ble` | `ae2127c7e7895e06fe9321d67c34f4b4074c309dabdaac99ad0c289e4f254791` |
| `heltec_mesh_tower_v2_sdcard` | `7f79dec828de86d39e953b2380d9f1ea031de7851d43c883f29255b13f0acb94` |
| `heltec_mesh_pocket` | `48a7376d59ba694e8daf5cd6fd7eaf4bd4e694e497ea827de55764c072f0880b` |
| `t1000_e` | `49d78c1cd94921c0d46bc0d0d20afcb327999278982250329f49342b432eb05e` |

## Connected-board results

The controller was the MercerWoodMesh Raspberry Pi with the T096, RAK3401,
XIAO nRF52840, MeshTower V2 microSD, Mesh Pocket, and T1000-E connected. All
six installed candidate `0x02040405`, passed exact USB serial plus VID/PID
gates, and returned to an application. The T114 passed both build systems but
was not physically present.

| Board | Candidate path | Result and final state |
| --- | --- | --- |
| MeshTower V2 microSD | Serial combined; BLE application restore | Pass; legacy cached DIS handles returned manufacturer, model, and firmware; exact application USB returned |
| Heltec T096 | BLE combined; serial application restore | Pass; exact application USB returned; a fixed Full Companion build then passed the real `uf2reset` command |
| RAK3401 | Serial combined; BLE application restore | Pass; exact application USB returned; no SWD or diagnostic wire was needed |
| Mesh Pocket | Serial combined; BLE application restore | Pass; exact application USB returned |
| T1000-E | 1200-baud serial entry and combined DFU; BLE application restore | Pass; exact application USB returned; a fixed Full Companion build then passed the real `uf2reset` command |
| XIAO nRF52840 | 1200-baud serial entry and combined DFU; BLE updater restore | Pass; the patched Bluetooth repeater-updater application and exact USB identity returned |

After combined recovery, the RAK3401, Mesh Pocket, T1000-E, and XIAO correctly
advertised their exact BLE-only recovery identity until an application was
installed. Before any application bytes were written, the host verified the
exact address, boot name, Legacy DFU service, and restored model string. The
RAK3401's extra diagnostic wires were not used at any point in this candidate
run. No hub or target power cycle was required. The Pi's `mctomqtt` service was
active after qualification and all six application USB identities were present.

The T1000-E's pre-run temporary Full Companion enumerated over USB but did not
produce a terminal response or live advertisement. Restoring that exact old
application artifact therefore proves application-byte acceptance and USB
return, but not continuity of its temporary MeshCore identity. The subsequently
installed command-fix build created a live default Companion identity and
passed USB text-terminal and advertisement checks. Its stale Pi bond was
replaced for that exact address; paired/bonded/trusted state, an encrypted
BLEDfu revision read, and the Nordic UART service then passed. This run makes
no claim that a combined recovery ZIP preserves application-owned settings;
the normal signed bootloader-only `.mota` path is the application-preserving
update path.

## Measured bootloader timings

Times are wall-clock measurements from the hardware logs. BLE `DATA` covers
target-confirmed payload bytes only. Protocol end-to-end includes package
verification, scan, connect, START, INIT, DATA, VALIDATE, ACTIVATE, and the
target-initiated disconnect. Stable USB includes the subsequent identity gate.

| Operation | Payload | DATA or serial time | Rate | Protocol end-to-end | Stable USB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tower combined serial DFU | 191,976 B | 24.591 s | - | - | - |
| Tower application BLE restore | 487,344 B | 231.319 s | 2,107 B/s | 254.946 s | 274.506 s |
| T096 combined BLE DFU | 191,976 B | 57.781 s | 3,322 B/s | 80.671 s | - |
| T096 application serial restore | 487,344 B | 37.547 s | - | - | 38.106 s |
| RAK3401 combined serial DFU | 191,976 B | 24.340 s | - | - | - |
| RAK3401 application BLE restore | 473,312 B | 225.176 s | 2,102 B/s | 258.718 s | 261.341 s |
| Mesh Pocket combined serial DFU | 191,976 B | 24.004 s | - | - | - |
| Mesh Pocket application BLE restore | 458,476 B | 291.134 s | 1,575 B/s | 326.933 s | 329.449 s |
| T1000-E combined serial DFU | 191,976 B | 24.807 s | - | - | - |
| T1000-E application BLE restore | 404,468 B | 193.928 s | 2,086 B/s | 217.463 s | 221.821 s |
| XIAO combined serial DFU | 191,976 B | 24.523 s | - | - | - |
| XIAO updater BLE restore | 179,720 B | 85.459 s | 2,103 B/s | 108.851 s | 113.817 s |

The Pocket used conservative 20-byte ATT writes because BlueZ still reported
that cached characteristic limit after MTU 247 negotiation. Every other BLE
row used 244-byte writes. The safe fallback is slower but completed normally.

## MeshCore `uf2reset` command qualification

The MeshCore fix delegates the retained-register transaction to the common
`NRF52Board` implementation. Repeater, Room Server, and Sensor already used the
shared CLI; Companion and Terminal Chat had separate dispatchers and now call
the same board method. The command accepts no arguments and is local-only.

On the T096, a 628,536-byte intermediate application installed over BLE in
188.131 s of DATA at 3,341 B/s and 221.122 s protocol end-to-end. The exact
terminal command disconnected the application in 1.031 s and produced stable
bootloader USB in 2.026 s. The final Full Companion application then installed
over serial in 38.900 s and returned as stable application USB in 41.672 s.

On the T1000-E, the fixed Full Companion application installed over serial in
32.196 s and returned as stable application USB in 35.888 s. A complete script
covering terminal entry, version, help, the exact `uf2reset` command, and stable
bootloader USB took 8.898 s. Reinstalling that same fixed application took
32.204 s and returned stable USB in 36.313 s. Both devices were finally left in
normal Binary Companion mode, and help continued to list `uf2reset`.

## Timeout and clock behavior

The DFU bank inactivity interval is 360,000 ms (six minutes). It starts when
DFU initializes and restarts on valid peer packets. This is deliberately close
to the requested five-minute recovery window while retaining one minute of
margin for a slow or reconnecting sender. An abandoned session with a valid
application therefore exits without diagnostic wires.

USB entry has separate timing: explicit serial/UF2 application requests get a
30,000 ms enumeration window, MakeCode-style single-tap entry gets 3,000 ms,
physical double-reset recovery is unbounded, and a no-application device probes
an active USB host for up to 30,000 ms before falling back to BLE.

Every board selects the calibrated internal LFRC both before and during
SoftDevice operation. A bad or mismatched external low-frequency crystal
configuration therefore cannot permanently remove the recovery timers or BLE
login path. A physical high-frequency oscillator failure remains a hardware
fault because the nRF52 radio requires it.

## Automated verification

- Both `heltec_t096` (ST7735S) and `heltec_t114` (ST7789) CMake builds pass.
- All seven tabled targets build with GCC 14.2.1 and packed test version
  `0x02040405`.
- `make -C test check` passes, including the Legacy DFU bounds/signature tests,
  timeout and LFCLK contracts, UF2 state/handoff tests, bootloader-image policy,
  and the cached BLE DIS layout regression.
- MeshCore's native tests, source-level all-dispatcher contract, representative
  Companion/Terminal/Repeater builds, and physical T096/T1000-E command tests
  cover the application-side CLI regression.
