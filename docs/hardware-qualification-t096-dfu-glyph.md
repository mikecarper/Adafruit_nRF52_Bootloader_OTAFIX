# T096 block DFU glyph qualification

Test date: 2026-09-04. Target: `heltec_t096`, connected to a Raspberry Pi
controller. Device and controller identifiers are omitted from this public report.

## Candidate

- Board: `heltec_t096`, display ST7735S, bootloader test version `0x02040401`.
- UF2: `cmake-build-heltec_t096/bootloader_mbr.uf2`, 87,552 bytes.
- SHA-256: `829d7db9bf2d99b7c8465d1100675ff61bde0b0cd1efb6030c52f19f8af999ec`.
- Embedded manifest: `T096_DFU`, CRC32 `3809BD95`; locally verified.
- Expected display: white block `DFU` on black, 121 by 55 pixels, at (19, 12).
- Both required board builds pass. T096 uses 40,292 of 40,784 executable flash
  bytes; T114 uses 40,724, leaving 492 and 60 bytes respectively.
- The shared internal-MOTA USB/BLE display path uses the same glyph. T114 has
  build verification only; its expected glyph is 209 by 95 pixels at (15, 20).

## Hardware observations

1. Following a controller outage, the T096 enumerated its application USB
   interfaces but returned no bytes to either the ASCII terminal or Binary
   Companion device query. A host USB bus reset reported success but did not
   restore replies. Unplugging and reconnecting the T096 restored both
   protocols. No firmware had been written before that recovery.
2. The live application was Full Companion
   `v1.17.1-uf2reset-f2c15225-f2c15225`, protocol 14. It is an OTA seeder with
   install disabled and no folder connected. This build does not expose the
   installed bootloader CRC through `ota bootloader` or `get bootloader.ver`.
3. The candidate was hashed again on the controller. Only the exact target
   USB serial-number match was selected, first as application `239a:8029`,
   then as bootloader `239a:0071` after the local `uf2reset` command.
4. The matching `HT-n5262G` UF2 volume was mounted with
   `sync,nosuid,nodev,noexec`. The verified bytes were streamed to a new UF2
   file. Linux returned an I/O error after 5.916 seconds, so the installer
   stopped without retrying. Kernel evidence recorded USB disconnect followed
   by a failed write to sector 517, the FAT root-directory area. Application
   USB returned about two seconds later and completed dual-CDC enumeration.
5. Subsequent live reads matched the pre-update application body hash,
   firmware version, node name, public identity, radio settings, and logging
   configuration. No application restore was required. The temporary UF2
   mount was removed; the controller's existing radio service was not stopped.
6. A second `uf2reset` entered the same device's DFU mode for visual inspection.
   USB enumeration suppresses the 30-second startup timeout, but not the
   separate six-minute DFU inactivity timer (`DFU_TIMEOUT_INTERVAL`,
   360,000 ms). That timer starts in `dfu_init()` and is restarted by the
   serial/BLE DFU packet handlers.
7. The operator confirmed the new glyph looked good. No shared-hub power
   operation was attempted.
8. The operator later reported an automatic exit after approximately five
   minutes. Kernel timestamps confirmed application enumeration six minutes
   after DFU enumeration. Post-exit terminal queries again matched the
   application hash, version, public identity, name, and radio settings. The
   terminal was returned to Binary mode. The earlier conclusion that leaving
   DFU required a physical reset was incorrect.

Application body size was 501,428 bytes; complete image size was 501,484 bytes.
USB logging remained enabled on separate interface 02; primary interface 00
responded. Private device identity and deployment-setting values are retained
only in the local qualification record.

## Qualification status

Application preservation, DFU re-entry, and idle timeout return passed. The
host UF2 transfer was not a clean transport pass because it reported an I/O
error. Its timing and directory-sector error are consistent with immediate
bootloader self-update reset, but do not independently prove the installed
image's CRC. No CRC readback or pixel capture was available from this
source-only Companion.

**Operator visually confirmed the new DFU glyph: "DFU looks good" (PASS).**
No hardware claim is made here about hybrid RAM OTA staging or the physical
T114 display.

Detailed controller logs and device-specific evidence are retained locally.
