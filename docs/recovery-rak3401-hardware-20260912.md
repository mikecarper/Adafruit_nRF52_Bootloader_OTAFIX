# R_ recovery: RAK3401 hardware qualification

**Result: PASS, 2026-09-12.** Ten bootloader-family UF2 transfers on the
MercerWoodMesh Pi's physical, SWD-wired RAK3401 qualified the two-step
wrong-board recovery procedure and both `R_gat562` and
`R_wiscore_rak3401` bridges. No firmware fix was required.

## Images and method

- Source: `ced26342ae6c8156999430e30962c81f4f579a5b`.
- New fixtures: normal GAT562, R_GAT562, and R_RAK3401; qualification version
  `0x0204070B`, Legacy only (`SECURE_DFU_TEST=OFF`). Recovery versions identify
  as `R_0x0204070B`. These are test builds, not released/tagged artifacts.
- Correct-board destination: the installed normal RAK3401 Legacy
  `TEST_0x0204070A`, built from the same firmware source. SoftDevice S140 6.1.1
  was unchanged throughout.
- Wrong-board fixture: a genuine normal GAT562 bootloader on the physical
  RAK3401. The profiles share the MCU, SoftDevice, layout, regulator setting,
  and active-high LED pins. Their VID/PID is also shared; this hardware pair
  exercises **device-name mismatch**, not a separate VID/PID mismatch.
- Every SWD operation checked the target's two FICR device-ID words before
  accessing it. USB writes checked the exact serial, physical USB path,
  bootloader VID/PID, volume label, and mounted block device.
- SWD established the initial wrong-board fixture, selected DFU mode, and
  read back evidence. **All six accepted transitions below were ordinary
  UF2 file copies**, not debug programming of the destination bootloader.
  SWD mode selection means this was not a physical-button/double-reset test.
- After every transfer, read back the complete 40 KiB installed bootloader
  and 40 KiB staging region. Both had to match the expected bytes exactly.
  Complete staging was also required for rejections, excluding incomplete
  delivery as a false-positive negative test.

## Hardware results

Each row starts a fresh DFU session. All ten expected outcomes passed.

| Installed image | Incoming UF2 | Outcome |
| --- | --- | --- |
| Normal GAT562 | Normal RAK3401 | Rejected; GAT retained |
| Normal GAT562 | R_RAK3401 | Rejected; matching installed identity is required |
| Normal GAT562 | R_GAT562 | Accepted; matching bridge installed |
| R_GAT562 | CRC-corrupted normal RAK3401 | Rejected; recovery did not waive CRC validation |
| R_GAT562 | Normal RAK3401 | Accepted; correct physical-board identity recovered |
| Normal RAK3401 | Normal GAT562 | Rejected; strict identity guard restored |
| Normal RAK3401 | R_RAK3401 | Accepted; RAK bridge installed |
| R_RAK3401 | Normal GAT562 | Accepted; RAK bridge permits manual cross-board recovery |
| Normal GAT562 | R_GAT562 | Accepted; matching bridge reinstalled |
| R_GAT562 | Normal RAK3401 | Accepted; final normal bootloader restored |

The negative CRC fixture changed one executable payload bit at `0xF4108`
without regenerating its manifest CRC. No CF2 identity was patched.

Linux reported `sync -f` I/O errors on all ten copies. These host errors were
**not** treated as proof of success or used to trigger a blind retry: the
post-transfer installed/staged readbacks determined each result. This does
not qualify an error-free host copy/sync experience. A host copy result alone
is insufficient to determine whether recovery activated.

## Restoration and supporting checks

Before cleanup, application bytes were unchanged and the normal RAK bootloader
already matched its baseline. The only flash pages differing from the initial
snapshot were the ten UF2 staging pages at `0xE0000..0xEA000`. Restoring those
pages yielded an exact match of **all 1 MiB of flash and all 4 KiB of UICR**.
No application, settings, SoftDevice, or bootloader rewrite was needed for
cleanup.

The board then booted `v1.17.1.6-cli4-test-bc0fb2c3`. Plain ASCII CLI replies,
the application EndF hash, and unchanged name, radio settings, and public key
were verified. All three temporarily paused Pi services returned to their
original active states. **No R_ bridge was left installed.**

- Normal RAK bootloader SHA-256:
  `a0962c90f021ae88f71814ea4991e73c9613deffedcf934d0e0a38d156e2ddb2`
- R_GAT562 bootloader SHA-256:
  `dae1545c31c581e7da8d0331431f58672c476b4212ed092d490acbe695c3f09c`
- R_RAK3401 bootloader SHA-256:
  `d6767672658dddb926c360ad4b4dec551ef3a87db73bf90b93d227458247f564`

GCC 14.2.1/CMake builds passed for the three fixtures plus R_T096 (ST7735S)
and R_T114 (ST7789). Remaining executable FLASH was 1,620 bytes for R_RAK3401,
972 for R_T096, and 587 for R_T114. The displays were compile-checked, not
physically tested in this run.

Native production-code suites passed in both normal and recovery configurations:
`bootloader_image_test`, `dfu_image_policy_test`, and `bootloader_mota_test`.
Additional actual-fixture classification checks passed for both configurations,
including strict remote cross-board rejection even with recovery enabled.
These are **host tests**, not physical LoRa tests.

The local evidence directory is `cmake-build-recovery3401-0b/`, containing
build hashes/logs, native results, and `public-evidence.tar.gz` with transfer
records and bootloader/staging readbacks. Full-device snapshots containing
settings or keys are excluded from that export and from this report.

## Scope

This run qualifies the documented **UF2 recovery sequence on RAK3401** and the
two named recovery bridge binaries. It does not establish a new BLE/CDC DFU,
power-loss, incompatible-SoftDevice migration, physical display, or all-board
hardware result. R_ remains a temporary recovery-only, separate-prerelease
distribution; this test did not create a tag, release, commit, or push.
