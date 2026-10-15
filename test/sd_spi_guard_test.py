#!/usr/bin/env python3
"""Source guards for bounded SD-card SPI waits and inherited watchdogs."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "src" / "ota_sd_spi.c").read_text(encoding="utf-8")

assert "#define MOTA_SD_SPI_WAIT_SPINS" in source
assert re.search(
    r"while\s*\(\s*!MOTA_SD_SPIM->EVENTS_END\s*&&\s*spins--\s*!=\s*0\s*\)",
    source,
)
timeout_paths = list(re.finditer(
    r"if\s*\(\s*!MOTA_SD_SPIM->EVENTS_END\s*\)\s*\{(?P<body>.*?)\n\s*\}",
    source,
    re.DOTALL,
))
assert len(timeout_paths) == 2  # original standalone SD and combined shared SPI
for timeout_path in timeout_paths:
    assert "MOTA_SD_SPIM->TASKS_STOP = 1" in timeout_path.group("body")
    assert any(flag in timeout_path.group("body") for flag in (
        "g_io_ok = false", "g_spi_ok = false"
    ))

assert '#include "watchdog.h"' in source
assert "otafix_watchdog_feed();" in source
watchdog = (ROOT / "src" / "watchdog.h").read_text(encoding="utf-8")
assert "NRF_WDT->RREN & 0xFFu" in watchdog
assert re.search(
    r"if\s*\(\s*\(enabled\s*&\s*\(1u\s*<<\s*channel\)\)\s*!=\s*0\s*\)\s*\{\s*"
    r"NRF_WDT->RR\[channel\] = WDT_RR_RR_Reload",
    watchdog,
)
assert "board_watchdog_feed();" in source
assert re.search(r"bool ota_sd_read_sector.*?if\s*\(\s*!g_io_ok", source, re.DOTALL)
assert re.search(r"void ota_sd_deinit.*?g_io_ok\s*=\s*false", source, re.DOTALL)

# A selected SD handoff shares the RAK WisBlock SPI wires with optional NOR.
# Set inactive CS latches before making either GPIO an output or clocking SPI;
# the internal/NOR paths must not touch the SD bus as a side effect.
init = source[source.index("bool ota_sd_init(void)") : source.index("void ota_sd_deinit")]
rak_deselect = re.search(
    r"#if defined\(MOTA_RAK_SD_STORE\)(?P<body>.*?)#endif", init, re.DOTALL
)
assert rak_deselect is not None
nor = rak_deselect.group("body")
assert "ota_rak_spi_begin(MOTA_SD_CS_PIN, MOTA_SD_SCK_PIN" in nor
assert "ota_qspi_" not in nor  # no NOR probe while selecting SD
assert init.index("nrf_gpio_pin_set(MOTA_SD_CS_PIN)") < init.index(
    "nrf_gpio_cfg_output(MOTA_SD_CS_PIN)"
)
assert init.index("nrf_gpio_cfg_output(MOTA_SD_CS_PIN)") < init.index(
    "MOTA_SD_SPIM->ENABLE"
)
shared = source[source.index("bool ota_rak_spi_begin(") : source.index("void ota_rak_spi_select(")]
assert "if ((cs | sck | mosi | miso) >= 32u)" in shared  # exact P0-only contract
assert "NRF_P0->OUTSET = (1u << 26) | (1u << 31) | (1u << cs) | (1u << mosi)" in shared
assert shared.index("NRF_P0->OUTSET") < shared.index("NRF_P0->PIN_CNF[26]")
assert shared.index("NRF_P0->OUTCLR = 1u << sck") < shared.index("NRF_P0->PIN_CNF[26]")
assert shared.index("NRF_P0->PIN_CNF[31]") < shared.index("MOTA_SD_SPIM->ENABLE")
assert "GPIO_PIN_CNF_DRIVE_H0H1" in shared
assert shared.index("MOTA_SD_SPIM->PSEL.SCK") < shared.index("ota_rak_spi_set_frequency(")
assert "length > 255u ? 255u : length" in source  # SPIM2's 8-bit EasyDMA counter
assert "while (!MOTA_SD_SPIM->EVENTS_END && spins-- != 0u)" in source
assert re.search(
    r"if \(!MOTA_SD_SPIM->EVENTS_END\) \{\s*"
    r"MOTA_SD_SPIM->TASKS_STOP = 1;\s*"
    r"MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;\s*"
    r"g_spi_ok = false;\s*return false;",
    source,
)

print("SD SPI bounded-wait/watchdog/shared-CS guards: PASS")
