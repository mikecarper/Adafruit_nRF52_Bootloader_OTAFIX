# OTAFIX 2.4.7-preview.1

Local test candidate based on Adafruit nRF52 bootloader 0.11.0. This is not a
published stable release. Canonical tag: `0.11.0-OTAFIX2.4.7-preview.1`;
packed bootloader version: `0x02040701`.

## Changes since 2.4.6

- Integrates the stable OTAFIX and mOTA upstream histories. Adafruit's
  `master` is already included; the integration preserves this fork's board
  identities, storage profiles, display implementation and update safeguards.
- Adds the tested Docker build environment with checksum-pinned Arm GNU
  14.2.Rel1, Make/CMake, CF2 tooling, and Legacy DFU/signing dependencies.
- Uses Debian 13's native sanitizer runtime for host tests, resolving the
  older container runtime's startup failure. The ARM firmware compiler stays
  at GCC 14.2.1.
- Adds Docker regression contracts, updates artifact CI actions and missing-
  artifact checks, and records recent hardware qualification and build notes.

There is no new bootloader logic change relative to the 2.4.6 source. This
candidate qualifies the integrated source history and reproducible toolchain
with a distinct test version. The 2.4.5 bonded BLE GATT fix, 2.4.4 application-
UF2 fix, and 2.4.6 retained-RAM handoff remain present.

## Test and recovery rules

- Match the exact board and storage profile. MeshTower V2 internal and SD-card
  artifacts are not interchangeable; neither are RAK3401 and RAK4631 images.
- The dedicated exact-board `update-..._mbr.uf2` updates the bootloader while
  preserving the application and node data when the installed layout permits
  that path. A combined SoftDevice+bootloader Legacy DFU ZIP can require an
  application restore; do not use it without an exact recovery artifact.
- A target on OTAFIX 2.4.3 must have its bootloader updated before copying a
  MeshCore application UF2 to its mounted drive.
- Version rollback remains supported within compatible layouts and capability
  profiles. Preserve a verified old bootloader and application before tests.
- Physical validation starts with the debug-wired RAK3401, then proceeds one
  board at a time. A successful build is not a physical update test.
- An ESP32 Heltec V4 cannot use an nRF52 bootloader. It may serve as a MeshCore
  test peer if its running firmware supports the required role; do not flash
  any OTAFIX HEX, UF2 or DFU ZIP to it.

Hardware outcomes, exact artifact hashes and timing measurements are recorded
separately after the runs. This candidate must not be described as hardware-
qualified until those gates have actually passed.
