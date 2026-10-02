# Allow-all board recovery release

These are temporary **recovery bridges**, not normal bootloader upgrades.
`RECOVERY_ALLOW_ALL_BOARDS=1` permits arbitrary manual bootloader installs
over Legacy serial/BLE DFU and bootloader-family UF2. It is available for every
board profile; each profile still supports only its normal transports.

The planned [2.4.12 recovery correction](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/blob/feature/ota-delta-apply/docs/release-2.4.12-recovery.md) adds a narrow
Bluetooth handoff fault fallback for older MeshCore applications. Its release
tag will be `R_0.11.0-OTAFIX2.4.12`; publication awaits the remaining physical
test. The normal latest release remains 2.4.10.
It includes the local recovery packages without an Open kit or signed
bootloader mOTA bundle. Existing mOTA features remain enabled.

New recovery builds ignore the incoming bootloader's board, name, version,
BLMF/BLM2 manifest, manifest CRC and layout declarations. They accept older
manifest-free binaries and shorter word-aligned bootloader images, including
the original 39,000-byte RAK4631 OTAFIX 2.3 ZIP, without a host wrapper.
Flash-region bounds and startup vectors for the chip remain checked. An
included SoftDevice must still pass the chip-family, vector and size checks;
an SD-only reinstall retains its runtime-layout check. Legacy DFU packet CRC
and signatures when `SIGNED_FW=1` remain required. UF2 retains its framing,
address and transfer-completion checks. Remote signed `.mota` updates still
require their exact board identity, whole-image CRC and layout metadata.

The previously published 2.4.10 recovery archive predates this policy change
and rejects the original manifest-free 2.3 ZIP. Rebuild the bridge with this
code before attempting the direct downgrade; repackaging old binaries does
not add the new behavior.

## Two-step USB recovery

1. Identify the **currently installed bootloader**, not just the physical board.
   Install the recovery image for that installed identity. This preserves its
   identity so its existing strict guard can accept the bridge.
2. Re-enter the bootloader after it restarts. Install the **normal** bootloader
   for the actual physical board, with its matching SoftDevice when needed.
   Verify the expected identity after restarting before reinstalling application firmware.

For a physical RAK4631 displaying `GAT562BOOT` after installing GAT562 OTAFIX:
install the **gat562 recovery** bridge first, then the **normal
wiscore_rak4631_auto** bootloader. The first step deliberately still identifies
as GAT562; only the second step should restore the RAK identity. Neither a host
script override nor erasing the application changes the installed bootloader's
identity checks. A successful host transfer alone does not prove activation.

Use the `update-..._mbr.uf2` bootloader updater on a working UF2 drive, or the
generated bootloader/SoftDevice `.zip` with a compatible Legacy DFU tool. UF2
does not replace the SoftDevice; its version must already match the target image.
Do not drag the merged `.hex` onto the drive or use an application erase package
as a bootloader replacement. The bridge does not repair a bootloader that cannot
start DFU, and hardware access may still be needed if USB recovery fails.

On RAK internal-update profiles, a valid application without a usable
hash-bound `EndF` record leaves the bootloader UF2 updater unable to prove
that fixed `0xE0000` staging flash is safe to erase. It refuses before staging;
this safety guard remains intact. Ordinary non-LoRa builds can also omit
this metadata even when their Bluetooth handoff is corrected. Use the
matching combined SoftDevice/bootloader DFU ZIP through a working serial/CDC
or Bluetooth DFU connection for that one-time bootstrap, then reinstall the
application. If buttonless entry itself fails, use the board's supported
hardware DFU entry. Verify the installed bootloader version after transfer;
a successful copy alone does not prove activation. No automatic filesystem
erase is added by the 2.4.12 correction.

Confirm the physical board manually. Allow-all means the bridge can accept the
wrong board again. Do not leave it installed for normal use. Back up settings
where possible and plan for application/settings loss during recovery.

For standard `3401_DFU` / `4631_DFU` devices, the next compatible `*_auto`
release preserves the installed identity. Use its ordinary signed bootloader
`.mota` or matching local updater directly; no recovery bridge is needed.
For historical `3401_AUTO_DFU` / `4631_AUTO_DFU` devices, the recovery `*_auto`
images deliberately keep those old names. Install that temporary local bridge,
then the normal compatible image. Dedicated external RAK identities also retain
their matching bridges inside this archive.

The two adaptive recovery images in the repaired 2.4.10 archive also accept
signed bootloader `.mota` packages over LoRa. Their packages must target the
exact historical `*_AUTO_DFU` identity and retain the internal bootloader
staging and optional application-storage capabilities. The recovery packages
in that repaired 2.4.10 archive update only a device already running the
matching recovery bridge. They do not migrate to the normal `*_DFU` identity; complete that
one-time transition with the local updater above.

For the in-place 2.4.10 repair, the two adaptive images were rebuilt from the
exact source-only tag `R_v0.11.0-OTAFIX2.4.10` at commit `ff7959c`.
The other 27 board images are unchanged. The archive manifest records the
source tag, both signed package identities, and every artifact checksum.
Host tests and package verification passed; these repaired images have not
been installed on physical boards as part of this repair.

## Linux build

Use the repository's Arm GNU 14.2.Rel1-or-newer toolchain and Python prerequisites,
including `adafruit-nrfutil`, `intelhex`, and initialized submodules.

From an untagged or dirty development checkout:

```sh
python3 tools/build_all.py --recovery-allow-all-boards --test-version 0x02040601 --jobs 4
```

This builds **every board**, including future profiles added under `src/boards`,
and collects packages in `_bin/recovery-allow-all/<board>/`. Intermediate builds
use `_build-recovery-allow-all/`, separate from normal builds. Recovery bootloader
names have a short `R_` prefix (UF2 updaters use `update-R_...`); board identity and
USB drive names intentionally remain unchanged. Do not upload leftover packages
from older builds; use a fresh checkout/build folder for release packaging.
On-device recovery text uses `R_` plus the packed version, for example
`R_0x02040601`. Full Git descriptions, including dirty/test markers, remain in
package names without consuming scarce bootloader flash. SoftDevice identity
remains in the compatibility manifest and package metadata.

For one board:

```sh
make BOARD=gat562 RECOVERY_ALLOW_ALL_BOARDS=1 \
  MOTA_BOOTLOADER_TEST_BUILD=1 MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040601 \
  all copy-artifact
```

CMake also supports `-DRECOVERY_ALLOW_ALL_BOARDS=ON`, with the same test-version
options as a normal qualification build. Use a separate build directory.
Its image filenames use `R_<board>_bootloader`.

## Separate recovery ZIP or release

Normal releases can attach `OTAFIX-<version>-R_recovery.zip` alongside the
separate signed bootloader mOTA ZIP. The recovery archive contains all board
profiles under `boards/<board>/`, this guide, the hardware qualification report,
an inventory, and checksums. These remain temporary recovery-only images even
when attached to a stable normal release. The repaired 2.4.10 archive carries
two signed exact-identity RAK recovery `.mota` packages; neither belongs in the
normal bootloader mOTA bundle. Build the images from a clean exact tag with the
recovery flag; their filenames and on-device versions retain the `R_` prefix.

The Build workflow's `release_build` manual input produces production artifacts
from an exact tag without publishing, including both ZIPs. Verify those artifacts
before publishing the release. Untagged manual runs retain the test-only path.

For a standalone recovery prerelease instead:

Use a **new, clean, exact tag** prefixed with `R_`, for example
`R_0.11.0-OTAFIX2.4.6`. Build that tag with the recovery flag and
omit `--test-version`. The packed compatibility version derives from the base
OTAFIX version; the `R_` prefix is a distribution/policy label, not a new ABI.
Normal builds reject these tags unless an explicit test-version override is used.

The dedicated **Recovery allow-all boards** workflow builds every board. A manual
workflow run with a blank `release_tag` produces test artifacts only. To rebuild
and repair an existing recovery prerelease using the current workflow, set
`release_tag` to its exact `R_` tag. This preserves the published source tag,
builds its exact source commit without test-version overrides, and uploads only
changed or missing assets sequentially. The release remains a non-latest
prerelease. A release event for a recovery tag
uploads only recovery packages, these instructions, and checksums; it marks the
release as a prerelease and does not make it latest. The normal release workflow
skips recovery tags. The repaired 2.4.10 archive is an in-place asset update,
not a separate recovery release.

The standalone 2.4.11 recovery release and planned 2.4.12 recovery release
include all 35 releasable board profiles.
Six included ports remain pending hardware qualification: `gat562_mesh_watch13`,
`lilygo_t_impulse_plus`, `lilygo_techo_card`, `meshtiny`, `muzi_base`,
and `nano_g2_ultra`. They are identified in the archive inventory
as `qualification_pending_boards`; inclusion does not establish hardware support.
The archive builder's explicit `--include-pending` option includes these ports.
Normal release bundles continue to exclude them.
The 36th source profile, `thinknode_m8`, remains compile-only because its factory
USB identity is not verified; it is recorded under `excluded_boards` and has no
published recovery image. For a local production build, explicitly supply
`--exclude-board thinknode_m8` to `tools/build_all.py`.

Creating a tag/release is a separate maintainer action. Building or committing
these changes does not publish anything. Qualify the two-step process on actual
hardware before distributing it as a tested recovery procedure.

The [RAK3401 hardware qualification](recovery-rak3401-hardware-20260912.md)
passed the two-step UF2 procedure, both GAT562/RAK3401 recovery bridges,
corruption rejection, and restoration of normal identity guards. Its transport,
board, and test-build limits are recorded in that report; it is not an all-board
or BLE/serial hardware qualification.
