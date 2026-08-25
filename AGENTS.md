# Agent Instructions

This file provides guidance to AI agents when working with code in this repository.

## Project Overview

OTAFIX CDC/DFU/UF2 bootloader for Nordic nRF52 microcontrollers. Supports Serial, BLE OTA, USB mass storage (UF2), and MeshCore in-place `.mota` delta application on the curated boards under `src/boards/`.

## Style

Follow the repo `.clang-format` when making changes.

## Build / Verify

Always verify changes against both display-controller variants:
- `heltec_t096` (ST7735S)
- `heltec_t114` (ST7789)

### CMake (preferred)
```bash
cmake -S . -B cmake-build-heltec_t096 -DBOARD=heltec_t096
cmake --build cmake-build-heltec_t096

cmake -S . -B cmake-build-heltec_t114 -DBOARD=heltec_t114
cmake --build cmake-build-heltec_t114
```

### Make (alternate)
```bash
make BOARD=heltec_t096 all
make BOARD=heltec_t114 all
```

### Flashing
```bash
make BOARD={board} flash       # Flash via JLink
make BOARD={board} flash-dfu   # Flash via Serial/CDC DFU
make BOARD={board} flash-sd    # Flash SoftDevice only
```

### Build all boards
```bash
python3 tools/build_all.py
```

For an intentionally dirty qualification tree, supply the packed test version
explicitly, for example `--test-version 0x02040302`. Production builds still
derive their version from a clean exact Git tag.

## Architecture

### MCU Variants and SoftDevices
- **nrf52** (nRF52832): UART-only bootloader, default SoftDevice s132 v6.1.1
- **nrf52833**: USB support, default SoftDevice s140 v7.3.0
- **nrf52840**: Full USB + OTA, default SoftDevice s140 v6.1.1
- Boards may override `SD_NAME`/`SD_VERSION` in their `board.mk`

### Key Source Structure
- `src/main.c` - Bootloader entry point, DFU mode detection, LED/button init
- `src/dfu_init.c` - DFU packet validation, CRC/signature verification
- `src/dfu_ble_svc.c` - BLE DFU service
- `src/flash_nrf5x.c` - Flash memory operations
- `src/boards/boards.c` - Board abstraction (LED control, buttons, timing)
- `src/usb/` - USB stack (nRF52833/nRF52840): CDC serial, MSC storage, UF2 handler
- `src/usb/uf2/ghostfat.c` - Virtual FAT filesystem for UF2 drag-and-drop

### Board Definition System

Each board lives in `src/boards/{board_name}/` with:
- `board.h` - Pin definitions, LED/button assignments, USB VID/PID, UF2 metadata
- `board.mk` - Makefile variable `MCU_SUB_VARIANT` (nrf52, nrf52833, or nrf52840)
- `board.cmake` - CMake variable `MCU_VARIANT`
- `pinconfig.c` - CF2 bootloader configuration (flash/RAM size, UF2 family ID)

### Memory Layout (linker scripts in `linker/`)
- The nRF52840 executable FLASH region is 40,784 bytes at `0xF4000..0xFDF50`; the board-bound
  88-byte CF2 configuration starts at `0xFDF50`, followed by a 12-byte reserved gap and the fixed
  76-byte BLMF+BLM2 envelope at `0xFDFB4..0xFE000`. CF2 consumers locate the configuration by its
  magic rather than a fixed address; linker assertions prevent either section from overflowing.
- Released bootloader images are board-bound and are not post-build CF2-patchable. Any CF2 mutation
  invalidates the whole-image BLMF CRC, and expanding the generic CF2 record can overwrite the fixed
  envelope. Use `tools/otafix_cf2.py` for read-only inspection; it refuses protected mutations before
  invoking the bundled patcher. Change `pinconfig.c`, rebuild, and regenerate the manifest CRC instead.
- No heap (`__HEAP_SIZE=0`), static allocation only
- Special sections: double-reset detection word, bond info for OTA, MBR params, bootloader settings

### Submodules (`lib/`)
- `tinyusb` - USB device stack
- `nrfx` - Nordic HAL drivers
- `uf2` - UF2 format tools
- `tinycrypt` - Crypto (only when `SIGNED_FW=1`)
- `sdk/`, `sdk11/` - Nordic SDK libraries
- `softdevice/` - Precompiled Bluetooth stack binaries

### Compile-Time Feature Flags
- `SIGNED_FW` - Require signed firmware (disables UF2 unless `FORCE_UF2=1`)
- `DUALBANK_FW` - Dual-bank updates
- `DEFAULT_TO_OTA_DFU` - Default to BLE OTA instead of serial DFU
- `DEBUG` - Enable RTT debugging, larger bootloader region

## PR Review Checklist

- **VID/PID assignment**: When a PR adds or modifies a board, verify `USB_DESC_VID`/`USB_DESC_UF2_PID` in `board.h`. New boards should use unique values. The Adafruit VID `0x239A` is reserved for Adafruit-allocated boards; third-party boards must use their own VID. Some legacy boards intentionally share a VID/PID with a reference board (see `// Shared VID/PID with ...` comments) - these are pending cleanup, not a template for new boards.

## CI

GitHub Actions (`.github/workflows/githubci.yml`) builds all boards in parallel using a matrix generated from `src/boards/` directory names. On release, artifacts (zip, hex, uf2) are uploaded as release assets.

## Required Toolchain

- `arm-none-eabi-gcc` 14.2.Rel1 or newer (GCC 12 is too large for the fixed nRF52840 envelope)
- Python 3 with: `adafruit-nrfutil`, `intelhex`
- `nrfjprog` (for JLink flashing)
