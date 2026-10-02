# MeshTower V2 combined SD/internal bootloader

Combined SD/internal implementation, merged into `feature/ota-delta-apply`
for the MeshTower 2.4.11 asset refresh. The original hardware qualification
and the subsequent merged-tree checks are distinguished below.

## Default and migration

`heltec_mesh_tower_v2_sdcard` is the default combined profile. It retains the
existing SD `TOWER_V2_OTA` identity, board ID `239A0071`, derived boot target
`1150F50E`, S140 6.1.1/FWID `00B6`, application base `0x26000`, and primary
`MOTABLDR` storage flags `0x09`. A validated adjacent `MOTARAMA`/`MOTASTOR`
record adds optional internal staging (`0x02`). It does not replace the primary
SD update contract with `0x0B`.

| Installed profile | Path to the combined default |
| --- | --- |
| BLM2/self-update-capable Tower SD (`0x09`) | Signed newer combined bootloader over the existing SD OTA path; then compatible MeshCore firmware |
| Legacy SD without authenticated retained handoff/BLM2 | Local USB/BLE DFU or SWD first |
| Tower internal-only (`0x0A`) | One-time local USB/BLE DFU or SWD migration; install matching combined/SD MeshCore firmware |
| Combined SD/internal | Signed newer combined successor using the selected store |

The internal-only target remains buildable for existing deployments. Exact
storage-profile checks intentionally reject cross-profile bootloader OTA, even
though the board name and target ID match. Combined successors must retain
both their SD profile and validated optional internal capability.

The SD-card update path does not require an `R_` recovery image or recovery
bridge. An existing authenticated SD self-update bootloader accepts the normal
combined SD-profile package directly. The optional recovery download is not an
installation prerequisite for SD users. Older bootloaders without that update
protocol need a local installation of the normal image, not a recovery detour.

## Application control

Matching MeshCore target:
`Heltec_tower_v2_sdcard_repeater_lora_ota_no_external_sensors`.
SD defaults on for a genuinely absent setting. `set sdcard off` or
`set sdcard on`, followed by a reboot, selects the backend. `get sdcard status`
and `ota sd` (alias `ota storage`) report both active and saved values. The CRC-protected setting is
stored in internal LittleFS, not on the card. A malformed setting or filesystem
error selects off. Changing the saved value never changes an in-flight transfer.

Off disables card access and the archive. It uses internal-flash application
deltas and signed internal-staged bootloader packages. On supports SD full and
delta application images, signed bootloader packages, and the persistent archive.
There is no fallback from a failed SD operation to a stale internal package.
`ota cache off` remains a separate archive-capture switch; it does not disable SD.

The combined bootloader keeps its stack below the existing 64 KiB retained
arena and understands the hybrid handoff. The default combined MC
application deliberately retains the full-RAM SD linker, 254 neighbours, and
254 archive entries: its internal mode is **flash-only**, without a 64 KiB RAM
staging reservation. A delta must fit both its staging slot and the in-place
workspace; a package built for the full SD workspace may not fit internal mode.

## Safety and geometry

The reset source selects one backend explicitly. Signature approval, whole
container/payload hashes, board/profile/SoftDevice continuity, vectors, live
application headroom, boot settings, and programmed-image readback checks remain.
SD boot replacement uses `0xE0000..0xEA000` scratch; internal staging uses the
shared region starting at `0xE2000` below `0xED000`. Both reject overlapping live
applications before erasing. SD approval is one-reset-only and bound to the
authenticated card geometry and normalized container hash.

## Original qualification snapshot

ARM GCC 14.2.1, explicit test version `0x02040B01`:

- Combined image: `.text` 40,571 + `.data` 168 = **40,739 / 40,784 bytes**;
  **45 bytes spare** before the fixed CF2 region. Padded boot region: 40,960 bytes.
- USB/UF2, existing BLE DFU, identity/SoftDevice text, and both update backends
  are retained. `-fno-caller-saves` is scoped to the combined board in both builds.
- Combined SD/internal application and bootloader host suites pass.
- The actual BIN is signed with an ephemeral test key and accepted by both the
  existing SD-profile and combined SD-profile host validators.
- T096 and T114 builds and the bootloader C regression executables pass.
- The ten release-inventory tests pass from a source-file snapshot, including
  exact-board and Make/CMake agreement for the combined profile. The working
  directory still contains an unused empty `src/boards/heltec_mesh_tower_v2_dual`
  directory from an earlier prototype; it is not part of Git and was excluded
  from that snapshot.

At the original qualification, the entire `make check` suite had not completed: that host's WSL Python 3.10
lacks `asyncio.timeout` needed by the uploader test, and WSL lacks CMake for a
separate secure-DFU target test. These are local test-environment limitations,
not passing results. The targeted combined-storage tests above completed.

This original snapshot used qualification builds, not production artifacts.
Its package tests used the matching MeshCore Python package builder and an
ephemeral key; no production signing key was used.

## Merged-tree 2.4.11 qualification

After merging the current 2.4.11 Bluetooth reset fallback, Windows ARM GCC
14.2 CMake builds pass for the combined Tower, internal-only Tower, T096 and
T114, both normal and recovery. At explicit test version `0x02040B03`, the
combined normal image uses 40,755 / 40,784 bytes (29 spare); recovery uses
40,578 bytes (206 spare). These are qualification sizes, not clean-tag sizes.

The complete Linux `make -C test check` and `make -C test sanitize` suites
pass from an isolated merged-source checkout, with the required ARM DFU
emulator enabled. This supersedes the original WSL environment limitation.
The packaging pin is now `mikecarper/motatool` at `9a9b9a4`, accepting only
the exact qualified Tower optional-storage record and retaining the existing
RAK restrictions. Its full Rust tests pass, including malformed, duplicate,
cross-board, storage-profile and RAM-boundary checks.

The refresh uses a new source tag, `0.11.0-OTAFIX2.4.11`, without moving the
existing `v0.11.0-OTAFIX2.4.11` release tag. Only affected Tower assets and
their bundle inventories/checksums are replaced; unaffected firmware keeps
its original bytes and provenance. Exact production verification is recorded
with the refreshed release assets.

Run the targeted checks from `test/`:

```sh
make check-tower-dual
python3 tower_dual_image_test.py --meshcore /path/to/MeshCore \
  --image ../cmake-build-meshtower-dual/combined-sd/bootloader.bin
```

Physical tests completed on 2026-09-29 Pacific, using the MercerwoodMesh Pi's
MeshTower V2 with its 1 GB card (USB serial `9352162A72082314`) through VMware.
The LoRa source was the T096 Companion (`651F8E496197F882`). All application
and bootloader images below travelled over LoRa; USB was console-only.

| Transition | Store | Package bytes | Installed result |
| --- | --- | ---: | --- |
| SD-only OTAFIX 2.4.8 to combined 2.4.11-preview.1 | SD | 41,330 | CRC `03FF791F`, `blup:C8` |
| Existing application to test A, full | SD | 546,726 | Body `1B75ADE42ECA6805`, `blrc:B8` |
| Test A to B, delta | SD | 2,428 | Body `14A19875921931A2`, `blrc:B8` |
| Test B to A, delta | Internal; SD off | 2,428 | Body `1B75ADE42ECA6805`, `blrc:B8` |
| Test A to corrected test C, delta | Internal; SD off | 45,649 | Body `B3BCBBB5038BC7E1`, `blrc:B8` |
| Combined preview.1 to preview.2 | Internal; SD off | 41,330 | CRC `4D0E9C55`, `blup:C8`; app unchanged |

SD-off persisted across reboots and both types of update. Card queries,
formatting, and archive access were refused while off. The `ota storage`
alias was exercised both ways. Saving on kept access disabled until reboot,
then restored SD selection and card access (959.6 MiB free). Test C is
`v1.17.1.9-tower-dual-test-c`, not a production release.
At the end of that run the Tower was on that test application and combined preview.2 with SD on.
Temporary test keys were removed and the original three trusted keys retained.
Both radios' original radio/power settings were restored, and the sender is
stopped (`folder:not connected`, `serving:0`).

The Pi unexpectedly restarted during one download, before installation. The
Tower returned with its existing application/bootloader and SD-off setting
intact; the incomplete download was restarted. Physical card-removal and
power-loss-during-install tests remain unperformed; the fault/power-cut tests
listed above are host tests. Discovery/transfer occasionally required a source
refresh; the full SD transfer took about 45 minutes, not a throughput benchmark.

Physical evidence is in
`/home/mikec/hwtest/runs/tower-dual-20260929-9352162a/events.jsonl` on the Pi.
Verify the exact serial before any further write. Do not power-cycle the Pi's
ganged root USB hub.
