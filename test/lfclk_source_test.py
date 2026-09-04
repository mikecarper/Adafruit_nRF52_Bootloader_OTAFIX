#!/usr/bin/env python3
"""Pin both boot timing and BLE recovery to the internal LFRC."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    raise AssertionError(f"unterminated function: {signature}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


boards = (ROOT / "src/boards/boards.c").read_text(encoding="utf-8")
main = (ROOT / "src/main.c").read_text(encoding="utf-8")

board_init = function_body(boards, "void board_init(void)")
stop = board_init.index("NRF_CLOCK->TASKS_LFCLKSTOP = 1UL")
select = board_init.index("NRF_CLOCK->LFCLKSRC = CLOCK_LFCLKSRC_SRC_RC")
start = board_init.index("NRF_CLOCK->TASKS_LFCLKSTART = 1UL")
require(stop < select < start, "board_init must stop, select, then start LFRC")
require("CLOCK_LFCLKSRC_SRC_Xtal" not in board_init,
        "board_init must not depend on an external LF crystal")

ble_init = function_body(main, "static uint32_t ble_stack_init(void) {")
required_ble_fields = (
    ".source       = NRF_CLOCK_LF_SRC_RC",
    ".rc_ctiv      = 16",
    ".rc_temp_ctiv = 2",
    ".accuracy     = NRF_CLOCK_LF_ACCURACY_250_PPM",
)
for field in required_ble_fields:
    require(field in ble_init, f"BLE LFRC configuration lost: {field}")
require("NRF_CLOCK_LF_SRC_XTAL" not in ble_init,
        "BLE recovery must not depend on an external LF crystal")
require("NRF_CLOCK_LF_SRC_SYNTH" not in ble_init,
        "BLE recovery must retain the calibrated LFRC source")
require(ble_init.index("nrf_clock_lf_cfg_t clock_cfg") <
        ble_init.index("sd_softdevice_enable(&clock_cfg"),
        "SoftDevice must be enabled with the checked LFRC configuration")

print("LF clock recovery policy: internal RC selected for board timing and BLE")
