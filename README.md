# Adafruit nRF52 Bootloader with Enhanced OTA DFU

## Changes in OTAFIX 2.4.4

- BLE application DATA reception now clears this bootloader's local connection
  latency and best-effort disables inherited slave latency for the active
  connection. This does **not** request a new GAP interval or override the
  phone's accepted link parameters; it makes the target attend every available
  connection event while DATA is active. Two bonded XIAO nRF52840 transfers
  improved from about 0.88 kB/s to 3.52--3.53 kB/s while the controller still
  reported the same 30 ms interval and latency 4. Errors from either local
  SoftDevice option fail open so older supported stacks retain the usable link.
  The policy is explicitly entered by `RECEIVE_APP_DATA`, restored on START,
  validation, completion, error, close, or disconnect, and re-applied after a
  connection-parameter update only while that live DATA phase remains active.
- `tools/otafix_legacy_ble_dfu.py` adapts its protocol PRN/write window up or
  down only at exact cumulative receipt boundaries. Every increase is a
  bounded adjacent-level probe; a failed probe rolls back once and blocks
  further increases for that transfer instead of oscillating. The helper also
  waits at most three seconds for BlueZ's separately cached characteristic
  view of the acquired ATT MTU to catch up. The wait requires the exact same
  service collection and characteristic object, rejects malformed capability
  values and clock bounds, aborts on disconnect, and safely retains 20-byte
  writes on timeout. Progress distinguishes bytes sent from bytes confirmed by
  an exact receipt or final RECEIVE response, and reports DATA-phase timing
  separately from end-to-end DFU timing. This sender adaptation is deliberately
  separate from GAP connection-parameter negotiation. An older connected-time
  GAP request was removed because a PHY or data-length procedure could make it
  return busy and reset a fatal-checking bootloader; do not reintroduce an
  unconditional connection update. The optional `--lab-pre-start-pause`
  exposes a bounded hardware-test window after identity/MTU checks but before
  the first DFU write. It does not negotiate anything itself and remains zero
  in production; a lab harness must verify any single connection update before
  allowing START.
- TinyUSB keeps its normal drain-to-empty event behavior for USB control, CDC,
  and MSC traffic. An MSC WRITE10 callback that consumes fewer bytes than it
  received now retains its endpoint buffer outside the global USB event queue
  and is retried once on the next bootloader-loop pass. Each buffered retry has
  a monotonic generation which survives transport reset; BOT/bus reset clears
  the buffered work, and a stale main-loop snapshot cannot consume a different
  WRITE accepted after that reset. This prevents
  bootloader staging from chaining ten complete page erases into one
  approximately 850 ms `tud_task()` call without starving unrelated USB
  events.
- Application and bootloader-staging updates use the proven complete-page NVMC
  erase. Hardware A/B testing found that exact OTAFIX 2.4.2 accepted and synced
  the first application UF2 sector, while exact 2.4.3 disconnected on that
  sector after switching to partial-page erases. A later 2.4.4 candidate
  restored complete-page erasure but still failed because it limited the
  *entire* TinyUSB task to one event per loop. The corrected scheduler drains
  every real USB event and limits only the deferred MSC retry. Each retry now
  performs at most one complete page erase (about 85 ms on nRF52840/833), with
  a complete USB queue drain between busy retries.
- Legacy serial DFU completes a page-rounded erase of the entire destination
  bank during START_DFU preparation, before reporting ready or accepting DATA.
  An attempted USB optimization that moved later page erases into the ordered
  DATA stream disconnected a real XIAO transfer at a page boundary, so both
  USB CDC and hardware-UART builds retain the proven erase-free DATA path. The
  expected multi-second START preparation is intentional, and each page erase
  feeds an inherited watchdog.
- OTAFIX 2.4.3 USB application reception contains the partial-page regression
  and may be unable to bootstrap this fix from an updater UF2. Recover it over
  BLE with the exact-board combined SoftDevice-and-bootloader Legacy DFU ZIP,
  or use a hardware programmer. OTAFIX 2.4.2 uses the working complete-page
  application erase and safe upfront Legacy serial erase, but still lacks the
  new staging scheduler. Ordinary UF2 application updates are safe again after
  2.4.4 is installed. Do not retry a truncated application before replacing an
  affected 2.4.3 bootloader.

The XIAO failure used for the second scheduler correction was not a released
2.4.4 image. Its exact INFO string was
`0.11.0-OTAFIX2.4.3-3-gffb1580-dirty-test-version-0x02040401`, identifying a
dirty candidate built from `ffb1580` with packed test version `0x02040401`.
The installed bootloader-only Legacy DFU ZIP was
`xiao-2.4.4-cleanhandoff-bootloader-only.zip` (SHA-256
`fcd7933afdc3c9dd8d24707084f5106b3612ed162939c02d68440f518d6fdbf6`);
its 40 KiB bootloader payload has SHA-256
`652bb243654bd3d500392e43d015f325061ccb56c418d862f410306c06238b6d`.
That candidate already called `nrfx_nvmc_page_erase()`, but carried the global
one-event TinyUSB budget. It disconnected during the first application-sector
transaction, before a complete image or application-completion handoff existed.
Its BLE-only recovery state was therefore the intended fail-closed result, not
evidence of a late handoff bug. The first MSC-local retry qualification build
used packed test version `0x02040402`. The command-lifecycle and generation-
bound reset hardening described above uses the distinct packed test version
`0x02040403`, so hardware readback cannot confuse those candidates. Test-only
candidates are not release artifacts.

## Changes in OTAFIX 2.4.3

- The MBR bootloader/SoftDevice replacement path now clears its stale BLE-entry
  request and performs a hardware reset after bank finalization. A replacement
  bootloader therefore cannot loop back into BLE DFU.
- Every completed BLE, CDC, or UF2 application install now resets after
  transport teardown, so the application cannot inherit live radio or USB
  peripheral state. USB CDC/UF2 startup also disables any inherited SoftDevice,
  preventing direct NVMC access from faulting on the first settings write or
  page erase.
- Application UF2 reception invalidates the saved application state before its
  first target-page erase, programs only after erase completion, and accepts a
  retransmitted block only when flash already contains the same bytes. OTAFIX
  2.4.3 attempted to split nRF52840/833 page erases into 2 ms partial-NVMC
  retries; hardware testing later proved that path unsafe, so OTAFIX 2.4.4
  restores complete-page erasure.
- Application UF2 completion now waits until the final WRITE10 status has
  reached the host and then honors an explicit eject, physical disconnect, or
  one second without further filesystem/SCSI activity. `SYNCHRONIZE CACHE`
  restarts that idle interval rather than disconnecting immediately because
  Linux can still have virtual-FAT bios queued after its status. This lets
  `cp`/`sync` finish before reset. TinyUSB reports every valid command's full
  CBW-to-CSW lifetime, including delayed WRITE10 data, READ10, and built-in
  commands; BOT/bus reset explicitly releases an abandoned command without
  blessing an image or a half-completed eject. Validated bootloader-family UF2
  keeps its immediate Nordic `COPY_BL` handoff.
- A mounted no-application USB recovery session exits when VBUS is removed, so
  its reset can select battery-powered BLE recovery without a physical reset
  button.
- TinyUSB's nRF5x startup-race fix and a post-SoftDevice HFCLK retry are pinned
  together on the repository's compatible 0.12-era fork.
- Production builds require Arm GNU Toolchain 14.2.Rel1 or newer, use the Nordic
  startup directly, retain GCC's size-reducing builtins, and use one whole-program
  LTO partition. Nonrelease CI and dirty-tree qualification builds carry an
  explicit test-only packed version instead of producing release candidates.
- Make intermediates are guarded by a content-hashed build-profile stamp. A
  repeated identical build reuses its object cache, while changing SoftDevice,
  signing keys or policy, dual-bank/UF2/DFU/debug options, the USB enumeration
  timeout, source selection, or compiler/linker flags forces recompilation and
  relinking. Public artifact names remain unchanged; use a distinct `BUILD=`
  directory when retaining multiple feature variants side by side.

## Changes in OTAFIX 2.4.2

- Release builds use Arm GNU Toolchain 14.2.Rel1 with the cumulative,
  hardware-qualified A/B/C size improvements: ordinary `-Os`, no
  compiler-generated jump tables, and linker alignment-based section sorting.
  The Make and CMake build paths carry the same flags.
- BLE direct-jump entry is bridged through a real reset before OTA startup,
  clearing nRF52840 ACL state while retaining compatibility with installed
  buttonless applications.
- Raw pstorage preserves FIFO order across BUSY retries, lazy erases, callback
  reentrancy, and multi-page clears; retained BLE peer data also uses the
  application-compatible data/CRC layout.
- Host regressions cover reset entry, retained peer layout/linker placement,
  pstorage failure paths, callback reentrancy, and multi-page erase sequencing.

## Changes in OTAFIX 2.4.1 preview.15

- No functional source change from preview.14. This forward-version rebuild is
  the remote candidate used to qualify the corrected monotonic bootloader-update
  path after locally provisioning preview.14.

## Changes in OTAFIX 2.4.1 preview.14

- **Correct runtime SoftDevice continuity check**
  Read the installed FWID with Nordic's required `SD_FWID_GET(MBR_SIZE)` base.
  Preview.13 incorrectly used a zero base, reading the instruction halfword at
  `0x200C` instead of the S140 information field at `0x300C`; remote bootloader
  updates therefore failed closed with `C5` after a successful verified copy.
  An exact-package host regression now reproduces that failure and proves the
  corrected path reaches the MBR handoff.

## Changes in OTAFIX 2.4.1 preview.13

- **Authenticated SD source handoff without filesystem-sector ownership**
  New SD-capable bootloaders do not read or write a sector-1 handoff. Before resetting, the authenticated application writes one 72-byte `MOTASDA2` record at retained RAM `0x20006008` (inside an 80-byte application `PERSISTENT_RAM` region beginning at `0x20006000`). The record binds purpose and format, first LBA, the exact `ceil(container_length/512)` sector count, exact container length, application-observed card capacity, and SHA-256 of the complete container with only `APRV` bytes 201..204 normalized to zero; CRC32 and its complement cover bytes 0..63. OTAFIX copies and zero-consumes this record before its first SD access. The compact boot SPI reader bounds every access against the authenticated LBA/count/capacity geometry and the card itself, but does not issue a second CSD-capacity query; a replacement card with incompatible capacity therefore fails on the first out-of-range/card read, while identical authorized bytes on another card are not a substitution. Missing, stale, wrong-purpose, corrupt, power-cycled, or geometrically inconsistent records fail closed without SD access or application writes. Both ordinary format-2 SD application updates and format-3 SD bootloader updates require this authorization, so a removable card/controller cannot swap authenticated container A for self-consistent container B across reset. The format-3 path additionally retains the `MOTASDBL` internal-flash payload token at `0xE0000` as defense in depth before scratch compaction.

- **Machine-bound bootloader compatibility and monotonic versions**
  Every new 40 KiB raw bootloader ends with an authoritative 76-byte envelope at raw offset `0x9FB4` (`0xFDFB4` in flash). Bytes 0..43 remain the preview.12-compatible `BLMF` record and whole-image CRC; adjacent bytes 44..75 are `BLM2`/`SOFT` v2 metadata containing the true packed boot version, SoftDevice family/FWID, application base, layout ABI, zero compatibility flags, and zero reserved bytes. Linker assertions fix this envelope at the image end and prevent the 88-byte CF2 configuration from overlapping it. Remote bootloader updates require the signed outer version to equal the embedded version, exact runtime/installed SoftDevice and layout compatibility, and a version strictly newer than the installed v2 bootloader. The running bootloader reads the installed FWID with Nordic's required `SD_FWID_GET(MBR_SIZE)` base; using a zero base reads `0x200C` rather than the actual SoftDevice information field at `0x300C`. There is no signed remote rollback/migration flag; incompatible recovery remains an explicit local USB/BLE/SWD operation.

  Released images are board-bound and must not be modified afterward with the generic CF2 patcher. Any CF2 mutation invalidates the whole-image CRC, and expanding the record can overwrite the fixed envelope. `tools/otafix_cf2.py IMAGE` is the supported read-only inspector and refuses protected mutation before invoking the bundled tool; direct bundled-patcher writes are unsupported. Board configuration changes belong in `pinconfig.c` before rebuilding and repatching the manifest CRC.

  Release versions are derived only from an exact canonical `OTAFIXX.Y.Z-preview.N` tag (`X<<24|Y<<16|Z<<8|N`, `N=1..254`) or stable `OTAFIXX.Y.Z` (`...|0xFF`). Dirty, git-distance, untagged, zero-channel, and all-ones versions fail the build. An explicit test-only override requires test-build mode and brands the build string; such artifacts are never release or live-flash candidates.

## Changes in OTAFIX 2.4.1 preview.11

- **Internal-flash, application-preserving bootloader self-update**
  Eligible internal-only nRF52840 targets can install an exact-board raw 40 KiB bootloader image without replacing the running application. This path is nRF52840-only: smaller nRF52 flash geometries cannot provide the 11-page shared window needed to hold the exact 41,330-byte package and then its 40 KiB raw form while retaining a usable application, and the build rejects other MCUs. Internal targets use the transport-neutral storage flags `0x0A` (`STAGE_CEILING|BOOT_UPDATE`) and the normal expanded handoff `GPREGRET2=0xED`; absence of the SD/QSPI bits means internal staging. Their signed hardware identity is the exact 32-byte NUL-padded field `NRF_BL_%08X_<DEVICE_NAME>`, and the package target is the little-endian first 32 bits of SHA-256 over that complete field. The embedded bootloader manifest must still match the installed board ID and all 16 device-name bytes exactly. Format 3 deliberately makes older/v2 application installers reject a bootloader package instead of treating its payload as an application.

  Application deltas and bootloader packages mutually exclusively reuse the normal internal window below `0xED000`; there is no second reserved raw-image bank. `GPREGRET=0x6A` selects an ordinary format-2 application delta, bottom-aligned dynamically below `0xED000`, and detools workspace ends at the actual container start. `GPREGRET=0x6B` selects the exact format-3 bootloader package. Its fixed 41,330-byte geometry bottom-aligns at `0xE2000`; the 40 KiB payload begins 365 bytes later. The bootloader reads each complete source page before erasing the lower destination page, compacting the payload forward in place to the page-aligned MBR source `0xE2000..0xEC000`. It independently requires a hash-valid live `EndF`, inclusive application end at or below `0xE2000`, and exact package geometry before the first compaction erase.

  The running application authenticates the package signature and writes `APRV`; the bootloader rechecks the source, target/identity/geometry, vector table, complete payload SHA-256, board-bound embedded manifest/CRC, and exactly one valid incoming `MOTABLDR` continuity marker before modifying the slot. It consumes the trigger and clears approval first, verifies every compacted page, the complete raw SHA-256, and the embedded metadata again, then asks the Nordic MBR to replace the bootloader. A reset before MBR can damage only the staged package: the application and installed bootloader remain byte-identical, and the consumed trigger prevents retry. Retained results are: `C1` gate entered, `C2` source/container/approval missing, `C3` package policy, identity, or live-app boundary rejected, `C4` vectors/payload integrity rejected, `C5` embedded manifest/CRC or continuity capability rejected, `C6` approval clear failed, `C7` in-place compaction/readback failed, `C8` MBR handoff has begun, and `C9` MBR unexpectedly returned.

  This shared-slot LoRa path is separate from legacy/manual bootloader UF2 reception, whose Nordic-defined fixed staging address remains `0xE0000`. On an internal-update build, manual UF2 now refuses before its first staging erase when a valid application's hash-bound `EndF` extends into that fixed range. Recovery with no valid application remains available. Thus the LoRa feature does not falsely make legacy UF2 staging application-preserving for larger applications.

  Internal bootloader updates are enabled only for nRF52840 targets whose Make and CMake definitions prove the fixed layout and do not enable SD or QSPI storage: GAT562, Heltec Mesh Pocket, MeshTower V2, T096, T1, T114, Keepteen LT1, MinewSemi MX25LE01, ProMicro nRF52840, T1000-E, ThinkNode M3, RAK3401, ordinary RAK4631, and WisMesh Tag. `tools/check_internal_bootloader_targets.py` validates the inventory, canonical identities, and derived-target collision freedom. The non-watch GAT562 carriers covered by the `gat562` target do not populate a QSPI NOR device; the 30S Kit's QSPI-capable pins are used as GPIO. GAT562 Mesh Watch 13 is excluded because it has a populated W25Q16JV. Boards with populated onboard flash are deliberately not switched to internal staging: Mesh Solar (MX25R1635F), Nano G2 Ultra (W25Q16JV), T-Impulse+ (MX25R6435F), ThinkNode M8 (MX25R1635F), T-Echo Lite/Card (ZD25WQ32CEIGR; some Lite revisions use MX25R1635F), and MeshTracker X1 (GD25Q64C/WM1110). Use the QSPI path where an exact OTAFIX target is available; otherwise these boards remain excluded from application-preserving bootloader updates until one is provided and verified.

- **MeshTower V2 microSD bootloader self-update**
  The exact `heltec_mesh_tower_v2_sdcard` target can accept signed format-3 bootloader packages from the contiguous raw-sector SD run named by the retained-RAM authorization above. Its identity is board ID `0x239A0071`, device name `TOWER_V2_OTA`, hardware ID `NRF_BL_239A0071_TOWER_V2_OTA`, and package target `0x1150F50E`. The installed and candidate `MOTABLDR` capability profile is exactly `0x09` (`SD|BOOT_UPDATE`), and bootloader apply uses the distinct `GPREGRET2=0x53` source marker. The LoRa packet type remains `0x0C`.

  This target does not reserve scratch in its linker layout, and ordinary SD full images and deltas retain the normal application limit at `0xED000`. Before any scratch erase, the bootloader independently finds the first hash-valid live `EndF`, requires its inclusive end to be at or below `0xE0000`, and recomputes the body hash stored in that trailer. If a valid bootloader setting has a nonzero application CRC, its complete recorded bank must also fit below `0xE0000`; an early valid EndF cannot hide CRC-covered trailing bytes. A missing, oversized, or hash-invalid live image fails with the application and installed bootloader untouched. It then copies the raw 40 KiB candidate to `0xE0000..0xEA000`, verifies each page, the complete SHA-256, the exact embedded board manifest/CRC, and a successor marker retaining both full and in-place codecs before asking the Nordic MBR to copy it.

  Removable-media approval is bound first by the consumed `MOTASDA2` retained-RAM record and then, for bootloader payloads, by a checksummed 64-byte internal-flash token containing the full 32-byte `image_hash` from the exact signed manifest buffer. OTAFIX requires the retained container hash, token hash, parsed manifest hash, staged payload SHA-256, and final scratch SHA-256 to agree. Therefore switching the card or file between any reads cannot authorize different bytes. Copying raw page zero consumes the flash token. The read-only SD backend still leaves the signed file and `APRV` bytes on the card, but both the retained-RAM authorization and `GPREGRET=0x6B` are consumed before validation or scratch work. A normal reset cannot retry an interrupted copy; a running application may deliberately recompute a fresh authorization and re-arm only after authenticating a new update command. This differs from QSPI/internal staging, where approval can be cleared in place.

## Changes in OTAFIX 2.4.1 preview.10

- **LoRa-delivered XIAO bootloader self-update**
  The `xiao_nrf52840_ble` and `xiao_nrf52840_ble_sense` targets can install an exact-board raw 40 KiB bootloader image from their onboard QSPI OTA store without modifying the application. Bootloader packages use the fixed-layout `.mota` manifest with `format_ver=3`, exact `FULL|SIGNED|BOOTLOADER` flags, a nonzero firmware version, full codec, SHA-256, 1024-byte blocks, zero `base_hash`, and the exact NUL-padded identity `XIAO_BL_28860044` or `XIAO_BL_28860045`. Format 3 deliberately makes older/v2 application installers reject the package instead of treating its payload as an application.

  The running application authenticates the package signature and writes `APRV`; the bootloader then requires the signed-package policy marker, exact QSPI handoff, target/identity/geometry, vector table, complete payload SHA-256, board-bound embedded manifest/CRC, and an incoming `MOTABLDR` marker that preserves ABI 3 plus QSPI bootloader-update capability. It copies the image pagewise to the reserved internal scratch range `0xE0000..0xEA000`, verifies every write and the complete scratch image, powers down QSPI, and only then asks the Nordic MBR to replace the bootloader. The app and old bootloader remain bootable through every pre-MBR failure or reset. Because that scratch range is reserved, these capable XIAO builds also cap ordinary full/delta application writes below `0xE0000`; other boards retain their existing limit.

  The trigger is `GPREGRET=0x6B` with QSPI handoff `GPREGRET2=0x51`. Retained results are: `C1` gate entered, `C2` source/container/approval missing, `C3` package policy or identity rejected, `C4` vectors/payload integrity rejected, `C5` embedded manifest/CRC or continuity capability rejected, `C6` approval clear failed, `C7` scratch copy/readback failed, `C8` QSPI is released and MBR handoff has begun, and `C9` MBR unexpectedly returned. A normal post-update boot preserves `C8` (or the failure code) for the application to report.

- **Bootloader vector validation**
  Both UF2 and LoRa bootloader-update paths now require an aligned initial stack pointer in nRF RAM and a Thumb reset handler inside the exact bootloader region before accepting an image.

## Changes in OTAFIX 2.4.1 preview.9

- **Persistent MeshCore OTA apply result**
  A normal boot after an OTA apply no longer replaces the retained `GPREGRET2` success or failure code with a pre-gate diagnostic. This preserves `0xB8` success and failure details long enough for the application to report the actual bootloader result.

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

- **Clean reboot after application DFU**
  A successfully installed BLE, serial, or UF2 application now starts after a hardware reset, ensuring clean SoftDevice, radio, USB, and peripheral state. Interrupted updates still re-enter recovery DFU.

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
  The `heltec_mesh_tower_v2_sdcard` target reads the authenticated contiguous sector run named by retained RAM from the onboard microSD socket and applies either a full MeshCore `.mota` image or an in-place delta. The card holds the download, while application writes remain bounded below InternalFS at `0xED000`. Build it with `make BOARD=heltec_mesh_tower_v2_sdcard`; it must be paired with MeshCore's SD-card firmware target.

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
  - **Heltec Mesh Pocket** -> `MESH_POCKET_OTA`
  - **Heltec MeshTower V2 / V2H** -> `TOWER_V2_OTA`
  - **Keepteen LT1** -> `KeepteenLT1_OTA`
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
- MTools Tec GAT562 family (30S Kit, Mesh Tracker Pro, EVB Pro / 30S Pod, and Solar Relay)
- Elecrow ThinkNode M1
- Elecrow ThinkNode M3
- Elecrow ThinkNode M6
- Heltec Automation Mesh Node T114 / HT-nRF5262
- Heltec Automation Mesh Node T096 / HT-n5262G
- Heltec Automation Mesh Node T1
- Heltec Automation Mesh Pocket
- Heltec Automation MeshTower V2 / V2H
- Keepteen LT1
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
Download the UF2 file for your board (they can be found in the releases with filenames beginning with `update-` and ending in `_mbr.uf2`), enter UF2 mode (usually by double pressing the reset button within 0.5s) and copy the UF2 file across. The `_mbr` artifact contains the MBR and bootloader; internal, SD-card, and QSPI apply support are determined by the exact board target. Packages ending in `_s140_<version>.zip` additionally contain the SoftDevice.

See the [OTAFIX releases](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases) and use a release whose notes explicitly list your exact board and required internal, SD, or QSPI apply mode.

Self-update-capable MeshCore targets can use the signed full bootloader `.mota`
bundle attached to current releases. Trust the official public key once, then
run the menu-driven `tools/otafix_mota_update.py` release checker/updater or use
MeshCore's explicit bootloader installation commands. See
[mOTA signing and custom keys](docs/mota_signing.md) for the official key,
menu and radio options, estimated transfer times, exact-board safety rules, and
instructions for signing a custom OTAFIX variant.

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
exact board and QSPI mode. XIAO QSPI bootloader `.mota` updates require preview.10 or newer; generic
internal-flash bootloader updates require preview.11 or newer. Both require a matching MeshCore build
with the exact storage/identity profile.

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
- On current builds, removing VBUS from an enumerated no-application USB session exits that session and resets into BLE recovery; no reset-button press is required.

Preview.7 offers USB only briefly before falling back to BLE. Other older OTAFIX builds may fall directly
to BLE. On those versions, a host or VM that attaches too slowly can miss the USB window even though the
cable supplies power.

**What to do:**
- On preview.8 or newer, connect the device to a computer with a data-capable USB cable and wait for the UF2 drive or serial port, **or** perform an OTA update using a supported DFU app.
- On preview.7 or older releases, explicitly request UF2/serial mode using **double-reset**, or perform a BLE OTA update.

This behavior keeps computer-based recovery available without leaving battery-powered devices stuck waiting for USB.

---

### Manual bootloader handoff and hard recovery

A Legacy DFU bootloader or SoftDevice-plus-bootloader update has two distinct
handoffs. The MBR first copies the replacement bootloader and starts it
directly. The replacement then finalizes the pending bank and performs one
intentional hardware reset before starting USB, BLE, or direct flash work.
It clears the prior transport's retained BLE-entry request before that reset.
During that sequence the USB drive and serial port may disappear and
re-enumerate. Wait for the second enumeration, then confirm the exact model and
board ID in `INFO_UF2.TXT` before copying application firmware.

A bootloader-only Legacy DFU package uses the application bank as temporary
storage and is not application-preserving. Reinstall the exact board's
application after the bootloader is stable. The signed internal, SD, and QSPI
bootloader-update paths described above use their own guarded staging layouts
and have different preservation guarantees.

For a device that shows as an unknown USB device, has no serial port, or does
not expose its UF2 drive:

1. Remove USB and every other power source, including the battery, for at least
   five seconds. A VM-side USB detach is not a hardware power cycle.
2. Reconnect with a known data cable, wait through the recovery window, and use
   the board's double-reset gesture if necessary.
3. If serial DFU is available, install only the exact-board combined package:

   ```bash
   adafruit-nrfutil dfu serial -pkg <exact-board-s140-package.zip> \
     -p <serial-port> -b 115200 -sb
   ```

4. If the device remains an unknown USB device and does not advertise BLE DFU
   after a true power cycle, use SWD. This erases the application and ExtraFS:

   ```bash
   nrfjprog --family NRF52 --recover
   nrfjprog --family NRF52 --program <matching-s140-softdevice.hex> --verify --sectorerase
   nrfjprog --family NRF52 --program <exact-board-bootloader_mbr.hex> --verify --sectorerase
   nrfjprog --family NRF52 --reset
   ```

Do not substitute a similarly named board or rely on a changing drive letter.
Resolve the USB serial number and verify the board-bound package before every
write.

BLE scanners should select the Legacy DFU service UUID, not depend on the full
advertised name. OTAFIX reserves the UUID before adding the local name to the
31-byte legacy advertising payload. Flags, UUID, and field overhead leave eight
name bytes, so longer names use the BLE shortened-name type; connect and read
board metadata before writing firmware. Older bootloaders that advertised a
long name before the UUID could silently omit the UUID and may require an exact
MAC or MAC+1 filter for recovery.

If USB enumeration works but serial DFU never acknowledges START and copied
application UF2 files do not change flash, do not replace only
`dcd_nrf5x.c` with a newer TinyUSB version. The newer Nordic atomic-EasyDMA
driver depends on its matching TinyUSB core; a partial backport onto this
repository's vendored TinyUSB 0.12 stack can lose host-to-device completion
handling even though a USB capture shows successful bulk OUT transactions.
Upgrade the TinyUSB core and controller driver together. OTAFIX keeps the
compatible vendored driver and pins a minimal backport of upstream TinyUSB
commit `6af4ee2c5` for the independent post-SoftDevice HFCLK retry. The
`mikecarper/tinyusb` fork's `otafix-0.12-nrf5x` branch contains the two nRF5x
controller fixes on the pinned TinyUSB 0.12-era base plus an MSC-local deferred
WRITE10 retry used by this bootloader's flash-erasure state machine. The generic
TinyUSB task retains its upstream drain-to-empty behavior. This keeps the
backport reproducible from a clean clone without unrelated core changes.

If the first valid UF2 flash sector instead makes an older bootloader reset,
while ordinary non-UF2 disk traffic remains stable, the recovery path may have
entered USB with the SoftDevice still enabled. Direct NVMC access is forbidden
in that state. Current builds explicitly disable the SoftDevice before TinyUSB
startup and use the hardware-proven complete-page erase; install the corrected
bootloader over BLE or SWD before retrying application UF2. A bootloader-only Legacy DFU update
uses the first 40 KiB of the application bank as staging, so reinstall the
exact application afterward.

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
