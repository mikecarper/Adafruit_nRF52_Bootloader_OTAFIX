# Bootloader update policy and flash retries

The bootloader policy is paired with a narrow MeshCore change allowing the two
compatible XIAO identities for bootloader updates. MeshCore signing requirements,
motatool, existing release packages and the optional `SIGNED_FW`
application/Legacy DFU policy are unchanged.

## Bootloader replacement

Normal builds now provide the manual bootloader replacement path previously
requiring a recovery build. USB UF2 and Legacy BLE/serial DFU accept bounded
images with valid chip RAM/Thumb reset vectors, including shorter and older
images without an OTAFIX manifest. Recognizable CF2 board IDs and BLMF identities
must match the running board. XIAO nRF52840 Sense and non-Sense are an explicit
compatible pair (`0x28860044` and `0x28860045`): their bootloader MCU, SoftDevice,
DFU/LED and QSPI pin definitions match. A shared image adopts that image's USB
identity and labels; it does not detect the sensor population automatically.
Some existing boards share a USB board ID, so that ID alone cannot establish
their pin compatibility; these remain basic checks rather than hardware detection.

Present BLMF CRCs and canonical BLM2 metadata are validated. Supplied BLM2
SoftDevice family/FWID, application boundary and layout ABI must agree with the
installed or accompanying SoftDevice. START component sizes, application vectors
and exact-reinstall rules for SD-only updates remain enforced. Raw images without
metadata cannot prove their board pins or SoftDevice ABI; choosing the correct
image remains the operator's responsibility. No signing key or separate `R_`
image is needed for these manual paths under the default unsigned configuration.

UF2 bootloader transfers may omit UICR declarations because the installed fixed
addresses already apply; declarations that are supplied must match. Conflicting
retransmissions are rejected against both committed flash and pending page-cache
bytes, and a new block number cannot overwrite an already committed target.
Staging still refuses to overlap a valid live application.

The bootloader accepts approved format-3 full bootloader `.mota` packages with
either `FULL | BOOTLOADER` or `FULL | SIGNED | BOOTLOADER`. It no longer requires
the SIGNED flag. Existing signed packages remain compatible.

The bootloader still requires explicit application approval and the existing
handoff/container hashes, matching package and embedded hardware identity, valid vectors,
matching SoftDevice/application layout, a whole-image BLMF CRC and compatible
storage/arena capabilities. Removing mandatory signing is not a cross-board or
arbitrary-blob bypass. The application remains responsible for package trust;
the old bootloader policy checked the signed flag, not an Ed25519 signature.
Other boards remain exact-board. The explicit XIAO pair exception requires a
canonical `XIAO_DFU` image: the outer target, its complete hardware ID and the
embedded image must agree on either `0x28860044` or `0x28860045`. SenseCAP images
sharing the base USB ID are excluded. Hash, CRC, SoftDevice/layout, approval and
staging-capability checks remain enforced.

At application handoff, the bootloader leaves its code and the MBR parameter
page writable, allowing an application to use Nordic MBR `COPY_BL`. The MBR
first page and bootloader settings page remain write-protected. This is a
deliberate security tradeoff: a buggy or malicious application can now overwrite
the bootloader or its copy parameters. Hashes and CRCs detect corruption; they
do not authenticate an author. Application code can set its own flash protections.

Current MeshCore and motatool have their own signed-bootloader requirements.
Those requirements are not changed here, so an unsigned end-to-end LoRa workflow
still needs corresponding application/tool support. Official package generation
remains signed for backward compatibility with existing devices.

## XIAO LoRa migration to one image

The initial rollout uses two bridge builds from the same update code and pin
configuration. `xiao_nrf52840_ble` retains ID `0x28860044` and
`xiao_nrf52840_ble_sense` retains ID `0x28860045`. Their identification labels,
embedded manifests and resulting hashes/CRCs differ; each initial package still
matches the old receiver's exact identity.

1. Install MeshCore firmware containing the XIAO pair compatibility checks.
   Its catalog, pull-to-flash and final bootloader validation paths all need
   this support. Application firmware still targets its own board and role.
2. Install each device's same-ID bridge `.mota` over LoRa using the existing
   signed-package and explicit `ota bootloader install <MID8> <HASH16>` flow.
   An old Sense bootloader cannot skip straight to the common ID-44 package.
3. Subsequent bootloader updates can use one signed `.mota` built from the
   non-Sense ID-44 image for both variants. Both bridge receivers accept it,
   and both devices then report the common image's USB identity and labels.

The application update and same-ID bridge may be installed in either order,
provided both are present before sending the common image. No motatool change
is needed: it already serves the exact, signed package identity unchanged.

## Bounded SoftDevice flash retries

An owned asynchronous `NRF_EVT_FLASH_OPERATION_ERROR` retries the same flash
chunk up to 100 additional times. Each retry waits at least 100 ms of foreground
board time; a successful chunk resets its retry count. Ten seconds is the total
deliberate delay allowance, not a bound on the SoftDevice's own operation times.
Exhaustion reports the error instead of retrying forever. Fatal synchronous
errors are also reported.

BUSY is not a completion. A retry that returns BUSY waits for the foreign flash
request's completion without counting that event as success for its own data.
That post-timeout BUSY wait is bounded; it never blindly reissues a write while
an earlier request may still own the next completion event.

Flash operations and owner callbacks remain in foreground context. Both normal
DFU waiting and SOC-only settings-save polling service due retries. Deadlines use
the existing millisecond SysTick, because the SDK can reset RTC1 when its last
application timer is removed. No new application timer or scheduler event is
needed: SysTick already wakes the bootloader, avoiding a build-up of unused
timer callbacks during SOC-only polling. Internal watchdogs are serviced on real
flash progress, not on empty polls that could conceal a stuck operation.

The Secure BLE qualification path uses a ten-second no-progress deadline, not a
ten-second total operation deadline. Real retry/flash progress renews that
deadline so 100 retries remain possible. A genuinely stalled accepted write
resets the device rather than returning while a callback still owns its buffer.

Ordinary serial/UF2 writes and LoRa application apply use direct NVMC operations
in this tree; the SoftDevice retry policy chiefly affects BLE DFU and its
activation settings. The pending-packet ring grows from 8 to 16 entries to cover
larger client PRN bursts during lazy erase or a delayed flash operation.
Private FIFO state is grouped in one BSS object and free slots rely on their
queue counts. This reduces generated code without changing the on-wire or
persisted layout. Shared volatile reads and separate bootloader-apply calls also
avoid duplicated code and register pressure; every update backend remains enabled.

The additional upstream session-status fix prevents a completed settings phase
from making a newly entered DFU session exit immediately. Cross-page flash writes
and safe UF2 staging overlap checks were already present. Upstream OLED/TWIM
teardown is not applicable to this tree's SPI TFT drivers. Disconnect resets,
inactivity policy and retained fault logging are not transplanted here because
they need separate resume/lifetime, RAM-layout and hardware qualification.

## Validation

- The production pstorage host suite passes 32 cases with optimization and LTO,
  including repeated command-slot reuse, synchronous rejection and reentrancy.
- Secure BLE passes 19 host cases; DFU-session entry and foreground integration
  pass two checks; production ACL/BPROT register tests pass.
- Internal, QSPI and SD bootloader `.mota` suites accept unsigned packages while
  retaining negative tests for corruption, approval, identity and layout.
- All 38 source boards pass fresh Arm GNU 15.3.Rel1 CMake qualification builds.
  Physical flash margins including initialized data are 1,332 bytes on T096,
  936 on T114, 781 on SD MeshTower, 8 on combined RAK4631, and 1,440/1,429 on the
  two XIAO bridges. They use explicit test version `0x02040CFE`; these are not
  released production images. All 37 nonzero-identity test binaries pass strict
  and manual image probes; ThinkNode M8 remains a compile-only zero-identity draft.
- Make also links and verifies the combined RAK4631, T096 and T114 HEX images
  with the same physical margins as CMake. Windows qualification used a short
  object directory to avoid native command-line length limits; ZIP packaging
  was not part of that frontend check.
- Twelve host bootloader suites pass 695 checks, including the full XIAO pair
  matrix, outer/payload mismatch, shared-ID foreign names and existing integrity
  failures. Optimized normal/recovery image-validator tests also pass.
- MeshCore passes 208 native OTA cases, nine production C++ scanner/CLI checks,
  nine signed-package checks and the XIAO repeater ARM build. Motatool's 18
  build/verify/seeder tests pass without changes.
- The existing build-profile helper suite was blocked on Windows by its
  symbolic-link privilege requirement (WinError 1314); it is not claimed passed.
- No hardware was flashed or power-interruption testing performed for this change.
