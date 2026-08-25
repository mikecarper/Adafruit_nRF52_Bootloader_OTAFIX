#!/usr/bin/env python3
"""Guard the reset boundaries around direct bootloader handoffs."""

from pathlib import Path


src = Path(__file__).resolve().parents[1] / "src"
source = (src / "main.c").read_text()
flash_source = (src / "flash_nrf5x.c").read_text()
ghostfat_source = (src / "usb" / "uf2" / "ghostfat.c").read_text()
main_start = source.index("int main(void)")
board_init = source.index("board_init();", main_start)
direct_entry = source.index("dfu_entry_reset_magic(requested_entry)", main_start)

if direct_entry >= board_init:
    raise AssertionError("buttonless direct entry must be reset before board initialization")

copy_start = source.index("if (bootloader_dfu_sd_in_progress())", board_init)
copy_end = source.index("\n  // Check all inputs", copy_start)
copy_block = source[copy_start:copy_end]

sequence = (
    "bootloader_dfu_sd_update_continue();",
    "bootloader_dfu_sd_update_finalize();",
    "led_state(STATE_WRITING_FINISHED);",
    "NRF_POWER->GPREGRET = 0;",
    "NVIC_SystemReset();",
)
position = -1
for statement in sequence:
    next_position = copy_block.index(statement)
    if next_position <= position:
        raise AssertionError(f"post-copy handoff order is wrong at {statement}")
    position = next_position

app_update = source.index(
    "bool const reset_after_app_update = bootloader_dfu_app_update_complete();",
    copy_end,
)
teardown = source.index("board_teardown();", app_update)
app_reset = source.index("NVIC_SystemReset();", teardown)
delta_apply = source.index("ota_delta_check_and_apply()", app_reset)
if not (app_update < teardown < app_reset < delta_apply):
    raise AssertionError("completed application updates must reset after teardown and before app launch")
if "_ota_dfu && bootloader_dfu_app_update_complete()" in source:
    raise AssertionError("UF2/CDC application completion must not direct-jump out of live USB state")

usb_dfu_start = source.index("// Enter DFU mode accordingly to input", copy_end)
usb_init = source.index("usb_init(false);", usb_dfu_start)
softdevice_disable = source.index("disable_softdevice();", usb_dfu_start)
if softdevice_disable >= usb_init:
    raise AssertionError("USB DFU must disable the SoftDevice before TinyUSB and direct NVMC access")
usb_guard = source[usb_dfu_start:softdevice_disable]
if "if (!_ota_dfu)" not in usb_guard:
    raise AssertionError("USB DFU SoftDevice shutdown must not run on the BLE transport")
if "bootloader_dfu_start(_ota_dfu, 0, probe_usb);" not in source:
    raise AssertionError("no-app USB recovery must exit on VBUS removal and allow BLE fallback")

invalidate_start = flash_source.index("void flash_nrf5x_invalidate_app_settings(void)")
invalidate_end = flash_source.index("\n}\n", invalidate_start)
invalidate_block = flash_source[invalidate_start:invalidate_end]
if "nrfx_nvmc_word_write(BOOTLOADER_SETTINGS_ADDRESS, 0);" not in invalidate_block:
    raise AssertionError("application settings invalidation is not an atomic zero-word write")

if "#define FLASH_PARTIAL_ERASE_MS    2u" not in flash_source:
    raise AssertionError("nRF52 partial erase must use Nordic's supported 2 ms minimum")

invalidate_case = ghostfat_source.index("case UF2_APP_FLASH_INVALIDATE_SETTINGS:")
invalidate_call = ghostfat_source.index("flash_nrf5x_invalidate_app_settings();", invalidate_case)
erase_case = ghostfat_source.index("case UF2_APP_FLASH_ERASE_PAGE:", invalidate_case)
if invalidate_call >= erase_case:
    raise AssertionError("UF2 application settings must be invalidated before page erase")

print("bootloader handoff reset checks passed")
