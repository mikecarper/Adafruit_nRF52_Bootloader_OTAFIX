# MeshTower V2 SD-card bootloader update

Date: 2026-09-05. Target: MeshTower V2 SD-card repeater, connected by USB to a
Linux VM. Device and controller identifiers are omitted from this public report.

## Release artifact

- Official release: [OTAFIX 2.4.5](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/0.11.0-OTAFIX2.4.5).
- Exact board profile: `heltec_mesh_tower_v2_sdcard` (not the internal-storage variant).
- File: `update-heltec_mesh_tower_v2_sdcard_bootloader-0.11.0-OTAFIX2.4.5_mbr.uf2`.
- Size: 88,064 bytes, 172 UF2 blocks.
- SHA-256: `3d4d33dd368d23154b2289b8e56781fff68d1cd56987334e14ae0208cd77a111`.
- Embedded version: `0x020405FF`; whole-image BLMF CRC: `EDAD06C6`.
- Board ID `239A0071`, device name `TOWER_V2_OTA`, apply ABI 3,
  codecs `0x0005`, storage capability `0x09` (`SD|BOOT_UPDATE`).
- Compatibility envelope: S140, FWID `00B6`, application base `00026000`,
  layout ABI 1.

Before device writes, the downloaded bytes matched GitHub's asset digest.
Validation also checked UF2 block geometry, bootloader-family ID, allowed
address ranges, complete bootloader-slot coverage, board-bound CRC, version,
SoftDevice/layout envelope, and the structured SD-card compatibility marker.
No locally modified firmware was built or substituted for the GitHub artifact.

## Pre-update application

- USB application descriptors: `239a:4405`, `HT-n5262`, interface 00.
- Application version: `1.17.1.5-halo-keymind-cascade-marathon-hwtest-e26d48e4`
  (build 30-Aug-2026).
- Application body/image lengths: 487,288 / 487,344 bytes.
- Existing bootloader CRC: `868CB6DC`; target `1150F50E`, ABI 3, caps `09`.
- No staged bootloader package or active OTA download; OTA serving off.
- Firmware profile: `Heltec_tower_v2_sdcard_repeat`; one trusted OTA key.
- This older application reports `get bootloader.ver` as unknown, but
  `ota bootloader` exposes its installed bootloader CRC and capability profile.

The application hash, public identity, name, and radio configuration were
captured for comparison. Device-specific values remain in the local record.

## Procedure and outcome

The application image ends below the bootloader UF2 scratch region at
`0xE0000`. The selected operation was the dedicated bootloader UF2 path, not
the combined Legacy DFU package that would require application restoration.

The initial 1200-baud USB touch entered **serial-only DFU** (interfaces 02/0A,
no mass-storage drive). The installer refused to write because no UF2 disk
belonged to the exact target USB serial. No firmware was written in this
attempt. The running firmware's exact source commit was then checked: local
`uf2reset` requests `GPREGRET=0x57` and exposes the UF2 drive. The serial-only
session was allowed to expire normally before using that command.

The VM automatically mounted the UF2 drive. This was the expected compact,
label-only volume, without `INFO_UF2.TXT`. Before writing, the disk was traced
through sysfs to the exact target USB serial, and its `HT-n5262` product and
volume label were checked. The VM's own disk and other devices were not touched.

A privileged copy attempt was refused by `sudo` before any bytes were written.
The actual copy used the existing user-writable mount without privilege,
exclusive file creation, and the already SHA-256-verified bytes. After 4.925
seconds, the final file sync returned an I/O error as the bootloader detached
and the application returned. No further firmware copy was attempted after
that write; the live installed CRC was checked instead.

**Final result: PASS.** The application reported:

```text
BL board=239A0071 target=1150F50E name=TOWER_V2_OTA crc=EDAD06C6 abi=3 caps=09
```

These are board-profile fields, not a unique device identity. The installed
CRC matches the complete official 2.4.5 image whose version envelope was
independently validated as `0x020405FF`. This older application does not
provide a textual bootloader-version query, so verification uses the exact
image CRC together with unchanged board and storage capabilities.

Post-update queries matched the pre-update application version, complete
application/body lengths and body hash, public identity, name, and radio
configuration. The SD repeater profile and one trusted OTA key remained;
there was no pending OTA download or staged bootloader package. The exact
application USB serial returned. No application restore, SoftDevice
replacement, SD-card operation, or user-settings change was needed.

Detailed controller logs and device-specific evidence are retained locally.
