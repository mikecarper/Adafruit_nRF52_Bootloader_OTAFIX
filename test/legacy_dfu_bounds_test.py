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
    validated = start.index("dfu_start_packet_validate(&m_start_packet")
    assigned = start.index("&m_image_size", validated)
    region_bound = start.index("m_image_size > DFU_IMAGE_MAX_SIZE_FULL", assigned)
    functions = start.index("m_functions.", region_bound)
    if not idle < copy < validated < assigned < region_bound < functions:
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

    callback = function_source(source, "static void pstorage_callback_handler(")
    signed_callback = callback.index("#ifdef SIGNED_FW")
    data_ready = callback.index("m_dfu_state = DFU_STATE_RX_DATA_PKT", signed_callback)
    init_notify = callback.index("m_data_pkt_cb(INIT_PACKET", data_ready)
    unsigned_callback = callback.index("#else", init_notify)
    if not signed_callback < data_ready < init_notify < unsigned_callback:
        raise AssertionError(
            f"{path.name} does not finish every signed preparation as INIT"
        )

    signed_start = start.index("#ifdef SIGNED_FW", assigned)
    ready_without_erase = start.index("m_dfu_state = DFU_STATE_RDY", signed_start)
    start_notify = start.index("m_data_pkt_cb(START_PACKET", ready_without_erase)
    unsigned_branch = start.index("#else", start_notify)
    start_prepare = start.index("m_functions.prepare(m_image_size)", unsigned_branch)
    if not (
        signed_start
        < ready_without_erase
        < start_notify
        < unsigned_branch
        < start_prepare
    ):
        raise AssertionError(f"{path.name} erases for an unauthenticated signed START")

    complete = function_source(source, "uint32_t dfu_init_pkt_complete(")
    prevalidate = complete.index("dfu_init_prevalidate")
    signed_branch = complete.index("#ifdef SIGNED_FW", prevalidate)
    authenticated_prepare = complete.index("m_functions.prepare(m_image_size)", signed_branch)
    unsigned_branch = complete.index("#else", authenticated_prepare)
    data_ready = complete.index("m_dfu_state = DFU_STATE_RX_DATA_PKT", unsigned_branch)
    if not (
        prevalidate
        < signed_branch
        < authenticated_prepare
        < unsigned_branch
        < data_ready
    ):
        raise AssertionError(f"{path.name} does not defer signed flash preparation until INIT")

    validate = function_source(source, "uint32_t dfu_image_validate(")
    integrity = validate.index("dfu_init_postvalidate")
    role = validate.index("dfu_image_policy_validate", integrity)
    activate = validate.index("DFU_STATE_WAIT_4_ACTIVATE", role)
    if not integrity < role < activate:
        raise AssertionError(f"{path.name} activates bytes without role/layout validation")


def require_shared_start_validator() -> None:
    source = (ROOT / "src/dfu_image_policy.c").read_text()
    validator = function_source(source, "uint32_t dfu_start_packet_validate(")
    populated = validator.index("uint8_t const populated_mode")
    matched_mode = validator.index("start_packet->dfu_update_mode != populated_mode")
    alignment = validator.index("sizeof(uint32_t) - 1U")
    bootloader_bound = validator.index(
        "start_packet->bl_image_size > DFU_BL_IMAGE_MAX_SIZE"
    )
    first_add = validator.index("__builtin_add_overflow(start_packet->sd_image_size")
    second_add = validator.index("__builtin_add_overflow(image_size")
    total = validator.index("*image_size_out = image_size")
    if not (
        populated
        < matched_mode
        < alignment
        < bootloader_bound
        < first_add
        < second_add
        < total
    ):
        raise AssertionError("shared START validator performs unsafe size arithmetic")


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

    ble = (DFU_ROOT / "dfu_transport_ble.c").read_text()
    callback = function_source(ble, "static void dfu_cb_handler(")
    init_case = callback.index("case INIT_PACKET:")
    init_response = callback.index("BLE_DFU_INIT_PROCEDURE", init_case)
    event_handler = function_source(ble, "static void on_dfu_evt(")
    complete = event_handler.index("err_code = dfu_init_pkt_complete()")
    deferred_success = event_handler.index("if (err_code == NRF_SUCCESS)", complete)
    immediate_response = event_handler.index("BLE_DFU_INIT_PROCEDURE", deferred_success)
    if not init_case < init_response or not complete < deferred_success < immediate_response:
        raise AssertionError("BLE does not defer signed INIT success until erase completion")


def main() -> None:
    require_shared_start_validator()
    require_start_bounds(DFU_ROOT / "dfu_single_bank.c")
    require_start_bounds(DFU_ROOT / "dfu_dual_bank.c")
    require_serial_framing_bounds()

    ble = (DFU_ROOT / "dfu_transport_ble.c").read_text()
    append = function_source(ble, "static bool accum_append(")
    available = append.index("sizeof(m_accum_buf) - m_accum_len")
    copy_len = append.index("MIN(length, available)", available)
    copy = append.index("memcpy(m_accum_buf + m_accum_len", copy_len)
    flush = append.index("accum_flush(p_dfu)", copy)
    if not available < copy_len < copy < flush:
        raise AssertionError("BLE accumulator copy is not capacity-bounded")

    accum_flush = function_source(ble, "static bool accum_flush(")
    aligned_prefix = accum_flush.index("m_accum_len & ~(sizeof(uint32_t) - 1U)")
    retain_suffix = accum_flush.index("memmove(m_accum_buf")
    if aligned_prefix >= retain_suffix or "0xFF" in accum_flush:
        raise AssertionError("BLE accumulator pads or loses a partial-word suffix")

    app_data = function_source(ble, "static void app_data_process(")
    total_bound = app_data.index("pkt_len > (m_reported_image_size - received)")
    append_call = app_data.index("accum_append(p_dfu, p_data, pkt_len)")
    if total_bound >= append_call:
        raise AssertionError("BLE accepts DATA beyond the authenticated START length")

    ble_events = function_source(ble, "static void on_ble_evt(")
    disconnected = ble_events.index("case BLE_GAP_EVT_DISCONNECTED:")
    clear_suffix = ble_events.index("m_accum_len = 0", disconnected)
    mtu = ble_events.index("case BLE_GATTS_EVT_EXCHANGE_MTU_REQUEST:")
    floor_mtu = ble_events.index("((att_mtu - 3U) & 0xFFFCU) + 3U", mtu)
    if not disconnected < clear_suffix < mtu < floor_mtu:
        raise AssertionError("BLE reconnect suffix or MTU floor policy regressed")

    start_data = function_source(ble, "static void start_data_process(")
    validated = start_data.index("err_code = dfu_start_pkt_handle(&update_packet);")
    reported = start_data.index("m_reported_image_size = start_packet.sd_image_size")
    if validated >= reported:
        raise AssertionError("BLE records an unchecked wrapped image-size total")

    print("Legacy DFU framing, parser, start-size, and BLE accumulator bounds: PASS")


if __name__ == "__main__":
    main()
