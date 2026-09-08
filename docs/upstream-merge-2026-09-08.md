# Upstream bootloader integration - 2026-09-08

Integration branch: `feature/ota-delta-apply` in
`mikecarper/Adafruit_nRF52_Bootloader_OTAFIX`, starting at the published
2.4.6 source commit `250559c`.

| Source | Integrated branch/tip | Result |
| --- | --- | --- |
| OTAFIX: `oltaco/Adafruit_nRF52_Bootloader_OTAFIX` | `master`, `3a75482` | Merged 11 outstanding commits, including support already ported into this fork. |
| mOTA: `vk496/Adafruit_nRF52_Bootloader_OTAFIX` | `feature/ota-delta-apply`, `21c8a9c` | Merged the Docker build and its merge commit. |
| Original: `adafruit/Adafruit_nRF52_Bootloader` | `master`, `c67f0bc` | Already an ancestor; no new changes to apply. |

OTAFIX's separate `dev` branch was not merged. Its development-only button,
RAK Tag LED, and other commits remain outside this stable-branch integration.
No release tag was changed and no new release or hardware update was made.

## Conflict decisions

- Keep this fork's T096, T1 and RAK3401 definitions, corrected button/LED
  assignments, unique DFU identities, and Make/CMake mOTA capability flags.
  Preserve the existing documented factory VID/PID compatibility exceptions;
  no new board or USB identity is introduced by these merges.
- Keep the shared ST7735/ST7789 implementation and bounded screen drawing.
  The automatic merge appended a second ST7735 initializer; that duplicate
  was removed. Do not reintroduce upstream's unchecked text/icon writes or
  replace the compact display path needed by the fixed bootloader envelope.
- Keep GCC 14.2.Rel1 and the gated signed-release/field-kit pipeline, with
  write permission confined to the existing publication job. Incorporate
  the newer download-artifact action and fail on missing artifacts. Do not
  replace this pipeline with the upstream board-only draft-release job.
- Adopt the separate BLE-name reference, retaining this fork's additional
  boards and the shortened-advertisement warning. Remove the obsolete RAK
  version comparison removed upstream; retain the current recovery guidance.
- Adapt the Docker build to GCC 14.2.Rel1 instead of Debian's older compiler.
  Pin both supported host-architecture archives to Arm's published SHA-256
  values, verify before extraction, and provide the `python` command used by
  Make. Document exact-tag release builds separately from qualification builds.

The firmware sources under `src/`, vendored libraries under `lib/`, linker
scripts, root Makefile and CMake configuration are unchanged from `250559c`.
The net changes are tooling, CI, tests and documentation, not a new firmware
fix or a replacement for the 2.4.6 release assets.

## Verification

- Full `make -C test check`: passed, including eight new Docker contracts.
- Full `make -C test sanitize` with AddressSanitizer/UndefinedBehaviorSanitizer:
  passed. The Docker shell tests replace external commands; they do not
  download files or install anything on the host.
- CMake `heltec_t096` (ST7735S): passed, executable FLASH 40,011 / 40,784 bytes.
- CMake `heltec_t114` (ST7789): passed, executable FLASH 40,412 / 40,784 bytes.
- The documented Make default, `wismesh_tag`: passed, including manifest
  verification, Legacy DFU ZIP and dedicated bootloader `_mbr.uf2` generation.
- All target builds used Arm GNU 14.2.Rel1 (compiler 14.2.1) and the explicit
  qualification version `0x02040601`, not a new production version.
- Docker is not installed on the VM. An actual container image build/run,
  including the ARM64 binary in a container, remains unverified.

Local logs and test artifacts are under
`/home/mesh/otafix-upstream-merge.EzQK7a/`. Existing untracked qualification and
release-build directories were left untouched. No Mercer Pi or radio actions
were required for this source integration.
