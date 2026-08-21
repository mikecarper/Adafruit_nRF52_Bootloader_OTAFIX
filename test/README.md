# Bootloader `.mota` apply - host simulation test

Validates the nRF52 in-place delta apply (`src/ota_delta.c` + the vendored `detools` decoder + `sha256`)
**on the host, without hardware**. It compiles the real `ota_delta_check_and_apply()` with the
`OTA_DELTA_HOST_TEST` shims, lays out a RAM "flash" exactly like the device (running image at `APP_BASE`,
a staged `.mota` bottom-aligned below its selected ceiling, `GPREGRET`/`GPREGRET2` set), runs the apply,
and checks the result against the expected new image. Every decision point (EndF scan, `.mota` scan, base
check, detools return code, post-hash) is printed, so a failing apply is debuggable here instead of via
flash-and-pray on a board.

## Run

```bash
make check        # apply the committed vector (apply_sim) + the LTO-readback regression (readback_test)
```

Debug an arbitrary scenario (e.g. the real firmware that misbehaved on a device):

```bash
make apply_sim
./apply_sim <base.img> <delta.mota> <expected_new.img>

# Exercise the SD-backed bootloader path with a real full or delta package.
make sd_apply_test
./sd_apply_test <base.img> <full-or-delta.mota> <expected_new.img>

# Exercise raw external-QSPI staging with the same full/delta checks.
make qspi_apply_test
./qspi_apply_test <base.img> <full-or-delta.mota> <expected_new.img>

# Exercise generic internal staging and signed bootloader-package validation.
make readback_internal_test bootloader_mota_internal_test
./readback_internal_test
./bootloader_mota_internal_test

# Exercise signed MeshTower V2 microSD bootloader-package validation.
make bootloader_mota_sd_test
./bootloader_mota_sd_test
```

The internal tests exercise one shared `0xED000` staging ceiling. An ordinary `0x6A/0xED` delta is
bottom-aligned dynamically, and every detools write remains below its actual container start. This
includes a large valid delta, an overlapping detools geometry that must fail before invalidation, and
the ordinary-path full-image firewall. The signed bootloader test requires the exact 41,330-byte
format-3 container at `0xE2000`, validates its hash-bound live-app boundary and exact `0x0A` continuity
capability, then forward-compacts the payload from `+365` in the same slot to the raw 40 KiB MBR source
`0xE2000..0xEC000`. It verifies every page/readback and simulates power loss after each of the ten
destination pages, proving the application and installed bootloader stay byte-identical, settings are
untouched, the trigger is consumed, and a partial slot cannot retry.

The SD bootloader test pins the MeshTower V2 identity, exact `0x09` (`SD|BOOT_UPDATE`) capability, and
distinct `GPREGRET2=0x53` source marker. It supplies the exact 72-byte `MOTASDA2` retained-RAM record,
proves the record is zero-consumed before any SD access, and rejects wrong purpose/format, geometry,
CRC, normalized full-container hash, and a self-consistent A-to-B removable-media swap. Because the SD
backend is read-only, `APRV` remains on the card, but the consumed RAM authorization and
`GPREGRET=0x6B` make the file inert on a normal reset. A separate 64-byte internal token binds the signed
manifest's full `image_hash` for format-3 bootloader updates and page zero consumes that token.
It checks the independently hashed live `EndF` and CRC-bound bank-size boundary before every possible
scratch erase, both full and in-place successor codecs, readback/full-image verification, all ten page-level
power cuts, and preservation of ordinary SD application updates through `0xED000` even though bootloader
scratch begins at `0xE0000`.

The bootloader-image tests require the authoritative `BLMF`+`BLM2` envelope in the final 76 bytes of the
raw image, reject a relocated-only envelope and a 75-byte undersized input, and prove decoy bytes cannot
override the fixed record. The format-3 suites additionally reject outer/embedded version disagreement,
equal-version and downgrade candidates, SoftDevice FWID, application-base, and layout mismatch, invalid
version channels, and loss of either required successor codec. `manifest_patcher_test.py` independently
enforces the same fixed offset in the HEX post-link tool.

`cf2_guard_test.py` exercises the supported OTAFIX CF2 wrapper with raw BIN and UF2 images using the
production `0x9F50` CF2 / `0x9FB4` manifest layout. It preserves read-only inspection, refuses
BLMF-protected mutation without changing the file, exercises legacy mutation through the transactional
Node `fs` shim, and rejects growth beyond the pre-existing zero-padded CF2 span.

The suite also exercises the no-valid-image USB recovery wait: no VBUS falls through to BLE without any
delay, a USB host has the full 30-second default grace period to enumerate, enumeration at the deadline
is accepted, and VBUS removal stops the wait immediately.

The UF2 write-state test verifies that settings invalidation, each page erase, and block programming
are separate retryable phases. It also covers busy retries, completion counting, fail-closed committed
duplicates and same-geometry second copies, terminal aborts, and clearing every transfer/page mask at
an explicit USB/MSC session reset.

The QSPI alignment test exercises the nRF52840 EasyDMA boundary adapter with one-, three-, and five-byte
unaligned reads, multi-window reads, end-of-device tails, and the unaligned four-byte approval clear at
container offset 201. It also verifies that the read-modify-program path preserves adjacent bytes and
rejects attempts to change NOR bits from zero back to one.

The QSPI wake test verifies the mode-0 GPIO wake stream reconstructs the opcode-only `0xAB` command,
retains the conservative 50-us CS-high guards, and occurs before the pins are assigned to QSPI and
`TASK_ACTIVATE` is issued. This prevents a prior probe's deep-power-down command from deadlocking the
next QSPI activation.

The apply tests run against both S140 v6 (`APP_BASE=0x26000`) and S140 v7 (`0x27000`) layouts. They
also prove that the `0xED000` expanded-window hint works and missing/mismatched hints fail without
touching the running application.

`base.img` / `expected_new.img` are flat app images (`BODY||EndF`, what lives at `APP_BASE`); for an nRF52
build you can get one from `firmware.hex` with `intelhex` (`ih.tobinarray(start=ih.minaddr())`). Build the
`.mota` with `tools/motatool` (in the MeshCore repo).

## Why this exists

Real-hardware apply debugging is slow and brick-prone (reflash + LoRa fetch per iteration). This harness
caught a real bug: in-place deltas were built with `--inplace-memory = FS_START - APP_BASE` (`0xAE000`),
but the apply workspace is `[APP_BASE, mota_addr)` - the staged `.mota` sits *inside* that span, so detools
overran the workspace and returned `DETOOLS_IO_FAILED`; the device just rebooted with nothing applied. The
correct value (`MOTA_NRF52_INPLACE_MEMORY = 0x98000`, leaving room below `FS_START` for the staged `.mota`)
makes the apply succeed - proven here in seconds. To exercise that workspace boundary, run `apply_sim` with
a realistic (~550 KB) image; the tiny committed vector validates the apply *pipeline* (parse / scan / base
check / detools decode / result hash).

## `readback_test` - the `-flto` flash-readback regression

A second, HW-confirmed bug: in-place apply *reads back flash it just wrote* (the output overlaps the
input). The write goes through `nrfx_nvmc_words_write`; the readback through `fl_read` ->
`memcpy(dst, (const void*)(uintptr_t)addr, n)`. Same flash, two different pointer provenances - so
whole-program `-flto` decides they can't alias and caches a **stale** read, the post-hash sees pre-decode
bytes, and the apply is silently refused (the old firmware boots). The fix: `fl_read` reads through a
`volatile` pointer. `-fno-strict-aliasing` does *not* cover it (provenance, not type aliasing).

A plain host run can't reproduce the miscompile - here `otah_read`/`otah_write_words` hit the *same* C
array, an obvious alias the compiler never gets wrong. So `readback_test` guards the apply path six ways:

1. **positive** - coherent readback => the apply succeeds, commits, and matches the expected image.
2. **result retention** - models the reset after a successful apply and proves a second normal boot leaves
   `GPREGRET2=0xB8` intact for the application to report.
3. **negative** - it *injects* the exact failure mode (workspace reads return stale pre-write bytes) and
   asserts the apply **fails safe**: the bank stays invalid, returns false (-> DFU, never a corrupt boot).
4. **bounds/geometry** - rejects wraparound callback ranges, wrapped container size/leaf arithmetic, and
   impossible detools flash geometry before invalidating settings or modifying the current application.
5. **staging handoff** - proves expanded and legacy packages apply only with their matching GPREGRET2
   ceiling hint; missing or mismatched hints leave the running application untouched.
6. **source guard** - asserts the device `fl_read` still reads through `volatile`. This is the only check
   that catches a "someone reverted the fix" regression (1/3 can't, on the host). Verified: flipping
   `fl_read` back to a plain `memcpy` turns the suite red.

## Regenerating the committed vector

`test/vectors/{base.img,new.img,delta.mota}` are built from the MeshCore reference (`tools/mota/motalib`)
with a small synthetic firmware and an in-place delta (`memory_size = 0x98000`, `segment_size = 4096`,
`crle`). Regenerate if the `.mota`/EndF format changes.
