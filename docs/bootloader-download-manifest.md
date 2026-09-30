# Bootloader download manifest

Every normal release publishes `bootloader-manifest.json` and its SHA-256
sidecar. This is download metadata, not the Nordic DFU manifest inside each
DFU ZIP. It does not change or rebuild the bootloader binaries.

The schema includes the exact release tag/version and URL, each normal board
profile's identity and storage backend, explicit MeshCore hardware names,
and the individual UF2, DFU ZIP and SWD HEX file names, URLs, sizes and SHA-256
hashes. File data comes from actual uploaded GitHub assets. A missing file,
duplicate match, absent hash or ambiguous hardware mapping fails generation.
Recovery bridges and experimental feature builds are not normal downloads.

`docs/bootloader_profiles.json` owns the explicit hardware aliases. The
generator checks that it covers every normal profile in
`build_bootloader_mota_release.py`. Do not add a similarly named board without
verifying its physical bootloader compatibility. A hardware name absent from
the mapping has no automatic download recommendation.

The [MeshCore hardware audit](meshcore-hardware-coverage.md) records carrier
aliases, physical pin differences and genuine gaps in released coverage.
Optional `unavailableProfiles` describe boards without a released download;
each has an ID, label, hardware names and reason, but no files. Their aliases
must be unique across both lists. Source ports marked
`OTAFIX_BOARD_QUALIFICATION_PENDING ON` build in CI but stay outside normal
releases until hardware qualification. A new board name alone does not justify
a new bootloader variant.

The MeshCore web picker mirrors the release manifest during each Pages build
and checks the latest stable GitHub release at runtime. It resolves exact
assets for the same explicitly mapped profiles, so a new stable version can
provide current individual file links immediately. Offline pickers embed the
manifest and identify the included bootloader version. RAK3401 and RAK4631
map to their normal adaptive `*_auto` profiles; MeshTower internal and microSD
map to separate profiles. Old RAK identities still need the documented
recovery bridge before installing a normal compatible image.

To add metadata to an existing release without rebuilding its binaries:

```bash
gh api repos/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tags/TAG > release.json
python3 tools/build_bootloader_download_manifest.py --release-json release.json --output bootloader-manifest.json
gh release upload TAG --repo mikecarper/Adafruit_nRF52_Bootloader_OTAFIX --clobber bootloader-manifest.json bootloader-manifest.json.sha256
```

Future release builds generate and upload this metadata after the normal
assets have been published. Consumers should verify the manifest checksum,
display its exact version, and follow the release's migration instructions.
