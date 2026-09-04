#!/usr/bin/env python3
"""Guard externally supplied Legacy DFU lengths before arithmetic and copies."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DFU_ROOT = ROOT / "lib/sdk11/components/libraries/bootloader_dfu"


def braced_source(source: str, opening: int) -> str:
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
    start = source.index(signature)
    opening = source.index("{", start)
    return source[start:opening] + braced_source(source, opening)


def require_start_bounds(path: Path) -> None:
    start = function_source(path.read_text(), "uint32_t dfu_start_pkt_handle(")
    zero_mode = start.index("m_start_packet.dfu_update_mode == 0")
    known_mode = start.index("m_start_packet.dfu_update_mode > DFU_UPDATE_APP")
    bootloader_bound = start.index(
        "m_start_packet.bl_image_size > DFU_BL_IMAGE_MAX_SIZE"
    )
    softdevice_bound = start.index(
        "m_start_packet.sd_image_size > DFU_IMAGE_MAX_SIZE_FULL - m_start_packet.bl_image_size"
    )
    total_bound = start.index(
        "m_start_packet.app_image_size > DFU_IMAGE_MAX_SIZE_FULL -"
    )
    total = start.index("m_image_size = m_start_packet.sd_image_size")
    if not (
        zero_mode
        < known_mode
        < bootloader_bound
        < softdevice_bound
        < total_bound
        < total
    ):
        raise AssertionError(
            f"{path.name} does not validate image layout and components before adding them"
        )


def main() -> None:
    require_start_bounds(DFU_ROOT / "dfu_single_bank.c")
    require_start_bounds(DFU_ROOT / "dfu_dual_bank.c")

    ble = (DFU_ROOT / "dfu_transport_ble.c").read_text()
    app_data = function_source(ble, "static void app_data_process(")
    oversize = app_data.index(
        "if (m_accum_active && pkt_len > sizeof(m_accum_buf))"
    )
    flush = app_data.index("accum_flush(p_dfu);", oversize)
    bounded_branch = app_data.index("else if (m_accum_active)", flush)
    remaining = app_data.index(
        "if (m_accum_len + pkt_len > sizeof(m_accum_buf))", bounded_branch
    )
    copy = app_data.index("memcpy(m_accum_buf + m_accum_len", remaining)
    if not oversize < flush < bounded_branch < remaining < copy:
        raise AssertionError("BLE accumulator bounds no longer dominate its packet copy")

    start_data = function_source(ble, "static void start_data_process(")
    validated = start_data.index("err_code = dfu_start_pkt_handle(&update_packet);")
    reported = start_data.index("m_reported_image_size = start_packet.sd_image_size")
    if validated >= reported:
        raise AssertionError("BLE records an unchecked wrapped image-size total")

    print("Legacy DFU parser, start-size, and BLE accumulator bounds: PASS")


if __name__ == "__main__":
    main()
