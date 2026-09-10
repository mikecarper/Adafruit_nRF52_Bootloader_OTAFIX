# OTAFIX 2.4.7-preview.2

USB READY fix test candidate, not a stable release. Canonical tag:
`0.11.0-OTAFIX2.4.7-preview.2`; packed version: `0x02040702`.
GCC remains 14.2.Rel1. No bootloader region, board identity, signing policy,
storage profile, or forward/reverse version policy is changed.

## USB fix

TinyUSB could wait forever for a peripheral READY event that an earlier
callback had already consumed. The completed-state guard could miss this
when the high-frequency clock was not running across a SoftDevice transition.
The same wait was observed directly on the debug-wired RAK3401 application.

The fix restores the clock before the READY wait, rechecks attachment while
waiting, bounds both waits, and exits if USB has been disabled. It is in the
bootloader's pinned TinyUSB fork and has a separate MeshCore application
backport for all nRF52 environments. **An existing MeshCore application needs
that application update too; installing this bootloader alone cannot repair
its embedded USB driver.**

The inherited failure is now a negative-control regression test: the old
READY prefix must hang in simulation, while the fixed real handler must
return correctly for duplicate events, nested calls, delayed/missing hardware
readiness, removal and retry. This complements the existing mounted-drive
UF2, BLE DFU and mOTA tests; it does not substitute for physical update tests.

See the [USB investigation and provenance](mercer-usb-investigation-2026-09-10.md).
The Pi's separate unattended hub disconnect/controller problem remains under
investigation. This candidate must not be advertised as a Pi-freeze fix.

## Update cautions

- Use the exact board and storage profile, including MeshTower V2 SD versus
  internal storage and RAK3401 versus RAK4631.
- On OTAFIX 2.4.3, update the bootloader before copying a MeshCore application
  UF2 to the mounted USB drive. That older flash-erase regression is separate.
- Combined SoftDevice/bootloader Legacy DFU ZIPs can require an application
  restore. Preserve exact recovery files and node settings before testing.
- Compatible forward and reverse version updates remain supported.
- The Heltec V4 is ESP32, not an OTAFIX bootloader target.

Build sizes, timing and physical results are recorded in the qualification
report after testing, not assumed from preview.1 or older releases.
