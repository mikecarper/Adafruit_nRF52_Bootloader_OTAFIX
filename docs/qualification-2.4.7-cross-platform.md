# OTAFIX 2.4.7 cross-platform and LoRa qualification

Qualification date: 11 September 2026. This is a development qualification,
not a stable release or an all-board physical qualification.

## Native Windows and Linux builds

All 27 curated boards built with CMake on native Windows and Linux. T096 and
T114 additionally built with SIGNED_FW, DUALBANK_FW, both together, and the
separate recovery profile. All **140 artifacts match byte-for-byte** across
the two hosts: BIN, HEX, MBR HEX, and MBR UF2 for 35 configurations.

- Firmware source: `a3ff2e076d2110bf334f3f257a16a47b0e52f864`, plus the
  host packaging fixes accompanying this report. No device firmware code
  or linker layout was changed during this qualification.
- TinyUSB: `db87375176ee49a7ee8488d08d526595c6a044c4`.
- ARM compiler on both hosts: Arm GNU Toolchain 14.2.Rel1, build arm-14.52,
  GCC 14.2.1 20241119.
- Windows used native MinGW Makefiles, not WSL. Linux used Unix Makefiles
  in the existing isolated build container, without network/device access.
- Both used `SOURCE_DATE_EPOCH=1789114216`, `MOTA_BOOTLOADER_TEST_BUILD=ON`,
  and `MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040703`.
- Signed-build compilation used the existing CI public test coordinates.
  Signed/recovery profile binaries were not flashed during these tests.
- The complete artifact sizes and SHA-256 values are in
  [the comparison record](qualification-2.4.7-cross-platform-hashes.json).
  Debug ELF files are deliberately excluded; their host paths are different.

The initial comparison already matched all 54 standard BIN/UF2 files.
Intel HEX file output differed only by CRLF versus LF. Both manifest patching
and MBR merging now explicitly write ASCII/LF files. Rebuilding all boards
confirmed byte-identical HEX output without changing any BIN/UF2 payload.

For reproduction, set the same epoch on both hosts before configuring and
building each board:

```text
cmake -S . -B <build-dir> -DBOARD=<board> -DMOTA_BOOTLOADER_TEST_BUILD=ON -DMOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040703
cmake --build <build-dir> -j 4
```

Add `-G "MinGW Makefiles"` on Windows. The four extra display profiles use
the same options and public test coordinates as `githubci.yml`. A production
release still requires an exact clean tag; no tag was created or moved here.

## Host verification and fixes

- Linux full host `make -C test check` and ASan/UBSan suite passed.
- Native Windows manifest-patcher tests passed, including CRLF input,
  canonical LF output, idempotence, CRC verification, and overlap rejection.
- Updater helper tests passed on Windows and Linux. A source response of
  `COUNT -> 0` now fails immediately instead of being reported ready. A
  stale positive count cannot hide a subsequent empty catalog, process exit,
  or ownership error. Discovery of the exact requested MID is still required.
- The readback regression vector inflater now preserves a supplied delta
  already larger than its requested fixture size. Previously it rejected
  legitimate large qualification inputs before testing the apply code.
  A regression explicitly checks that the inflater never shrinks its input.
- The committed vectors and the actual large application A/B images passed
  the internal readback suite on native Windows and Linux. A separate
  ASan/UBSan run of the real hybrid entry point reproduced the expected image and
  rejected a corrupted SRAM tail before changing application flash.

These are packaging/updater/test-runner fixes. No signing requirement,
identity check, version policy, flash bound, or retained-RAM guard was relaxed.

## Physical signed bootloader LoRa transfers

Firmware bytes traveled over LoRa between two radios. USB supplied local
control commands and the source's folder data; this was not a phone-only
remote-admin test. Packages were independently signature-verified, checked
against exact board/storage identities, and approved only after the staged
MID and image hash matched the selected package.

| Receiver | Source | Download | Installed CRC | Result |
| --- | --- | --- | --- | --- |
| MeshTower V2 microSD | RAK3401 Full Companion | 40 x 1024-byte blocks; about 67 s | `8EC3DD7C` | `blup:C8`; original application/name/radio unchanged |
| RAK3401 internal flash | T096 Full Companion | 40 x 1024-byte blocks; about 389 s | `779EBE1E` | `blup:C8`; test receiver application/name/radio unchanged |

The MeshTower moved from its installed 2.4.5 image to the test candidate.
RAK3401 moved from 2.4.7-preview.2 to the test candidate. SWD subsequently
confirmed the RAK3401's entire installed 40 KiB bootloader equals the
cross-platform candidate BIN; MBR, SoftDevice, and UICR were unchanged.

Both used SF5/BW500/CR5 with RXPS enabled. The receivers reported effective
level 8 and a 128-symbol preamble. Temporary radio settings were restored.
The transfer times are observations from this bench, not a throughput or
long-duration reliability qualification.

After its LoRa update, the MeshTower passed three additional software
reboots, each with verified USB disappearance/return, candidate CRC, and
unchanged application hash and saved name/radio. These were warm reboots,
not battery-off cold starts.

RAK3401 was temporarily provisioned with the USB-fixed receiver from MeshCore
`602dbfe3d9ad43630d9b4b6e8d9b6a73f4bc48b8`. Its original full flash was captured
twice and matched before testing; UICR was also backed up. Copies were stored
off the Pi. Every SWD operation checks the chip identity before halt/reset/write.
The local lab signer was used only for qualification, not as a production key.

## Large application / retained-RAM qualification

The application test pair uses the same pinned MeshCore receiver. Build B
adds 80 KiB of inert, deterministic flash-only data to force a substantial
delta without adding heap use or changing its radio behavior. The signed
package is 154,802 bytes, with 76 application blocks of up to 2048 bytes.
Its deterministic split is 90,112 bytes of flash at `0xD7000` plus 64,690
bytes of the fixed arena at `0x20030000`.

The existing bootloader-package tool pin `9eef6e5` rejects application layout
flag `0x10`; it was not used to generate this hybrid delta. The application
builder was pinned to the existing upstream hybrid fix
`8c38369e7d35ad50cf74261869676d52dd24adf7`; its locked Rust tests and release
build passed. No guard or layout record was patched out to generate a file.

The physical transfer completed all 76 blocks in about 955 seconds, still
at SF5/BW500 with RXPS enabled. Before approval, SWD readback verified the
entire flash prefix and SRAM tail against the signed package byte-for-byte;
the original application was unchanged. One `ota install` approval applied
the update and rebooted into build B with `blrc:B8` and no pending download.
Full SWD readback matched all 571,952 application bytes against the expected
image, SHA-256
`728160e89c4fe833a96065c5c9307210d976a0d0fb28ee281d06e1d731fba1e6`.
The bootloader, MBR, SoftDevice, and UICR were unchanged by this application
update. This exercises actual retained SRAM, not just a host simulation or
a package small enough to fit entirely in flash.

The immediate serial health check after halting the CPU for the full SWD
readback returned empty replies. Subsequent queries recovered without a
reset or reinstall and confirmed the application hash, success status,
saved name/radio, and RXPS setting. The initial harness assertion and the
successful follow-up are both retained in the private evidence. This is
a recorded post-debug delay, not a claim of uninterrupted USB operation.

## Local rollback and restoration

On RAK3401, a local SWD rollback from the candidate to the original
2.4.7-preview.2 bootloader passed. Readback confirmed the exact original
bootloader bytes, and build B then booted with its application hash unchanged.
This was a local recovery test, not a remote downgrade or a bypass of the
application's monotonic bootloader-version policy.

The candidate bootloader was then reinstalled and the RAK3401's original
Full Companion application, ExtraFS, InternalFS, and bootloader settings
were restored from the verified pre-test backup. Before reboot, full SWD
readback confirmed the original bytes throughout `0x26000..0xF4000` and
`0xFF000..0x100000`, the candidate at `0xF4000..0xFE000`, and unchanged
MBR/SoftDevice/UICR. Restoring both filesystems matters because the enlarged
test staging window overlaps the original Companion's ExtraFS region.
The original Companion version, application hash, saved name/radio, and
source-only role were verified after reboot. The temporary receiver and
its added lab key were not left installed.

Final health checks passed for RAK3401, T096, and the SD MeshTower: original
application hashes, names, and saved radios matched their baselines, and
no source folder or update remained active. RAK3401 and MeshTower retain
the tested candidate bootloaders. Temporarily stopped host services were
restarted, and the Pi reported no current or historical throttling flags.

## Scope limits

T096 was exercised as a LoRa source; its application was not replaced.
T114 was compile-tested across the build variants but no physical
T114 was available in the identified USB inventory. Other attached boards
were not indiscriminately reflashed. No unread Companion messages were
cleared to free a queue. External-QSPI OTA, phone DFU, battery-off cold starts,
and long soak tests are not claimed by this report. No Pi reboot, USB hub
reset, mass erase, or permanent host-service configuration change was used.

Private identities, keys, raw radio logs, and device backups are excluded
from this report and from Git.
