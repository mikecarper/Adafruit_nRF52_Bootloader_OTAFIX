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
```

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
