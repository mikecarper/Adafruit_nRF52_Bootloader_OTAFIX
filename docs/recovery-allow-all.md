# Allow-all board recovery release

These are temporary **recovery bridges**, not normal bootloader upgrades.
`RECOVERY_ALLOW_ALL_BOARDS=1` permits arbitrary manual bootloader installs
over Legacy serial/BLE DFU and bootloader-family UF2. It is available for every
board profile; each profile still supports only its normal transports.

Use `OTAFIX-2.4.12-R_recovery.zip` from the
[current 2.4.12 release](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/v0.11.0-OTAFIX2.4.12).
It contains 28 recovery profiles with inventory and checksums. Nine pending
source ports and the historical internal-only Tower profile remain excluded.
It includes the narrow Bluetooth handoff fault fallback for older MeshCore
applications and the current USB fixes. The separate signed bootloader mOTA
bundle remains board-protected; no Open kit or automatic settings erase is
included. See the [2.4.12 release notes](release-2.4.12.md) for hardware limits,
including unperformed physical RAK15002/NOR power-cut qualification.

The [historical 2.4.11 correction](release-2.4.11-recovery-correction.md)
records a RAK4631 Bluetooth application update through Nordic nRF Connect
4.24.3 and MeshCore Open 9.5.5, starting from application 1.17.1.7. Its radio
tuple and seven compared settings were preserved. That report describes
qualification images and the historical source-only rebuild tags; use the
2.4.12 archive for current recovery.

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

The original 2.4.10 recovery archive predates this policy change and rejects
the manifest-free 2.3 ZIP. Use the current 2.4.12 bridge before a direct
downgrade; repackaging old binaries does not add the new behavior.

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
erase is added. Verify the 2.4.12 packed version (`0x02040CFF`) and installed
manifest CRC against the selected recovery profile's inventory.

Confirm the physical board manually. Allow-all means the bridge can accept the
wrong board again. Do not leave it installed for normal use. Back up settings
where possible and plan for application/settings loss during recovery.

For standard `3401_DFU` / `4631_DFU` devices, the normal 2.4.12 `*_auto`
image preserves the installed identity. Use its ordinary signed bootloader
`.mota` or matching local updater directly; no recovery bridge is needed.
For historical `3401_AUTO_DFU` / `4631_AUTO_DFU` devices, the recovery `*_auto`
images deliberately keep those old names. Install that temporary local bridge,
then the normal compatible image. Dedicated external RAK identities also retain
their matching bridges inside this archive.

The adaptive recovery images accept signed bootloader `.mota` packages for
their exact historical `*_AUTO_DFU` identities. Matching recovery packages
update only an already installed recovery bridge. They do not migrate to the
normal `*_DFU` identity; complete that transition with the local updater above.
The historical [2.4.10 release notes](release-2.4.10.md) record the earlier
in-place adaptive-archive repair and its separate source provenance.

## Linux build

Use the board-qualified Arm GNU releases in `tools/compiler_policy.json` and
the Python prerequisites, including `adafruit-nrfutil`, `intelhex`, and
initialized submodules. The default Docker image includes both selected releases;
native hosts can set `ARM_GNU_TOOLCHAIN_14_2` and `ARM_GNU_TOOLCHAIN_15_3` to
their installation directories.

From an untagged or dirty development checkout:

```sh
python3 tools/build_all.py --recovery-allow-all-boards --test-version 0x02040C01 --jobs 4
```

This builds **every board**, including future profiles added under `src/boards`,
and collects packages in `_bin/recovery-allow-all/<board>/`. Intermediate builds
use `_build-recovery-allow-all/`, separate from normal builds. Recovery bootloader
names have a short `R_` prefix (UF2 updaters use `update-R_...`); board identity and
USB drive names intentionally remain unchanged. Do not upload leftover packages
from older builds; use a fresh checkout/build folder for release packaging.
On-device recovery text uses `R_` plus the packed version, for example
`R_0x02040C01`. Full Git descriptions, including dirty/test markers, remain in
package names without consuming scarce bootloader flash. SoftDevice identity
remains in the compatibility manifest and package metadata.

For one board:

```sh
make BOARD=gat562 RECOVERY_ALLOW_ALL_BOARDS=1 \
  MOTA_BOOTLOADER_TEST_BUILD=1 MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040C01 \
  all copy-artifact
```

CMake also supports `-DRECOVERY_ALLOW_ALL_BOARDS=ON`, with the same test-version
options as a normal qualification build. Use a separate build directory.
Its image filenames use `R_<board>_bootloader`.

## Separate recovery ZIP or release

The 2.4.12 release attaches `OTAFIX-2.4.12-R_recovery.zip` alongside the
separate signed bootloader mOTA ZIP. The recovery archive contains the 28
selected profiles under `boards/<board>/`, this guide, the hardware
qualification report, an inventory, and checksums. These remain temporary recovery-only images even
when attached to a stable normal release. Its two signed exact-identity RAK
recovery `.mota` packages do not belong in the normal bootloader mOTA bundle.
Build the images from a clean exact tag with the recovery flag; their filenames and on-device versions retain the `R_` prefix.

The Build workflow's `release_build` manual input produces production artifacts
from an exact tag without publishing, including both ZIPs. Verify those artifacts
before publishing the release. Untagged manual runs retain the test-only path.

For a standalone recovery prerelease instead, use a new, clean, exact tag
prefixed with `R_`, such as `R_v0.11.0-OTAFIX2.4.12`. Build it with the
recovery flag and omit `--test-version`. The packed compatibility version
comes from the base OTAFIX version; `R_` is a distribution/policy label.
Normal builds reject these tags without a test-version override.

The dedicated **Recovery allow-all boards** workflow can build standalone
recovery packages. A blank `release_tag` produces test artifacts only.
Production builds use no test-version override. Their inventory records the
source and distribution tag objects/commits, each installed manifest CRC and
artifact checksums. Recovery-only publication remains a non-latest prerelease;
the normal 2.4.12 release is the stable latest release.

Historical standalone 2.4.11 recovery assets included pending ports using
`--include-pending`. That is not the current normal-release archive policy.
The nine current pending profiles are excluded from the 2.4.12 normal and
recovery bundles. `thinknode_m8` also remains blocked because its factory USB
identity is unverified. The historical internal-only Tower profile is retired
from both bundles; use the normal combined profile and its documented local
migration, not a cross-profile LoRa update.

Creating a tag/release is a separate maintainer action. Building or committing
these changes does not publish anything. Qualify the two-step process on actual
hardware before distributing it as a tested recovery procedure.

The [RAK3401 hardware qualification](recovery-rak3401-hardware-20260912.md)
passed the two-step UF2 procedure, both GAT562/RAK3401 recovery bridges,
corruption rejection, and restoration of normal identity guards. Its transport,
board, and test-build limits are recorded in that report; it is not an all-board
or BLE/serial hardware qualification.
