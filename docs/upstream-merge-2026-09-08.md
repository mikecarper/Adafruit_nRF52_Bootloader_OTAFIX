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
- Docker was not installed during the initial merge verification. The
  subsequent native x86_64 container qualification is recorded below.

Local logs and test artifacts are under
`/home/mesh/otafix-upstream-merge.EzQK7a/`. Existing untracked qualification and
release-build directories were left untouched. No Mercer Pi or radio actions
were required for this source integration.

## Docker follow-up qualification - 2026-09-08

Docker Engine 29.1.3 and Buildx 0.30.1 are installed on the Ubuntu 24.04
x86_64 VM. The daemon is active and enabled at boot; the `hello-world` pull
and run passed. The existing session uses `sg docker -c '<command>'` to
activate the newly assigned Docker group without rebooting the VM.

Actual container testing found three environment problems:

- Missing Node.js prevented the CF2 inspection/transaction tests from running.
- Missing Python `cryptography` prevented the signed Legacy DFU tests from
  importing their signing implementation.
- Bookworm's native GCC 12 AddressSanitizer runtime repeatedly failed at
  startup. A bounded control using only `int main(void) { return 0; }` also
  failed in 6 of 20 runs, independently of the bootloader sources. This is
  consistent with the [upstream sanitizer startup issue](https://github.com/google/sanitizers/issues/1614).
  The failing suite was stopped and its repetitive diagnostic log compressed.

The Dockerfile now installs Node.js and `cryptography`, uses Debian 13
(`trixie-slim`) for its native GCC 14 sanitizer runtime, and checks these
dependencies while building the image. The firmware compiler remains the
same checksum-pinned Arm GNU 14.2.Rel1 (14.2.1). No host kernel settings were
changed, and no sanitizer or firmware safety checks were disabled. Three additional
regression contracts bring `docker_build_test.py` to 11 tests. Each new
contract was observed failing before its corresponding Dockerfile fix.

Final image: `otafix-build:latest`, Linux/amd64,
`sha256:f8bc8af57f8e210bee276b8cec4a3be1a5f5f1eb9c1f0e4a6c651a78593225c6`.
Its tools include native GCC 14.2.0, CMake 3.31.6, Python 3.13.5, Node.js
20.19.2, adafruit-nrfutil 0.5.3.post16, intelhex 2.3.0, and cryptography 50.0.1.

Final container results:

- Empty-program ASan/UBSan control: 100 of 100 runs passed.
- Full `make -B -C test check`: passed, rebuilding every native harness.
- Full `make -C test sanitize`: passed with ASan and UBSan enabled.
- Both required CMake display-controller builds passed from fresh directories.
- The unmodified image CMD, `make BOARD=wismesh_tag all`, passed when given
  the explicit qualification-version environment variables. It generated the
  combined SoftDevice+bootloader Legacy DFU 0.5 ZIP and dedicated `_mbr.uf2`.
- All three target builds passed their bootloader manifest CRC checks. ZIP
  integrity and read-only CF2 inspection of a generated T096 UF2 also passed.
- The untagged checkout was correctly rejected without the test-version
  override. No production version or release tag was fabricated.

| Target / build system | Executable FLASH used / limit | Free bytes | Manifest CRC32 |
| --- | --- | --- | --- |
| `heltec_t096` / CMake | 40,011 / 40,784 | 773 | `D2F8B266` |
| `heltec_t114` / CMake | 40,412 / 40,784 | 372 | `A5AB3281` |
| `wismesh_tag` / default Make CMD | 39,502 / 40,784 | 1,282 | `1783B107` |

The firmware qualification used `c1fc708` plus these Docker/test/documentation
edits and packed test version `0x02040601`. The two display bootloader BINs
are byte-identical across the Bookworm and final Trixie container builds.
The firmware sources, linker scripts and target build configuration remain
unchanged from the published 2.4.6 source.

Runs used UID/GID 1000, a read-only source checkout, separate writable test
and output directories, and `--network none`. No devices, privileged mode,
host Docker socket, or published ports were exposed to the test containers.
No Mercer Pi or radio was accessed. This is native x86_64 qualification;
the AArch64 download/checksum shell contracts passed, but an AArch64 image
was not built or run and hardware update qualification was not repeated.

Logs and generated qualification artifacts are under
`/home/mesh/otafix-docker-test.qd4Jmy/`. Final results are in
`image-build-final.log`, `toolchain-final.log`, `trixie-host-check.log`,
`trixie-sanitizers.log`, `trixie-t096.log`, `trixie-t114.log`, and
`trixie-default-wismesh-tag.log`. The earlier failures and empty-program
controls are retained in the same directory. Nothing was pushed or released.
