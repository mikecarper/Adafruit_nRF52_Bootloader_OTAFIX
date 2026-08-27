# Signing OTAFIX bootloader mOTA packages

Bootloader `.mota` files are privileged format-3 packages. They must contain a
full, exact-board 40 KiB bootloader image and a valid Ed25519 signature from a
key trusted by the running MeshCore application. Ordinary UF2, serial/BLE DFU,
and SWD installation do not use this mOTA signer.

## Official OTAFIX release key

The official OTAFIX release signing public key is:

```text
272564CC588D3D122285A15E6E2566D2ABE7177BB7EA1D1E41B23B29F0F85D2D
```

Add it once from the MeshCore device console:

```text
ota key add 272564CC588D3D122285A15E6E2566D2ABE7177BB7EA1D1E41B23B29F0F85D2D
ota key
```

The second command lists the trusted keys so the addition can be confirmed.
Only the public key is distributed. The official private key is stored outside
the source tree and in the repository's release-only GitHub Actions secret.

After trusting the key, use MeshCore's explicit bootloader flow:

```text
ota pull <MID8> flash
# Wait until ota status reports that the download is ready.
ota bootloader
ota bootloader install <MID8> <HASH16>
```

Copy `MID8` and `HASH16` from the device output. A bootloader package is never
automatically installed. Verify the exact physical board and storage profile;
`heltec_mesh_tower_v2` and `heltec_mesh_tower_v2_sdcard` are not
interchangeable.

## Menu-driven release check and LoRa update

`tools/otafix_mota_update.py` reads `get bootloader.ver` and `ota bootloader`
from a directly connected MeshCore target, queries the latest GitHub release,
and reports whether an update is needed. Its install menu downloads the signed
bundle, verifies GitHub and package SHA-256 digests, requires the pinned
official signer, selects by the bootloader's exact target identity and storage
capability, and runs the explicit LoRa bootloader workflow.

Install `meshcli`, `motatool`, and PySerial first. Then run:

```bash
python3 -m pip install --user pyserial
python3 tools/otafix_mota_update.py
```

The default interactive flow asks for the target serial port, update action,
LoRa source, RF hop count, and bandwidth. It keeps frequency `909.950 MHz` and
SF5 unless they are overridden. A non-interactive version check is also
available:

```bash
python3 tools/otafix_mota_update.py \
  --target-serial /dev/serial/by-id/TARGET \
  --check-only
```

Pin the source and radio choices when desired:

```bash
python3 tools/otafix_mota_update.py \
  --target-serial /dev/serial/by-id/TARGET \
  --source-serial /dev/serial/by-id/SOURCE \
  --source-mode companion \
  --frequency 909.950 --sf 5 --bandwidth 500 --hops 1
```

The bandwidth menu offers 500, 250, 125, and 62.5 kHz. These conservative
end-to-end estimates include discovery, the 41,330-byte transfer, verification,
apply, and reboot. The BW500/SF5 one-hop baseline is grounded in four physical
2.4.2-to-2.4.3 runs that transferred in 67 to 89 seconds; narrower bandwidths
and additional hops are scaled estimates rather than guarantees.

| RF hops | BW500 | BW250 | BW125 | BW62.5 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1m45s-3m10s | 2m50s-4m50s | 5m00s-8m10s | 9m20s-14m50s |
| 2 | 2m34s-4m25s | 4m28s-7m20s | 8m15s-13m10s | 15m50s-24m50s |
| 3 | 3m23s-5m40s | 6m05s-9m50s | 11m30s-18m10s | 22m20s-34m50s |
| 4 | 4m12s-6m55s | 7m43s-12m20s | 14m45s-23m10s | 28m50s-44m50s |

Frequency, bandwidth, and transmit power must be legal at the operating
location. Every intermediate relay must already be on the same TempRadio tuple;
the script controls only the selected source and directly connected target.
Use `--temp-radio frequency,bw,sf,cr,minutes` only when the complete tuple must
be overridden.

The updater never chooses by a similar product name and never invents the
privileged install confirmation. It parses MID and hash from the device after
download and requires them to match the independently verified release
manifest. Success requires the new version, unchanged target identity,
`blup:C8`, and cleared staging after reboot.

## Create a key for a custom OTAFIX variant

Build the standalone `motatool`, then create an Ed25519 keypair with a private
file mode:

```bash
git clone https://github.com/mikecarper/motatool.git
cd motatool
git checkout 11f67eef8f1dffba9cbb7d102777cc7134be3821
cargo build --release --locked
umask 077
./target/release/motatool keygen --out custom-otafix.key
chmod 600 custom-otafix.key
```

This writes:

- `custom-otafix.key`: the private 32-byte signing seed. Keep it secret, back
  it up securely, and never place it in firmware, a release, or source control.
- `custom-otafix.key.pub`: the public key. Distribute this file and add its
  hexadecimal value to each target device with `ota key add`.

Build one exact-board package from the immutable release HEX:

```bash
./target/release/motatool build-bootloader \
  --fw heltec_t114_bootloader-0.11.0-OTAFIX2.4.3_s140_6.1.1.hex \
  --board heltec_t114 \
  --sign custom-otafix.key \
  --fw-version 2.4.3.255 \
  --out update-heltec_t114_bootloader-0.11.0-OTAFIX2.4.3.mota

./target/release/motatool verify \
  update-heltec_t114_bootloader-0.11.0-OTAFIX2.4.3.mota \
  --pub custom-otafix.key.pub
```

The version is derived from the embedded BLM2 metadata. `--fw-version` is only
an assertion and a mismatch is rejected. A stable `X.Y.Z` release uses channel
255; preview `N` uses channel `N`.

A custom board identity or storage profile must also be added to the qualified
inventories in motatool and MeshCore. Merely choosing a similar existing board
is unsafe and is rejected by the board-bound manifest checks.

## Automated official release bundle

The release workflow supplies its protected signing secret to the release-only
packaging job. The local equivalent is:

```bash
python3 tools/build_bootloader_mota_release.py \
  --artifacts-dir _release \
  --output-dir _mota-release \
  --motatool /path/to/motatool \
  --sign-key /secure/path/otafix-release.key \
  --public-key tools/otafix_mota_release.pub \
  --tag 0.11.0-OTAFIX2.4.3
```

The builder creates and verifies all qualified packages, requires the signer to
match the published public key, writes an inventory and SHA-256 checksums, and
produces one release ZIP. The private key is never copied into that output.
