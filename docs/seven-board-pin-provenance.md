# Seven-board pin provenance follow-up

Checked 2026-09-29 against MeshCore upstream **dev** at
`33468c4f80aaeae64e8bef5692e66d8978c82434` and Meshtastic **develop** at
`778184c7a1b91993c810558325570cdbec4cc457`, plus manufacturer documentation,
factory bootloader downloads and the discussions behind the pin changes.

`git blame --line-porcelain` identifies the originating commits. Use `-w` when
formatting obscures a change, and inspect the commit diff and associated PR.
For example, plain blame attributes Mesh Solar's LED line to a formatting
commit; `git blame -w` finds the actual hardware change in PR 9337.
Review bots and generated PR summaries are not hardware evidence.

## Decisions

| Board | What the history establishes | OTAFIX action |
| --- | --- | --- |
| Nano G2 Ultra | Designer-authored Meshtastic pins match MeshCore and the published schematic. Factory HEX has USB identity **4251:8695**, unlike the generic application board JSON. | Add `nano_g2_ultra` as a source port with external flash, pending hardware qualification. |
| Meshtiny | The manufacturer's Meshtastic port changes three flash pins to avoid encoder/buzzer conflicts. Manufacturer product and downloadable bootloader confirm external flash and MT001 identity. | Add `meshtiny` as a source port with external flash, pending hardware qualification. Do not alias GAT562. |
| MeshTracker X1 | Both firmware projects agree on the active-high button and LEDs. MeshCore adds powered QSPI in a separate PR; Seeed's factory ZIP confirms **2886:0057**. | Need a dedicated profile. Keep unpublished until the flash rail and complete boot-time power/reset behavior are corroborated for the production revision. |
| ThinkNode M8 | Initial vendor V0.1 work and a newer V0.3-tested port establish the separate controls. M1's bootloader button would use M8's display-enable pin. | Add `thinknode_m8` as a compile-only source port, pending factory USB identity, power/entry verification and physical qualification. |
| ThinkNode M4 | The port author explicitly says M4 has a bespoke MCU/radio PCB, rather than M3's module. Manufacturer says it has 2 MB external flash, but neither current firmware variant provides that flash map. | Need a dedicated profile. Do not infer M3 flash wiring; obtain the actual flash routing and factory bootloader identity. |
| Wio WM1110 | MeshCore's original PR identifies the **Wio-WM1110 Dev Kit**, which matches Meshtastic's SDK carrier, not Tracker 1110 or XIAO. | Carrier identity is resolved. No existing OTAFIX alias fits. Verify the Dev Kit installation path and bootloader identity before adding a port. |
| Heltec Mesh Solar | The same Heltec contributor introduced the original definitions and later reported a compatible watchdog hardware revision. Manufacturer pin map contradicts its Arduino BSP LED/button definitions. | Keep unpublished. Do not choose between the conflicting LED/flash definitions or reuse a T114/T1 profile. |

None of these seven gained a released OTAFIX download from this research.
The three new ports have `OTAFIX_BOARD_QUALIFICATION_PENDING ON`, so release
manifests and normal/recovery archives continue to exclude them. Adding a port
does not change the storage backend of an already released MeshCore application.

## Nano G2 Ultra

- MeshCore blame: `7e14fb3f6590`, Rob Loranger,
  [PR 298](https://github.com/meshcore-dev/MeshCore/pull/298).
- Meshtastic blame: `b9c9f0f8654f`, designer Neil Hao,
  [PR 2660](https://github.com/meshtastic/firmware/pull/2660).
- Manufacturer: [Nano G2 Ultra documentation](https://wiki.bqvoy.com/en/meshtastic/nano-g2-ultra),
  [schematic](https://wiki.bqvoy.com/meshtastic/nano_g2_ultra/nanog2ultra_19_jun_2023.pdf),
  [factory bootloader HEX archive](https://wiki.bqvoy.com/meshtastic/nano_g2_ultra/nano_g2_nrf52840_bootloader-0.6.4_s140_6.1.1.hex.zip).

The schematic's MCU/flash/user-button sheet, PDF page 4, confirms QSPI
SCK/CS/IO0/IO1/IO2/IO3 = **8/39/6/26/36/34** in physical Nordic numbering.
The SW1 user-button net is P1.06 (38), pulled to 3.3 V through 10k and shorted
to ground when pressed. Hardware reset is a separate switch. Both projects
have no ordinary bootloader LED. The new port therefore has no PWM LEDs.

Factory HEX CF2 at `0xFD800` and the actual USB device descriptor at `0xFC32D`
both contain **4251:8695**. Factory model is `B and Q nRF52840`, board ID
`nRF52840-BQ-rev1`, S140 6.1.1. The source port preserves that identity and
uses it in CDC-only mode too, without inventing an additional PID.

[Meshtastic bootloader PR 22](https://github.com/meshtastic/Adafruit_nRF52_Bootloader_OTAFIX/pull/22)
is an unmerged draft that explicitly admits an unconfirmed Adafruit PID and
untested single-button behavior. That proposal is not the authority for our
USB identity. The single-button entry behavior still needs physical testing.

## Meshtiny

- MeshCore blame: `5a20e8674f59`, oltaco,
  [PR 1492](https://github.com/meshcore-dev/MeshCore/pull/1492): working
  controls and hibernation with wake from the side button.
- Meshtastic blame: `f413c49555fd`, manufacturer Wilson,
  [PR 7676](https://github.com/meshtastic/firmware/pull/7676).
  Side-button cancellation behavior changes in `4a669032dcc5`,
  [PR 7789](https://github.com/meshtastic/firmware/pull/7789), with an explicit
  Meshtiny test attestation. That change does not move the physical button.
- Manufacturer: [product specification](https://shop.mtoolstec.com/product/meshtiny),
  [bootloader installation](https://shop.mtoolstec.com/bootloader-update-on-meshtiny.html),
  [vendor bootloader source](https://github.com/whywilson/Adafruit_nRF52_Bootloader_OTAFIX/blob/07ad9ef2fb8b8870f2c5f116d72b4a29345e00fc/src/boards/mt001_board/board.h),
  [downloadable bootloader UF2](https://dl.mtoolstec.com/meshtiny/bootloader.uf2).

The product explicitly specifies **IS25LP080D onboard QSPI**. The
manufacturer-authored Meshtastic variant specifies **3/22/27/29/21/2** and
explains that CS moved from 26, IO0 from 30 and IO2 from 28 to avoid the
encoder, buzzer and encoder press. Those conflicts make a GAT flash mapping
unsuitable, even though the LEDs look similar.

Both firmware projects agree on LEDs P1.03/04, active high, side button P0.09,
top-switch down P0.04 and press P0.28. Manufacturer installation instructions
use the side button for USB and the top switch held down for BLE; the new port
uses those real controls. The vendor bootloader header's P0.08 button is
inconsistent with both application ports, so it is not copied.

The downloaded UF2's CF2 confirms **239A:0029** and its strings confirm
`Meshtiny-MT001-Board`. Its version string is 0.4.5. The source port retains
that legacy manufacturer identity and 3.3 V setting, with unique
`MT001_DFU`. MeshCore currently omits the external-flash macros: that omission
does not mean the hardware lacks flash, and adding the bootloader alone does
not enable external staging in the application.

## MeshTracker X1

- MeshCore `3d6a891586b9`,
  [PR 3112](https://github.com/meshcore-dev/MeshCore/pull/3112), reports a real
  BLE companion flash, USB enumeration, app connection and successful radio
  initialization. The author says the pin map was checked against Seeed and
  Meshtastic.
- External flash comes later in `02ec123eb820`,
  [PR 3139](https://github.com/meshcore-dev/MeshCore/pull/3139), with a CustomLFS
  update for the new flash chip. It is not part of the original radio port.
- Meshtastic `7509c1a6dd0d`,
  [PR 10834](https://github.com/meshtastic/firmware/pull/10834).
- Manufacturer: [MeshCore installation and recovery guide](https://wiki.seeedstudio.com/sensecap_meshtracker_x1_meshcore/)
  and its [factory ZIP](https://files.seeedstudio.com/wiki/SenseCAP/Meshcore/MeshTrackerX1/Bootloader.zip).

Both firmware projects specify RGB LEDs **3/24/28**, active high, and user
button **6**, active high with pulldown. MeshCore QSPI is
**19/20/21/22/23/32**, enabled by **15 high**. Sensor, GNSS, RTC and haptic
power controls also exist and should not be replaced by L1 hooks.

The ZIP manifest contains S140 plus a 39000-byte bootloader; CF2 confirms
**2886:0057**, model `Seeed MeshTracker-X1`, board ID
`nRF52840-MeshTracker-X1-v1`. The manufacturer explains that the device has a
button-driven USB reset/DFU procedure. A generic double-reset instruction
is therefore insufficient. No independent manufacturer flash-rail schematic
was located in the checked documentation.

## ThinkNode M8

- MeshCore `3e828277066f`,
  [PR 3180](https://github.com/meshcore-dev/MeshCore/pull/3180).
- Meshtastic `597f6767b5e0`,
  [PR 11226](https://github.com/meshtastic/firmware/pull/11226), explicitly
  reports **V0.3 hardware** verification. Its first commit `65c1a53d7f83`
  says the pins were resolved from `ThinkNode_M8_V0.3.sch` and compared with
  [the original V0.1 submission, PR 9181](https://github.com/meshtastic/firmware/pull/9181).
  The original submitter also reports testing on M8. This is more specific
  evidence than a shared PlatformIO board name.

QSPI **46/47/44/45/7/5** matches M1, but bootloader-critical pins do not:
M1's button **42** is M8 display enable; M1's LED **14** is M8 GNSS PPS.
M8 has encoder press **6** with pulldown, separate button **12** with pullup,
and power enable **13**. The same flash tuple is not sufficient for an alias.
The checked public manufacturer repositories/wiki did not provide an exact
M8 factory bootloader file or a directly downloadable revision schematic.
Generic application USB HWIDs are not proof of factory bootloader identity.

The retained `thinknode_m8` draft uses the V0.3 QSPI tuple, no PWM LED, and the
separate active-low P0.12 button for the existing single-button DFU convention.
The active-high encoder press on P0.06 is not treated as a second active-low
button. DFU holds display power P1.10, frontlight P1.11, GPS power P0.16, ADC
power P1.08 and buzzer P1.01 low. The output latch is cleared before enabling
each output. P0.13 remains untouched because MeshCore calls it power enable
while the newer V0.3 Meshtastic port calls it I2C power. GPS PPS P0.14 and the
VBUS divider P1.03 remain untouched too. Common USBREGSTATUS handling remains
in use; the V0.3 source explicitly cautions against digital VBUS-divider reads.

Make and CMake require test-build mode and an explicit test version. The
header additionally requires the compile-only definition from that build
configuration. **0000:0000 is an invalid compiler fixture, not an allocated or
verified USB identity**; zero CF2/BLMF identity cannot match a qualified target
and is also rejected by manual recovery validation. The UF2 product and board
strings are explicitly marked as draft.
Generated images must not be flashed or published. Before hardware testing,
record the exact factory USB descriptor and INFO_UF2 board string, replace the
fixtures with that verified identity, and resolve safe rail/entry behavior.
Keep the qualification marker until the physical checks pass. Production CI
excludes pending ports; qualification CI can still check the draft compiles.

## ThinkNode M4

- MeshCore `0a15c487d8b8`,
  [PR 3463](https://github.com/meshcore-dev/MeshCore/pull/3463).
- Meshtastic `233e6acc8510`,
  [PR 8754](https://github.com/meshtastic/firmware/pull/8754).
  In the [RF-switch discussion](https://github.com/meshtastic/firmware/pull/8754#issuecomment-3584910071),
  the author distinguishes M3's module from M4's bespoke PCB and acknowledges
  a copied RF-switch table error. It was radio-switch evidence, not a
  bootloader identity or external-flash confirmation.
- Manufacturer: [M4 specification](https://static-cdn.elecrow.com/wiki/ThinkNode-M4_Power_Bank_LoRa_Device_with_Meshtastic_Function_Powered_By_nRF52840.html)
  specifies **2 MB external flash**. Its separate
  [LoRa Tracker installation page](https://elecrow.com/wiki/ThinkNode_M4_Power_Bank-LoRa_Device_with_LoRa_Tracker_Function_Powered_By_nRF52840.html)
  links a factory **application** UF2, not an independently identified
  bootloader package; those are different product firmware editions.

Firmware ports agree on LEDs **13/41**, active high, button **4**, radio power
**11**, I2C power **32 active low**, and separate GNSS controls. Neither
checked variant supplies the external-flash pins. Assuming M3's wiring or
declaring M4 internal-only from that absence would conflict with the
manufacturer specification. The actual routing and safe reset/rail behavior
are the remaining implementation gates.

## Wio WM1110

- MeshCore `ec05d40b3c94`,
  [PR 982](https://github.com/meshcore-dev/MeshCore/pull/982), links the exact
  [Wio-WM1110 Dev Kit product](https://www.seeedstudio.com/Wio-WM1110-Dev-Kit-p-5677.html)
  and says an external programmer was used.
- Meshtastic `b43c7c0f2369`,
  [PR 3013](https://github.com/meshtastic/firmware/pull/3013), introduces
  separate `wio-sdk-wm1110` and `wio-tracker-wm1110` targets.
- Manufacturer: [Dev Kit documentation and hardware diagram](https://wiki.seeedstudio.com/Wio-WM1110_Dev_Kit/Introduction/).

MeshCore LEDs **13/14 active high**, sensor rail **7**, I2C **27/26** and
LR1110 **40/42/43/44/45/46/47** match the SDK carrier. Tracker 1110 instead
uses LED **6 active low**, sensor rail **33** and user button **34**.
The SDK has user/config controls **23/25** in the community
[SDK bootloader header](https://github.com/caveman99/wm1110_bootloader/blob/f0b79d5eab2bf3ce0afe998187cc36b1f5eb8bad/src/boards/wio_sdk_1110/board.h),
while MeshCore disables its user-button macro. The community header is useful
corroboration, not a manufacturer-issued bootloader qualification.

The manufacturer's Dev Kit diagram places **CH340C USB-to-UART** on the USB
connector. Thus even a correctly compiled nRF native-USB bootloader would
not prove that UF2 drag-and-drop is available through that connector. The
Dev Kit installation path, NFC configuration and correct bootloader identity
need verification; a Tracker factory ZIP must not be offered for this target.

## Heltec Mesh Solar

- MeshCore `612dde73e9aa`, Heltec contributor Quency-D,
  [PR 575](https://github.com/meshcore-dev/MeshCore/pull/575), supplies LED
  **12 active low**, user button **42**, NeoPixel data **47** and no physical
  QSPI definitions. The review discussion concerns file placement, not a
  resolution of LED or flash wiring.
- Manufacturer Arduino BSP `e6f9d7fbfd31`, same contributor,
  [PR 8](https://github.com/HelTecAutomation/Heltec_nRF52/pull/8), instead
  gives LED **35 active high**, buttons **5/11** and QSPI
  **46/47/44/45/32/33**.
- Meshtastic initially comes from `0903ed8232d6`,
  [PR 7764](https://github.com/meshtastic/firmware/pull/7764). Later
  `b2f2f6b305e9`, Quency-D,
  [PR 9337](https://github.com/meshtastic/firmware/pull/9337), changes LED
  **4 to 47**, disables NeoPixel support and assigns watchdog **9/10**.
  It describes a new hardware watchdog revision compatible with the earlier
  board and includes a hardware test attestation. A linked
  [reboot report](https://github.com/meshtastic/firmware/issues/9457) was
  resolved by this watchdog change. MeshCore later adds watchdog handling
  separately in `c89a0e992`.
- Manufacturer [carrier pin map](https://resource.heltec.cn/download/MeshSolar/Pin_map/MeshSolar_pinmap.jpg)
  shows user button **42**, reset **18**, **battery shutdown 35**, display
  GPIO **12**, BMS I2C **32/33**, and expansion GPIO **5**. The
  [HT-N5262M module schematic](https://resource.heltec.cn/download/HT-N5262M/HT-N5262M_Schematic_Diagram.pdf)
  does not resolve all carrier connections.

The BSP's LED 35 conflicts with the published battery-shutdown function.
Its QSPI tuple also overlaps BMS/indicator definitions in the application
ports. These conflicts cannot be treated as confirmed bootloader wiring.
Factory HT-n5262 HEX CF2 confirms **239A:0071**, but a common factory USB ID
does not resolve the board's GPIO differences. A safe Solar port needs the
exact carrier revision schematic, indicator type, actual staging storage and
watchdog behavior during lengthy DFU before promotion.

## Verification scope

The new Nano, Meshtiny and M8 source ports are build/test candidates, not hardware
qualified downloads. Pin-contract host tests compile their actual headers
and verify exact buttons, flash pins, LED polarity and factory CF2 identities
where known. M8 instead asserts the invalid draft identity and verifies that
its build cannot run without test mode/version, that its peripheral hooks avoid
PPS, encoder, QSPI and disputed power pins, and that production CI excludes it.
Release inventory tests ensure pending ports stay excluded from normal and
recovery releases. Physical qualification remains the gate documented in
[the coverage audit](meshcore-hardware-coverage.md#hardware-checks-before-promotion).
