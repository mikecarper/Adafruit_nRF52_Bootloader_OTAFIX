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
timeout_path = re.search(
    r"if\s*\(\s*!MOTA_SD_SPIM->EVENTS_END\s*\)\s*\{(?P<body>.*?)\n\s*\}",
    source,
    re.DOTALL,
)
assert timeout_path is not None
assert "MOTA_SD_SPIM->TASKS_STOP = 1" in timeout_path.group("body")
assert "g_io_ok = false" in timeout_path.group("body")

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

print("SD SPI bounded-wait/watchdog guards: PASS")
