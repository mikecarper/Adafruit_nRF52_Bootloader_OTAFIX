# OTAFIX 2.4.5

Stable OTAFIX 2.4.5 release based on Adafruit bootloader 0.11.0.

## Fix for Android `GATT INVALID HANDLE`

OTAFIX 2.4.5 fixes the bonded application-to-bootloader reconnect that could
make Nordic's Android DFU client stop while reading DFU Version. OTAFIX 2.4.4
does not contain this correction.

The old bootloader asked the SoftDevice to send Service Changed for an
unpopulated handle range. The SoftDevice rejected that request, but the error
was treated as harmless. After the buttonless application disconnected and the
bootloader reconnected at the same bonded address, Android could therefore use
the application's cached DFU Version handle against the bootloader's different
GATT database and receive `GATT INVALID HANDLE`.

The new bootloader:

- indicates the runtime-populated DFU-through-Device-Information range;
- keeps the indication pending until the SoftDevice successfully queues it;
- retries after connection, system-attribute, encryption, and MTU events; and
- treats optional data-length and MTU negotiation failures as nonfatal.

## Updating to 2.4.5

Use only the artifact matching the exact board and storage profile. The signed
bootloader `.mota` is the preferred application-preserving path on supported
MeshCore targets. The dedicated exact-board `update-..._mbr.uf2` also updates
the bootloader through its guarded staging path. Combined SoftDevice and
bootloader Legacy DFU ZIPs generally require MeshCore to be reinstalled. SWD
sector programming can preserve untouched sectors, but `--recover` erases the
device.

The fix takes effect after 2.4.5 is installed. A target still running 2.4.3 or
2.4.4 executes the old BLE code during its one-time upgrade. If Nordic's phone
app already stops at `GATT INVALID HANDLE`, bootstrap 2.4.5 with the exact-board
signed `.mota`, dedicated bootloader `_mbr.uf2`, serial Legacy DFU, the hardened
XIAO BLE updater, or SWD instead of repeatedly clearing the phone cache.

If OTAFIX 2.4.3 is installed, update the bootloader before copying a MeshCore
application `.uf2` to the mounted UF2 drive. That warning is specific to the
mounted-drive application path. The dedicated exact-board bootloader
`update-..._mbr.uf2` uses a separate guarded path and remains an allowed upgrade
method.

## GAT562 LoRa field kit

The release includes a self-contained, phone-driven
`GAT562-OTAFIX-2.4.5-LoRa-field-kit.zip`:

```text
Android phone -- encrypted Bluetooth --> local Full Companion source
local XIAO or second GAT562 ---- LoRa --> remote GAT562 repeater
```

The remote GAT562 target is **not** connected by USB. The kit contains the
isolated arm64 Android field APK, protocol-v14 Full Companion firmware for
either a XIAO nRF52840 plus Wio-SX1262 or a second GAT562 30S Mesh Kit, the
exact signed GAT562 `.mota`, official key and hashes, and the GAT562 30S LoRa-OTA
receiver application for pre-deployment/recovery. The `.mota` remains on the
phone and is streamed in small blocks through a 256-byte RAM ring, so the
source does not use its external file storage. The XIAO's 2 MB external flash
is not used.

The remote GAT562 must already expose MeshCore's `ota` commands. In the field
app, connect to either local Full Companion by Bluetooth, log into the GAT562
under **Repeater Management**, require
`board=239A0029 target=D50D2D44 name=GAT562_DFU abi=3 caps=0A`, trust the
included official key, then open **LoRa OTA** and choose the bundled `.mota`.
For a direct link use Direct for both paths, tap **Test radios and start
source**, then **Pull** MID `0E2DE4B7`.

Once the target reports ready, **Install and reboot** first requires the exact
remote confirmation
`staged:ready mid=0E2DE4B7 hash=B23AD0E2E86C38E2`. Only then does the app send
the explicit bootloader install command. This profile is not for legacy
`4631_DFU` installations or the GAT562 Mesh Watch 13. The archive's README has
the complete direct/routed recipe and recovery guidance.

## Compatibility and validation

- Packed bootloader version: `0x020405FF`.
- All 27 board profiles build with Arm GNU Toolchain 14.2.Rel1.
- Make and CMake validate both `heltec_t096` (ST7735S) and `heltec_t114`
  (ST7789), including signed and dual-bank CI variants.
- Host tests synthetically reproduce the old invalid Service Changed range and
  verify successful range selection, retry state, disconnect cleanup, and
  nonfatal optional-procedure behavior.
- A live T1000-E bonded handoff observed the corrected Service Changed range
  and confirmation. The original reporter's exact GAT562/Android combination
  was not available for a final end-to-end rerun before release.
- The 2.4.3 mounted-drive differential and drive-copy harnesses remain in the
  release gate.

The release also includes the documentation and synthetic mounted-drive tests
added after 2.4.4. No application, node identity, or MeshCore data format was
changed by the 2.4.5 firmware fix.

[Full source comparison](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/compare/0.11.0-OTAFIX2.4.4...0.11.0-OTAFIX2.4.5)

[Detailed 2.4.4 hardware qualification and timings](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/0.11.0-OTAFIX2.4.5/docs/hardware-qualification-0x02040405.md)
