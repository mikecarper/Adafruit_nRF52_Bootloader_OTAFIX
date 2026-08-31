#!/usr/bin/env python3
"""Guard Legacy serial DFU's upfront erase and erase-free DATA contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DFU_ROOT = ROOT / "lib/sdk11/components/libraries/bootloader_dfu"
SINGLE_BANK_SOURCE = DFU_ROOT / "dfu_single_bank.c"
DUAL_BANK_SOURCE = DFU_ROOT / "dfu_dual_bank.c"
FLASH_SOURCE = ROOT / "src/flash_nrf5x.c"
GHOSTFAT_SOURCE = ROOT / "src/usb/uf2/ghostfat.c"

LEGACY_SD_BL_BYTES = 193688
CODE_PAGE_SIZE = 4096


def braced_source(source: str, opening: int) -> str:
    """Return a complete C braced block beginning at ``opening``."""
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    raise AssertionError("unterminated C block")


def function_source(source: str, signature: str) -> str:
    """Return one complete C function, including its balanced outer braces."""
    start = source.index(signature)
    opening = source.index("{", start)
    return source[start:opening] + braced_source(source, opening)


def non_ota_branch(prepare: str) -> str:
    """Return the else block paired with a prepare function's is_ota test."""
    ota_if = prepare.index("if ( is_ota() )")
    ota_opening = prepare.index("{", ota_if)
    ota_block = braced_source(prepare, ota_opening)
    ota_end = ota_opening + len(ota_block)
    else_index = prepare.index("else", ota_end)
    return braced_source(prepare, prepare.index("{", else_index))


def require_prepare_erase(
    source: str,
    signature: str,
    erase_call: str,
    callback_call: str,
) -> None:
    prepare = function_source(source, signature)
    direct = non_ota_branch(prepare)
    if direct.count("flash_nrf5x_erase(") != 1:
        raise AssertionError(f"{signature} must contain exactly one direct erase")
    if "#ifdef NRF_USBD" in direct:
        raise AssertionError(f"{signature} must not diverge for USB serial DFU")
    erase = direct.index(erase_call)
    ready = direct.index(callback_call, erase)
    if erase >= ready:
        raise AssertionError(f"{signature} reports ready before its complete erase")


def require_erase_free_data(source: str, direct_write: str) -> None:
    for forbidden in ("m_direct_erase_next", "packet_end"):
        if forbidden in source:
            raise AssertionError(f"serial DATA erase state remains: {forbidden}")
    data = function_source(source, "uint32_t dfu_data_pkt_handle(")
    if "flash_nrf5x_erase(" in data:
        raise AssertionError("Legacy serial DATA handling must never erase flash")
    if direct_write not in data:
        raise AssertionError("Legacy serial DATA handling lost its direct write")
    if "flash_nrf5x_flush(false);" not in data:
        raise AssertionError("Legacy serial DATA completion lost its final flush")


def main() -> None:
    single = SINGLE_BANK_SOURCE.read_text()
    dual = DUAL_BANK_SOURCE.read_text()
    flash = FLASH_SOURCE.read_text()
    ghostfat = GHOSTFAT_SOURCE.read_text()

    # Both Legacy bank implementations must finish the complete destination
    # erase before their synchronous PREPARING callback reports START ready.
    require_prepare_erase(
        single,
        "static void dfu_prepare_func_app_erase(",
        "flash_nrf5x_erase(DFU_BANK_0_REGION_START, m_image_size);",
        "pstorage_callback_handler(&m_storage_handle_app, PSTORAGE_CLEAR_OP_CODE",
    )
    require_prepare_erase(
        dual,
        "static void dfu_prepare_func_app_erase(",
        "flash_nrf5x_erase(DFU_BANK_0_REGION_START, m_image_size);",
        "pstorage_callback_handler(&m_storage_handle_app, PSTORAGE_CLEAR_OP_CODE",
    )
    require_prepare_erase(
        dual,
        "static void dfu_prepare_func_swap_erase(",
        "flash_nrf5x_erase(DFU_BANK_1_REGION_START, image_size);",
        "pstorage_callback_handler(&m_storage_handle_swap, PSTORAGE_CLEAR_OP_CODE",
    )

    # flash_nrf5x_erase() aligns the start down and rounds the requested byte
    # length up, so even a non-page-sized Legacy image is completely erased.
    erase = function_source(flash, "void flash_nrf5x_erase (")
    if "dst & ~(CODE_PAGE_SIZE - 1)" not in erase:
        raise AssertionError("flash erase no longer aligns its first page")
    if "NRFX_CEIL_DIV(len, CODE_PAGE_SIZE)" not in erase:
        raise AssertionError("flash erase no longer rounds image length to full pages")
    legacy_pages = (LEGACY_SD_BL_BYTES + CODE_PAGE_SIZE - 1) // CODE_PAGE_SIZE
    if legacy_pages != 48:
        raise AssertionError("Legacy SD+bootloader page-count model changed")

    require_erase_free_data(
        single,
        "flash_nrf5x_write(DFU_BANK_0_REGION_START + m_data_received",
    )
    require_erase_free_data(
        dual,
        "mp_storage_handle_active == &m_storage_handle_app",
    )

    # This rollback is serial-only. MSC application writes must retain their
    # separately retryable, one-complete-page erase phase.
    app = function_source(ghostfat, "static bool prepare_app_block(")
    erase_case = app.index("case UF2_APP_FLASH_ERASE_PAGE:")
    program_case = app.index("case UF2_APP_FLASH_PROGRAM_BLOCK:", erase_case)
    erase_phase = app[erase_case:program_case]
    full_page = erase_phase.index(
        "flash_nrf5x_erase(block->targetAddr, CODE_PAGE_SIZE);"
    )
    busy = erase_phase.index("return false;", full_page)
    if full_page >= busy:
        raise AssertionError("MSC must return busy after each complete page erase")

    print(
        "Legacy serial DFU erase checks passed: "
        f"{legacy_pages} pages upfront, DATA erase-free, MSC retry preserved"
    )


if __name__ == "__main__":
    main()
