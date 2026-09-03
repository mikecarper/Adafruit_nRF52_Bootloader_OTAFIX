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
make sanitize     # rebuild and run the complete host suite with ASan and UBSan
```

`make codec3-check` explicitly compiles the opt-in codec 3 on and off and runs
the real application-update entry point with raw, compressed, and mixed DIP1
records. Profile 1 uses independent 1 KiB records with one final fixed-Huffman
block per compressed record. Both legacy internal staging and shared internal
bootloader-update staging are covered, including codec-2 compatibility and
capability advertisement. Malformed wrapper geometry, record sizes, final
records, manifest flags, truncations, and trailing input must be rejected before
application invalidation; a final image hash mismatch must leave the bank
invalid. Vectors are generated independently with Python's zlib around the
committed detools patch and target image.

The standalone tinf tests use a native batch runner with exact-sized allocations,
not a shared library loaded into Python. Both it and the codec-3 integration
harnesses inherit `CFLAGS`, so `make sanitize` instruments the actual decoders,
including the standalone valid, malformed, truncated, and random input cases.

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

# Reproduce the complete SD handoff against an exact signed release package.
# The harness models APRV, retained authorization/token, and raw payload +365.
MOTA_EXACT_PACKAGE=/path/to/exact-bootloader.mota ./bootloader_mota_sd_test
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

The UF2 write-state test verifies that the bootloader atomically clears the
application-valid settings word before erasing any out-of-order target page,
and that each page erase and block program remains a separate retryable phase.
This keeps an interrupted image unbootable even while its vector page is still
intact. Hardware A/B testing showed that OTAFIX 2.4.3's partial-NVMC application
erase could disconnect a XIAO nRF52840 on its first UF2 sector, while OTAFIX
2.4.2's complete-page erase accepted and synced the identical sector. The
regression tests therefore require the proven complete-page path and reject the
partial-erase helper. TinyUSB retains its normal global drain-to-empty behavior.
Only an MSC WRITE10 callback that consumed fewer bytes than it received is
deferred outside the USB event queue, and at most one previously pending MSC
retry runs after each complete real-event drain. Deferred work is bound to a
monotonic generation so a retry sampled before BOT/bus reset cannot consume a
new WRITE accepted while the real-event queue drains. The task-budget model
covers that reset/new-command race as well as
the ten page erases used by bootloader staging and proves they require ten loop
passes with at most one roughly 85 ms erase per pass instead of one
approximately 850 ms stall. It does not model every block in an application
image. The separate write-state test uses compact synthetic geometry to cover
busy retries, idempotent committed-block retransmission, completion counting,
terminal geometry/kind aborts, and clearing every transfer/page mask at an
explicit USB/MSC session reset. The production caller compares retransmitted
application bytes with flash before accepting them; a conflicting same-geometry
image remains fail-closed.

The synthetic physical `CURRENT.UF2` extent is pinned read-only at its first,
middle, and last sectors, including malformed or changed host data and a
multi-sector write crossing its tail. A saved `CURRENT.UF2` copied to clusters
beyond that extent remains a normal application transfer.

The hardware lineage has two distinct first-sector failures. Released OTAFIX
2.4.3 (`243b061`) introduced the unsafe 2 ms partial-NVMC erase path; exact
OTAFIX 2.4.2 (`20f976f`) accepted and synced the same sector with a complete
page erase. The later XIAO candidate identified by
`0.11.0-OTAFIX2.4.3-3-gffb1580-dirty-test-version-0x02040401` had already
restored `nrfx_nvmc_page_erase()`, but its global one-event TinyUSB budget still
failed. The exact installed bootloader-only ZIP SHA-256 was
`fcd7933afdc3c9dd8d24707084f5106b3612ed162939c02d68440f518d6fdbf6`;
the embedded 40 KiB bootloader SHA-256 was
`652bb243654bd3d500392e43d015f325061ccb56c418d862f410306c06238b6d`.
It failed before image completion, so that case is an MSC receive/retry
scheduling failure rather than the clean application-handoff path tested below.
Packed test version `0x02040402` identifies the first corrected MSC-local retry
candidate lineage. Command-lifecycle and generation-bound reset hardening uses
the distinct packed version `0x02040403` for current qualification.

The UF2 clean-handoff regression keeps a completed application invalid until
TinyUSB has acknowledged the final write and either the volume stays idle for
one second, an explicit eject status reaches the host, or the host physically
disconnects. Later FAT/directory writes and `SYNCHRONIZE CACHE` move the idle
boundary; cache sync is deliberately not an immediate reset boundary because
Linux can still have virtual-FAT bios queued after its status. Bootloader-family
UF2 keeps its immediate validated `COPY_BL` path. The model pins the full
CBW-to-CSW lifecycle for delayed WRITE10, READ10, and built-in commands, plus a
BOT/bus reset which releases an abandoned command and incomplete eject without
blessing or cancelling a complete pending image. Abort/session-reset paths
still cancel rather than bless an incomplete image.

The Legacy serial DFU erase regression guards the separate CDC/UART contract in
both the single- and dual-bank implementations. Every page covering the full
announced image is erased during START preparation, before the ready callback;
the DATA path writes into that prepared bank without any erase state or page
boundary stall. The test also pins the page-alignment/round-up behavior and
checks that this serial correction did not replace MSC's separately retryable
one-complete-page erase phase.

The pstorage regression compiles the production raw driver against a deterministic SoftDevice flash
mock. It verifies that an immediate `NRF_ERROR_BUSY` waits for and ignores the preceding operation's
event, retries without completing the wrong queue entry, and propagates lazy-erase enqueue failures
instead of leaving the DFU packet buffer permanently active. It also covers fatal synchronous and
asynchronous rollback, full-ring callback enqueue, nested callback attribution, command-bound lazy
erase identity, exactly-once abort callbacks for every accepted pending packet, and multi-page clears
used by dual-bank OTA. It also pins strict buffered-store FIFO ordering while a pending store is in
flight, including stores submitted from its callback, so a final DFU packet cannot overtake older
accepted packets or report completion before they are programmed. A later clear is backpressured until
that accepted store FIFO drains, and a store accepted reentrantly during an abort callback is kicked
after the original abort snapshot instead of being left idle without a future flash event.

The DFU-entry regression pins the buttonless handoff contract: legacy `B1`
direct-jump entry must bounce through a hardware reset, while reset-based BLE,
serial, UF2, and normal boots must not reset again. A source-level guard also
requires that conversion before board initialization, requires the UF2
settings-invalidating zero-word write to precede page erase, and fixes the
bootloader-copy sequence as continuation, settings finalization, completion
indication, stale transport-magic clear, then system reset. The replacement
image therefore cannot re-enter BLE DFU because of the `0xA8` request left by
the prior transport callback. Completed BLE, UF2, and CDC application updates
all tear down their active transport and reset before application startup, so
none direct-jumps with live USB, SoftDevice, or radio state. The same guard
requires non-BLE recovery to disable the SoftDevice before TinyUSB/direct NVMC,
uses a complete-page erase rather than the hardware-failing partial path, and
keeps no-application USB recovery sensitive to VBUS removal so it can fall back
to BLE.

The BLE-advertising regression pins the 31-byte Legacy DFU layout. Flags and the
128-bit DFU service UUID must be inserted before the local name, leaving eight
name bytes. Longer board names, including MeshTower V2's `TOWER_V2_OTA`, must
use the shortened-name AD type instead of silently dropping the UUID.

The Make build-profile regression uses a stub Arm toolchain, so it runs on a
host without Arm GCC 14. It proves that identical profiles reuse objects while
changes to the SoftDevice, signing policy or public key, dual-bank/UF2/DFU/debug
features, USB timeout, source selection, or compiler/linker flags rewrite a
content-hashed stamp and force both recompilation and relinking. The persisted
stamp contains only a SHA-256 digest. The same regression pins nonrelease CI to
the documented corrected `0x02040403` qualification lineage and rejects reuse
of failed candidate ID `0x02040401` as an active override.

The BLE-connection-policy regression keeps connection-parameter ownership with
the central and forbids a fatal CONNECTED-time GAP update. It requires both
DATA-phase latency options to remain fail-open and re-applies them after a
central connection-parameter update only while firmware DATA is active, so an
update cannot silently restore the bonded-path throughput regression or undo
the intentional flash-priority latency during START erasure. It also requires
every DATA exit (validation, final/error callback, transport close, disconnect,
and a new START) to restore both local and negotiated-slave-latency policy.

The Legacy BLE DFU host regression exercises the identity-gated recovery
client without hardware. It binds the exact ZIP bytes to their SHA-256 and
manifest/init CRC, requires address/name/service/DIS-model identity, rejects
short, ahead, stale, missing, malformed, and out-of-order receipts, and covers
both application and SoftDevice-plus-bootloader package geometry. Adaptive PRN
changes occur only at exact cumulative receipt boundaries; zero and nonfinite
timing samples are rejected. Its levels are
bounded by packet size: 20--60-byte accumulated writes use 8/16/32, 64-byte
writes use 8/16, and larger direct-to-pstorage writes use 4/8 so they cannot
outrun the target's eight-packet lazy-erase FIFO. Two clean exact receipts
within a 125 ms notification allowance plus the actual payload time at 1600
B/s trigger one adjacent safe-level probe. Two clean neutral receipts at a
nonmaximum window can trigger the same bounded probe, avoiding a
receipt-overhead trap seen at 864--871 B/s with 244-byte XIAO writes. One clean
receipt slower than the same allowance plus 800 B/s payload time demotes one
level. A probe keeps a first sample
that is over 10 percent better, rolls back a first sample that is over 10
percent worse (or materially slow), and otherwise compares at most two probe
receipts against the lower-window baseline. A failed probe or a real slow
demotion from a previously kept level blocks every further increase for that
DFU session, even after fast-looking jitter, while additional slow exact
receipts may continue down through the remaining safe levels. This prevents
PRN churn without disabling the initial probe or safe downward negotiation.
The host vectors pin both the physically observed 2110
B/s fast path and the 870 B/s
neutral path, including improved, degraded, rollback, and no-reprobe cases,
while proving 244-byte writes never exceed PRN8. BlueZ readiness vectors
require an exact service/characteristic identity, strict integer capability
values, finite bounded polling, and canonical disconnect-race failures. DATA
progress separately records sent, exact-receipt-confirmed, and final-response-
confirmed bytes, while phase timing includes the final RECEIVE response.
The lab-only pre-START pause is finite and nonnegative, performs no DFU write,
and fails if the exact link disconnects while paused. It exists so an external
hardware harness can prove one bounded connection update before START; it is
not an in-DATA speed-control mechanism.

The retained-peer-data regression compiles the exact S132 v6, S140 v7, and S140 v6 Nordic types used by
nRF52832, nRF52833, and nRF52840 and pins the Bluefruit BLEDfu ABI: 60 bytes of peer data at
`0x20007F80`, followed by its CRC16 at offset 60. A static test checks every release and debug linker
script so LTO or input-section ordering cannot place the CRC before the data again.

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
