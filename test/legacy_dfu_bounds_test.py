#!/usr/bin/env python3
"""Guard externally supplied Legacy DFU lengths before arithmetic and copies."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DFU_ROOT = ROOT / "lib/sdk11/components/libraries/bootloader_dfu"
HCI_ROOT = ROOT / "lib/sdk/components/libraries/hci"


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
    source = path.read_text()
    start = function_source(source, "uint32_t dfu_start_pkt_handle(")
    idle = start.index("DFU_STATE_IDLE != m_dfu_state")
    copy = start.index("m_start_packet = *(p_packet->params.start_packet)")
    populated = start.index("const uint8_t populated_mode")
    matched_mode = start.index("m_start_packet.dfu_update_mode != populated_mode")
    nonempty = start.index("populated_mode == 0")
    known_mode = start.index("populated_mode > DFU_UPDATE_APP")
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
        idle
        < copy
        < populated
        < matched_mode
        < nonempty
        < known_mode
        < bootloader_bound
        < softdevice_bound
        < total_bound
        < total
    ):
        raise AssertionError(
            f"{path.name} does not validate image layout and components before adding them"
        )

    data = function_source(source, "uint32_t dfu_data_pkt_handle(")
    received_bound = data.index("m_data_received > m_image_size")
    word_bound = data.index("(m_image_size - m_data_received) / sizeof(uint32_t)")
    data_multiply = data.index(
        "data_length = p_packet->params.data_packet.packet_length * sizeof(uint32_t)"
    )
    if not received_bound < word_bound < data_multiply:
        raise AssertionError(f"{path.name} multiplies an unchecked DATA word count")

    init = function_source(source, "uint32_t dfu_init_pkt_handle(")
    init_word_bound = init.index("sizeof(m_init_packet) / sizeof(uint32_t)")
    init_multiply = init.index(
        "length = p_packet->params.data_packet.packet_length * sizeof(uint32_t)"
    )
    init_remaining = init.index(
        "m_init_packet_length > (sizeof(m_init_packet) - length)"
    )
    init_copy = init.index("memcpy(&m_init_packet[m_init_packet_length]")
    if not init_word_bound < init_multiply < init_remaining < init_copy:
        raise AssertionError(f"{path.name} does not bound INIT arithmetic before copying")


def require_serial_framing_bounds() -> None:
    hci = (HCI_ROOT / "hci_transport.c").read_text()
    validator = function_source(hci, "static bool is_rx_pkt_valid(")
    physical_min = validator.index("length < (PKT_HDR_SIZE + PKT_CRC_SIZE)")
    payload_decode = validator.index("const uint32_t payload_length")
    payload_min = validator.index("payload_length < sizeof(uint32_t)")
    payload_exact = validator.index(
        "payload_length != (length - PKT_HDR_SIZE - PKT_CRC_SIZE)"
    )
    crc = validator.index("crc16_compute")
    if not physical_min < payload_decode < payload_min < payload_exact < crc:
        raise AssertionError("HCI accepts a short or length-confused application packet")

    serial = (DFU_ROOT / "dfu_transport_serial.c").read_text()
    handler = function_source(serial, "void rpc_transport_event_handler(")
    extract = handler.index("hci_transport_rx_pkt_extract")
    packet_type = handler.index("const uint32_t packet_type = uint32_decode")
    known_type = handler.index("packet_type < INIT_PACKET")
    unsupported_type = handler.index("packet_type == STOP_INIT_PACKET")
    start_shape = handler.index("sizeof(uint32_t) + sizeof(dfu_start_packet_t)")
    stop_shape = handler.index("packet_type == STOP_DATA_PACKET")
    data_shape = handler.index("rpc_cmd_length_read % sizeof(uint32_t)")
    schedule = handler.index("app_sched_event_put")
    publish = handler.index("data_queue_element_alloc", schedule)
    if not (
        extract
        < packet_type
        < known_type
        < unsupported_type
        < start_shape
        < stop_shape
        < data_shape
        < schedule
        < publish
    ):
        raise AssertionError("serial DFU publishes unchecked or unscheduled packet storage")

    processor = function_source(serial, "static void process_dfu_packet(")
    start_case = processor.index("case START_PACKET:")
    start_handle = processor.index("dfu_start_pkt_handle(packet)", start_case)
    activity = processor.index("bootloader_dfu_activity_mark()", start_handle)
    init_case = processor.index("case INIT_PACKET:")
    init_handle = processor.index("dfu_init_pkt_handle(packet)", init_case)
    init_complete = processor.index("dfu_init_pkt_complete()", init_handle)
    stop_case = processor.index("case STOP_DATA_PACKET:")
    stop_validate = processor.index("dfu_image_validate()", stop_case)
    stop_activate = processor.index("dfu_image_activate()", stop_validate)
    stop_cleanup = processor.index("data_queue_element_free(index)", stop_activate)
    if not (
        start_case
        < start_handle
        < activity
        < init_case
        < init_handle
        < init_complete
        < stop_case
        < stop_validate
        < stop_activate
        < stop_cleanup
    ):
        raise AssertionError("serial DFU accepts invalid state transitions or strands STOP")


def main() -> None:
    require_start_bounds(DFU_ROOT / "dfu_single_bank.c")
    require_start_bounds(DFU_ROOT / "dfu_dual_bank.c")
    require_serial_framing_bounds()

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

    print("Legacy DFU framing, parser, start-size, and BLE accumulator bounds: PASS")


if __name__ == "__main__":
    main()
