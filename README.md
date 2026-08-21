# Adafruit nRF52 Bootloader with Enhanced OTA DFU

## Changes in OTAFIX 2.4.1 preview.9

- **Reliable buttonless USB recovery window**
  Deliberate serial-only (`GPREGRET=0x4E`, including a 1200-baud touch) and UF2 (`GPREGRET=0x57`) entry now allow the full configured 30-second USB enumeration window before returning to a valid application. Once a host mounts, DFU remains available until an update completes or USB is unplugged. MakeCode-style single-tap recovery intentionally retains its brief 3-second window, while button/double-reset recovery remains unbounded.

- **Reliable raw-QSPI resume after deep power-down**
  The bootloader now sends an opcode-only `0xAB` wake as mode-0 GPIO SPI, with conservative CS-high timing guards, before assigning the pins to QSPI and issuing `TASK_ACTIVATE`. This prevents a successful probe or rejected handoff from leaving the NOR asleep and causing the next boot or probe to time out during QSPI activation. Connected QSPI pads are restored to the Nordic high-drive configuration before peripheral handoff; RAK15001 IO2/IO3 remain disconnected.

- **QSPI write and recovery completion hardening**
  External-NOR page programs and interrupted-operation recovery now poll SR1/WIP to completion before verification, deep power-down, reset, or optional rail removal. Unaligned staging reads and the unaligned approval clear are adapted to the nRF52840 EasyDMA word-alignment rules, and timeout paths keep CS inactive without cutting power from a potentially busy flash.

## Changes in OTAFIX 2.4.1 preview.8

- **USB-first recovery with automatic BLE fallback**
  When no valid application is installed, the bootloader first checks for an active USB data host. An enumerated host receives serial/UF2 DFU; battery-only power falls back to BLE OTA immediately, while VBUS-powered devices allow up to 30 seconds for host enumeration or VM USB passthrough before falling back. Builds can override the grace period with `DFU_USB_ENUMERATION_TIMEOUT_MS`.

- **Persistent application CRC validation**
  BLE/serial DFU now saves the CRC that was validated during installation, allowing the bootloader to verify application integrity on subsequent boots.

- **Clean reboot after BLE OTA**
  A successfully installed BLE application now starts after a hardware reset, ensuring clean SoftDevice, radio, and peripheral state. Interrupted updates still re-enter recovery DFU.

- **Reliable BLE OTA connection settings**
  Uses a 15-30 ms preferred connection interval with zero slave latency and lets the phone control connection updates, avoiding both the earlier throughput regression and connection-update races.

- **Board-configurable bootloader display layouts**
  The status-screen renderer now supports arbitrary integer font scaling and board-level coordinates. This keeps the 240x135 ST7789 layout while fitting the complete UF2 and BLE status screens on 160x80 ST7735 panels.

- **WisBlock RAK3401 support**
  Adds a current CMake/Make target with the correct nRF52840 rail voltage, base-board LEDs, and BLE identity. It retains the factory RAK4631 bootloader's legacy `0x239A:0x0029` UF2 identity for immediate device compatibility while using the board-specific `3401_DFU` manifest identity for safe self-updates.

- **Heltec Mesh Node T1 support**
  Adds both build systems, the two bootloader buttons, and the complete 160x80 display layout. For immediate factory-device compatibility, this target explicitly retains Heltec's legacy `0x239A:0x0071` UF2 identity while using the board-specific `T1_DFU` manifest identity for safe self-updates.

- **Heltec MeshTower V2 support**
  Adds a dedicated headless target with the correct status LED, user button, and external-watchdog feed. Both the standard-power V2 and high-power V2H use this target.

- **MeshTower V2 microSD self-updates**
  The `heltec_mesh_tower_v2_sdcard` target reads a checksummed raw-sector handoff from the onboard microSD socket and applies either a full MeshCore `.mota` image or an in-place delta. The card holds the download, while application writes remain bounded below InternalFS at `0xED000`. Build it with `make BOARD=heltec_mesh_tower_v2_sdcard`; it must be paired with MeshCore's SD-card firmware target.

- **Raw-QSPI MeshCore repeater self-updates**
  Exact-board targets for XIAO nRF52840 BLE/Sense, original LilyGo T-Echo, ThinkNode M1/M6, Wio Tracker L1, SenseCAP Solar Node P1, and RAK4631 with a RAK15001 in sensor Slot C can read a verified raw `.mota` from external flash and apply either a full image or an in-place delta. They must be paired with the matching MeshCore QSPI repeater build; a board merely exposing QSPI-named GPIO is not supported. Build the RAK target with `make BOARD=wiscore_rak4631_board_rak15001_slot_c`. It uses 8 MHz standard SPI over the nRF52840 QSPI peripheral, requires the exact `C8:40:15` GD25Q16 JEDEC ID, and leaves QSPI IO2/IO3 disconnected. WP# and HOLD# use the module's onboard pull-ups, so the bootloader does not drive WB_IO4. The Slot C deployment contract avoids the RAK12501 GNSS module's RESET/1PPS lines whether GNSS occupies its supported Slot A or D. Do not combine this target with Ethernet, SD, or another WisBlock SPI module: WisBlock sensor slots share SPI and chip-select, so those configurations must use their own update storage/transport. The ordinary RAK4631 target retains internal staging. RAK3401 is excluded because its required RAK13302 radio uses the same SPI bus and chip-select as RAK15001. Heltec T114 is excluded because its public schematics mark the MX25R1635F U9 footprint optional, so the standard target cannot assume it is populated.

- **Fail-closed bootloader UF2 updates**
  Bootloader self-update files now carry a board-bound manifest and a CRC32 over the complete bootloader region. The receiver verifies the UICR addresses, legacy VID/PID, unique DFU device identity, manifest, and CRC before asking the MBR to copy the image. This distinguishes boards such as the T1, T096, T114, and MeshTower even though their factory bootloaders share a VID/PID. A bootloader containing this check intentionally rejects older self-update UF2 files that do not have the manifest; newly generated files remain installable by older bootloaders.

## Changes in OTAFIX 2.4

- **In-place OTA delta apply**  
  Adds on-device application of compact firmware *delta* updates (MeshCore `.mota` containers), letting a device with no A/B slot update over a low-bandwidth link without transferring a full image.  
  After the running application stages a verified, approved `.mota` in free flash and reboots with the apply trigger set, the bootloader locates it, re-checks that the delta was built against the exact running firmware (the `.mota` `base_hash` vs the `EndF` trailer of the current app), applies the patch in place with the bundled [detools](https://github.com/eerimoq/detools) decoder, and verifies the result against the manifest `image_hash` before marking the new image valid.  
  The trigger is a dedicated `GPREGRET` magic set only on approval, so normal boots never scan or apply. Any failure (no trigger, base mismatch, bad patch, post-apply hash mismatch) leaves the bank invalid and falls through to OTA DFU - an interrupted apply can never boot a corrupt image.

## Changes in OTAFIX 2.2

- **Use maximum TX power for BLE**  
  Changed BLE TX power to be set to +8 for nRF52840.

- **New boards**  
  Elecrow ThinkNode M1, M3, M6  
  LilyGo T-Echo  
  Minewsemi MX25LE01  
  Seeed SenseCAP Solar Node P1\
  Heltec T096

## Changes in OTAFIX 2.1

- **Defaults to OTA DFU mode**  
  When no valid application is present, the bootloader defaults to OTA DFU mode.  
  This prevents devices from becoming stuck in UF2 mode after a failed OTA update.

- **High-MTU BLE support**  
  Enables larger DFU packets for improved throughput when supported by the client.  
  The Android DFU app and [`dfu.py`](https://github.com/recrof/nrf_dfu_py) support large packets; the iOS DFU app is limited to 20-byte packets.

- **Lazy flash erase**  
  Flash pages are erased on demand during the transfer instead of upfront, significantly reducing the delay during DFU initialisation before the transfer begins.

- **Small-packet accumulation**  
  Packets smaller than 64 bytes are combined at the transport layer and written to flash in chunks of up to 240 bytes.  
  This improves OTA performance from iOS devices and other small-packet DFU hosts by reducing flash write overhead.

- **Automatic application boot after OTA over USB**  
  When connected to a USB host, devices now automatically reboot into the application after a successful OTA update, instead of requiring a manual reset.

- **Unique BLE advertising names per board**  
  In OTA DFU mode, devices advertise using a board-specific name instead of the generic `AdaDFU`:
  - **Elecrow ThinkNode M1** -> `TNM1_DFU`
  - **Elecrow ThinkNode M3** -> `TNM3_DFU`
  - **Elecrow ThinkNode M6** -> `TNM6_DFU`
  - **Heltec T114** -> `T114_DFU`
  - **Heltec T096** -> `T096_DFU`
  - **Heltec T1** -> `T1_DFU`
  - **Heltec MeshTower V2 / V2H** -> `TOWER_V2_OTA`
  - **LILYGO T-Echo** -> `LGTE_DFU`
  - **Minewsemi MX25LE01** -> `MX25_DFU`
  - **ProMicro NRF52840** -> `PROM_DFU`
  - **RAK 3401** -> `3401_DFU`
  - **RAK 4631** -> `4631_DFU`
  - **RAK WisMesh Tag** -> `RTAG_DFU`
  - **Seeed SenseCAP Solar Node P1** -> `SCAP_DFU`
  - **Seeed T1000e** -> `T1KE_DFU`
  - **Seeed WioTracker L1** -> `WTL1_DFU`
  - **XIAO NRF52 BLE / SENSE** -> `XIAO_DFU`

---

## Boards supported
- Elecrow ThinkNode M1
- Elecrow ThinkNode M3
- Elecrow ThinkNode M6
- Heltec Automation Mesh Node T114 / HT-nRF5262
- Heltec Automation Mesh Node T096 / HT-n5262G
- Heltec Automation Mesh Node T1
- Heltec Automation MeshTower V2 / V2H
- LilyGO T-Echo
- Minewsemi MX25LE01
- Nologo ProMicro NRF52840 (aka SuperMini NRF52840)
- RAK 3401
- RAK 4631 ([See note](#notes-on-RAK4631-bootloader))
- RAK WisMesh Tag
- Seeed Studio SenseCAP Card Tracker T1000-E
- Seeed SenseCAP Solar Node P1
- Seeed Studio Wio Tracker L1
- Seeed Studio XIAO nRF52840 BLE ([See note](#notes-on-xiao-nrf52840-ble))
- Seeed Studio XIAO nRF52840 BLE SENSE

If there is another nRF52840-based board you would like to see supported please raise a github issue and we can make it happen.

---

## Installation

**IMPORTANT:** If you are running a MeshCore companion firmware or Ripple firmware on your device **you will need to run an erase after flashing a new bootloader**. Use the MeshCore web flasher to do the erase, it will guide you to the correct erase firmware for your device. Other erase firmwares will not work, they will not erase the ExtraFS area.

The recommended way to install the bootloader is using the UF2 file.  
Download the UF2 file for your board (they can be found in the releases with filenames beginning with `update-` and ending in `_mbr.uf2`), enter UF2 mode (usually by double pressing the reset button within 0.5s) and copy the UF2 file across. The `_mbr` artifact contains the MBR and bootloader; SD-card and QSPI apply support are determined by the exact board target. Packages ending in `_s140_<version>.zip` additionally contain the SoftDevice.

See the [OTAFIX releases](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases) and use a release whose notes explicitly list your exact board and required SD or QSPI apply mode.

When migrating a RAK4631 from the ordinary `wiscore_rak4631_board` bootloader to
`wiscore_rak4631_board_rak15001_slot_c`, do **not** use the canonical slot-C
bootloader-update UF2 for the first migration. A current board-bound ordinary RAK4631
bootloader expects the DFU device name `4631_DFU`, while the slot-C target is intentionally
identified as `4631_15001C_DFU`, so it rejects that cross-target UF2. Use the exact slot-C
OTAFIX combined bootloader + SoftDevice package ending in `_s140_<version>.zip` through
serial DFU or a compatible BLE DFU client, or flash the exact slot-C image with SWD. A
MeshCore application Serial DFU ZIP updates only the application and is not a substitute.
Reinstall the matching slot-C MeshCore application after this one-time bootloader migration;
subsequent canonical slot-C bootloader-update UF2 files can then be used normally.

The direct preview.7 links below are retained for their original board targets, but preview.7 has only a
brief USB recovery probe and predates raw-QSPI apply support. Use preview.8 or newer for the 30-second USB
recovery grace. Raw-QSPI apply requires preview.9 or newer; verify the release notes explicitly list the
exact board and QSPI mode.

- [Heltec T1 UF2](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/download/0.9.2-OTAFIX2.4.1-preview.7/update-heltec_t1_bootloader-0.9.2-OTAFIX2.4.1-preview.7_mbr.uf2)
- [Heltec T096 UF2](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/download/0.9.2-OTAFIX2.4.1-preview.7/update-heltec_t096_bootloader-0.9.2-OTAFIX2.4.1-preview.7_mbr.uf2)
- [Heltec T114 UF2](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/download/0.9.2-OTAFIX2.4.1-preview.7/update-heltec_t114_bootloader-0.9.2-OTAFIX2.4.1-preview.7_mbr.uf2)
- [Heltec MeshTower V2 UF2](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/download/0.9.2-OTAFIX2.4.1-preview.7/update-heltec_mesh_tower_v2_bootloader-0.9.2-OTAFIX2.4.1-preview.7_mbr.uf2)
- [WisBlock RAK3401 UF2](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/download/0.9.2-OTAFIX2.4.1-preview.7/update-wiscore_rak3401_bootloader-0.9.2-OTAFIX2.4.1-preview.7_mbr.uf2)

If you have somehow managed to accidentally flash an incorrect bootloader to your device you will likely require flashing a full bootloader and SoftDevice zip package using ``adafruit-nrfutil``

---

## Troubleshooting

### Device does not appear as a USB drive or serial port

If the device does not show up on your computer after flashing the bootloader or performing an OTA update, it may be **waiting in OTA DFU mode**.

In **OTAFIX 2.4.1 preview.8** and above, a device without a valid application chooses its recovery transport automatically:
- Connected to an active USB data host: serial and UF2 DFU remain available.
- Running on battery: BLE OTA starts immediately because VBUS is absent.
- Connected to USB power without a data host: BLE OTA starts after the 30-second USB detection window.

Preview.7 offers USB only briefly before falling back to BLE. Other older OTAFIX builds may fall directly
to BLE. On those versions, a host or VM that attaches too slowly can miss the USB window even though the
cable supplies power.

**What to do:**
- On preview.8 or newer, connect the device to a computer with a data-capable USB cable and wait for the UF2 drive or serial port, **or** perform an OTA update using a supported DFU app.
- On preview.7 or older releases, explicitly request UF2/serial mode using **double-reset**, or perform a BLE OTA update.

This behavior keeps computer-based recovery available without leaving battery-powered devices stuck waiting for USB.

---

### OTA update fails with `Error: Operation Failed`

If an OTA update consistently fails early with `Error: Operation Failed`, this is often caused by BLE stack incompatibilities when **Request High MTU** is enabled.

**What to try:**
- Experiment with different PRN settings. Try 12, 8, 1, or even off altogether!
- Disable **Request High MTU** in your DFU app

While high MTU significantly improves performance on supported devices, it is not required for a successful OTA update.

---

## Recommended OTA DFU settings

To perform the OTA update you can use **nRF Device Firmware Update**  
([Android](https://play.google.com/store/apps/details?id=no.nordicsemi.android.dfu&hl=en&gl=US) / [iOS](https://apps.apple.com/sa/app/device-firmware-update/id1624454660))  
or **nRF Connect**  
([Android](https://play.google.com/store/apps/details?id=no.nordicsemi.android.mcp&hl=en&gl=US) / [iOS](https://apps.apple.com/gb/app/nrf-connect-for-mobile/id1054362403)).

My preference is the **nRF Device Firmware Update** app.

For **OTAFIX 2.0**, the following settings are recommended (these may change - feel free to experiment and report your findings):

<table>
<tr>
<td valign="top">

**Packet Receipt Notification (PRN):** ON  
**Number of packets:** 8  
**Reboot time:** 0ms  
**Scan timeout:** 2000ms  
**Request high MTU:** ON for Android (See notes below) / Not available on iOS  
**Disable resume:** ON  
**Prepare object delay:** 0ms  
**Force scanning:** ON  
**Keep bond:** OFF  
**External MCU DFU:** OFF  

**Notes:**
- Some Android devices and BLE stacks do not behave well with **Request high MTU** enabled.  
  If the transfer fails early with `ERROR: Operation Failed`, retry with **Request high MTU turned OFF**.
- Keep Packet Receipt Notification enabled with no more than 8 packets. Higher values can overrun the bootloader's receive and flash queues on faster phones.

</td>
</tr>
</table>

[Recommended settings for versions prior to 2.0 can be found here](docs/oldsettings.md).

**IMPORTANT:**  
On <u>older versions</u> of the bootloader, performing an OTA update while the device was connected to a computer USB host would complete successfully but **would not automatically boot into the new application firmware**, requiring a manual reset.  
This issue is fixed in **OTAFIX 2.0**.

---

## OTA update on a MeshCore repeater

First you will need to login to the repeater and issue the `start ota` CLI command.

Next, open the nRF Device Firmware Update app, select the appropriate MeshCore firmware zip file for your device, select your device (it will be advertised as `ProMicro_OTA` / `RAK4631_OTA`, etc), and press start.

---

## Donations

Although it's not necessary, if you find this useful please consider donating to support my work!

[![Ko-Fi](https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/oltaco)

---

## Notes on Xiao NRF52840 BLE

Many of these boards are shipped with the Sense version of the bootloader installed. If your board has the Sense version installed you must use the Sense version when updating via UF2.

You can look at the INFO_UF2.TXT file on the UF2 drive to check what version is currently installed.

To check:
1. Enter UF2 DFU mode (double-press reset) 
2. Open the `INFO_UF2.TXT` file on the mounted drive  

If the file shows: "Board-ID: nRF52840-SeeedXiaoSense-v1" then you must install the ***SENSE*** variant if updating via UF2 file.

## Notes on RAK4631 bootloader

This version of the RAK4631 bootloader is based on a much newer version (0.9.2) of the Adafruit nRF52 bootloader than what RAK Wireless uses on their official bootloader (0.6.2-11).  

I haven't looked to see what changes (if any) that RAK made to the Adafruit bootloader, so I'm not sure if there's any difference but I have tested this bootloader and I haven't found any problems thus far. If you would rather use the original RAK bootloader but with these patches included you can find that [here](https://github.com/oltaco/WisCore_RAK4631_Bootloader/releases).
