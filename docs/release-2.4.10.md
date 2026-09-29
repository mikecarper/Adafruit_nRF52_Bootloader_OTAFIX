# OTAFIX 2.4.10

Stable bootloader release. Packed version: `0x02040AFF`.

## Downloads

- `OTAFIX-2.4.10-bootloader-mota.zip`: 24 signed, exact-profile bootloader
  packages, the official public key, inventory and checksums.
- `OTAFIX-2.4.10-R_recovery.zip`: separate temporary local recovery bridges
  for all 29 historical/current profiles.
- Individual bootloader UF2, local DFU ZIP and SWD HEX files for the 24 normal
  profiles. RAK3401 and RAK4631 each have one normal download named `*_auto`.
- MeshCore Open remains a separate application. No Open kit or APK is bundled.

## Compatible RAK bootloader updates

Both normal RAK adaptive images now support signed bootloader `.mota` updates.
They retain the standard `3401_DFU` / `4631_DFU` identities, ABI 3 and internal
bootloader staging. Existing standard OTAFIX 2.4.9 `board` devices can install
the matching package normally, without a special migration command or bridge.
External flash is not required for this path.

Optional application NOR is advertised separately and selected by updated
unified MeshCore applications. Bootloader packages always stage internally on
these RAK images, including when the application uses external flash. Normal
MeshCore applications and their Nordic Legacy Bluetooth DFU ZIPs remain
compatible.

For optional NOR detection and bootloader pulls while using that NOR, use a
MeshCore build containing `5c4b6d63` (and its parent `346cf2fd`). Earlier
applications can continue using the standard internal contract. The associated
MeshCore Open Bluetooth reply fix is `5fee33f`; its successful phone test used
a local APK, not the published 9.5.5 RC2 APK. See the
[hardware qualification](hardware-qualification-2.4.10-rak-auto.md) for exact
application versions, hashes and test scope.

Installed `*_AUTO_DFU` bootloaders from 2.4.8/2.4.9 and dedicated external RAK
identities still require the [local recovery bridge](recovery-allow-all.md).
Use the bridge matching the installed identity, then the normal compatible
image for the physical board. Recovery builds remain temporary local tools;
the two adaptive recovery images do not support bootloader `.mota` themselves.

## Restored recovery information

- `INFO_UF2.TXT` again contains bootloader version, model, board ID, build date
  and expected SoftDevice family/FWID. `INDEX.HTM` again opens the board's
  support page. `CURRENT.UF2` readback and drag-and-drop flashing remain.
- Heltec T1, T096 and T114 again display model/version, USB versus Bluetooth
  mode, and USB update instructions or the Bluetooth DFU device name. A direct
  line renderer keeps this information within the fixed bootloader size.
- Shared parsing/copy/error-handling code and smaller equivalent USB/SHA loops
  recover space. Board identity, bounds, signatures, image hashes, CRCs,
  watchdog handling and failure cleanup remain enforced. Flash regions and
  the retained 64 KiB RAM contract are unchanged.

## Application update limits

Every normal profile supports application deltas and signed bootloader updates.
Full **application** `.mota` images require external NOR or microSD. Internal
staging supports exact-base application deltas that fit its available space;
the retained RAM arena extends that space but does not enable internal full
application installation. A matching LoRa-enabled application is required to
receive `.mota` packages.

The standard T114 does not assume optional NOR is populated. MeshTower internal
and microSD images remain separate profiles. Normal releases retain Legacy BLE
DFU; experimental resumable Secure BLE, signed-only Legacy DFU and dual-bank
builds remain separate options. The special signed-plus-dual-bank display
combination continues to use the status LED.

The [complete feature audit](update-feature-audit.md) lists every 2.4.9 profile
and the corrections in 2.4.10. Release publication requires the full board
matrix, host/sanitizer tests, both display-controller build families, signed
package verification and separate recovery archive verification to pass.
