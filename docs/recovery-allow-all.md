# Allow-all board recovery release

These are temporary **recovery bridges**, not normal bootloader upgrades.
`RECOVERY_ALLOW_ALL_BOARDS=1` permits manual cross-board bootloader installs
over Legacy serial/BLE DFU and bootloader-family UF2. It is available for every
board profile; each profile still supports only its normal transports.

The flag waives only the incoming bootloader manifest's VID/PID and `DEVICE_NAME`
equality check. It does not permit arbitrary binaries: manifest CRC, vectors,
image bounds, transfer validation, and existing SoftDevice/layout checks remain.
Legacy DFU signatures remain required when `SIGNED_FW=1`; UF2 retains its existing
unsigned policy. Remote authenticated `.mota` updates remain exact-board-bound.
This is not a universal image or a way to migrate between incompatible chips.
Legacy BLMF-only images retain their existing, more limited compatibility checks;
prefer a current BLM2 bootloader and its matching SoftDevice package.

## Two-step USB recovery

1. Identify the **currently installed bootloader**, not just the physical board.
   Install the recovery image for that installed identity. This preserves its
   identity so its existing strict guard can accept the bridge.
2. Re-enter the bootloader after it restarts. Install the **normal** bootloader
   for the actual physical board, with its matching SoftDevice when needed.
   Verify the expected identity after restarting before reinstalling application firmware.

For a physical RAK4631 displaying `GAT562BOOT` after installing GAT562 OTAFIX:
install the **gat562 recovery** bridge first, then the **normal
wiscore_rak4631_board** bootloader. The first step deliberately still identifies
as GAT562; only the second step should restore the RAK identity. Neither a host
script override nor erasing the application changes the installed bootloader's
identity checks. A successful host transfer alone does not prove activation.

Use the `update-..._mbr.uf2` bootloader updater on a working UF2 drive, or the
generated bootloader/SoftDevice `.zip` with a compatible Legacy DFU tool. UF2
does not replace the SoftDevice; its version must already match the target image.
Do not drag the merged `.hex` onto the drive or use an application erase package
as a bootloader replacement. The bridge does not repair a bootloader that cannot
start DFU, and hardware access may still be needed if USB recovery fails.

Confirm the physical board manually. Allow-all means the bridge can accept the
wrong board again. Do not leave it installed for normal use. Back up settings
where possible and plan for application/settings loss during recovery.

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
when attached to a stable normal release. They are never included in the normal
bootloader mOTA bundle. Build them from the same clean normal tag with the
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
workflow run produces test artifacts only. A release event for a recovery tag
uploads only recovery packages, these instructions, and checksums; it marks the
release as a prerelease and does not make it latest. The normal release workflow
skips recovery tags, and no recovery `.mota` bundles are published.

Creating a tag/release is a separate maintainer action. Building or committing
these changes does not publish anything. Qualify the two-step process on actual
hardware before distributing it as a tested recovery procedure.

The [RAK3401 hardware qualification](recovery-rak3401-hardware-20260912.md)
passed the two-step UF2 procedure, both GAT562/RAK3401 recovery bridges,
corruption rejection, and restoration of normal identity guards. Its transport,
board, and test-build limits are recorded in that report; it is not an all-board
or BLE/serial hardware qualification.
