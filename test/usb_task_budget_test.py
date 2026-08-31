#!/usr/bin/env python3
"""Regression model for yielding MSC busy retries without starving TinyUSB."""

from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TUSB_CONFIG = ROOT / "src/usb/tusb_config.h"
USBD_SOURCE = ROOT / "lib/tinyusb/src/device/usbd.c"
MSC_SOURCE = ROOT / "lib/tinyusb/src/class/msc/msc_device.c"
MSC_HEADER = ROOT / "lib/tinyusb/src/class/msc/msc_device.h"
BOOTLOADER_SOURCE = (
    ROOT / "lib/sdk11/components/libraries/bootloader_dfu/bootloader.c"
)
FLASH_SOURCE = ROOT / "src/flash_nrf5x.c"
FLASH_HEADER = ROOT / "src/flash_nrf5x.h"
GHOSTFAT_SOURCE = ROOT / "src/usb/uf2/ghostfat.c"
UF2_HEADER = ROOT / "src/usb/uf2/uf2.h"
NRF52840_PAGE_ERASE_MS = 85


class MscRetryModel:
    """Minimal model of the bootloader loop and a BUSY WRITE10 callback."""

    def __init__(self, busy_flash_steps: int) -> None:
        self.events: deque[str] = deque()
        self.generation_seed = 0
        self.pending_generation = 0
        self.busy_flash_steps = busy_flash_steps
        self.handled: list[str] = []
        self.flash_ms_each_pass: list[int] = []
        self.stale_retries = 0

    @property
    def pending(self) -> bool:
        return self.pending_generation != 0

    def _next_generation(self) -> int:
        self.generation_seed += 1
        return self.generation_seed

    def _reset(self) -> None:
        # The monotonic seed deliberately survives transport reset, while the
        # buffered work and its generation do not.
        self.pending_generation = 0

    def _write_callback(self) -> None:
        if self.busy_flash_steps:
            self.busy_flash_steps -= 1
            self.pending_generation = self._next_generation()
            self.flash_ms_each_pass[-1] += NRF52840_PAGE_ERASE_MS
        else:
            self.pending_generation = 0
            self.handled.append("write-complete")

    def _retry(self, generation: int) -> None:
        if not generation or self.pending_generation != generation:
            self.stale_retries += 1
            return
        self.pending_generation = 0
        self._write_callback()

    def pass_once(self) -> None:
        # Sample before tud_task(): a retry first created by a real event in
        # this pass is not eligible until the next pass.
        retry_generation = self.pending_generation
        self.flash_ms_each_pass.append(0)

        # tud_task() drains every real event. Do not throttle every TinyUSB
        # class merely because MSC has deferred flash work.
        while self.events:
            event = self.events.popleft()
            if event == "write":
                self._write_callback()
            elif event == "reset":
                self._reset()
            else:
                self.handled.append(event)

        if retry_generation:
            self._retry(retry_generation)


def main() -> None:
    config = TUSB_CONFIG.read_text()
    usbd = USBD_SOURCE.read_text()
    msc = MSC_SOURCE.read_text()
    msc_header = MSC_HEADER.read_text()
    bootloader = BOOTLOADER_SOURCE.read_text()
    flash = FLASH_SOURCE.read_text()
    flash_header = FLASH_HEADER.read_text()
    ghostfat = GHOSTFAT_SOURCE.read_text()
    uf2_header = UF2_HEADER.read_text()

    # The generic device scheduler must retain upstream drain-to-empty
    # semantics; MSC pacing belongs to MSC.
    assert "CFG_TUD_MAX_EVENTS_PER_TASK" not in config
    assert "CFG_TUD_MAX_EVENTS_PER_TASK" not in usbd
    assert "#define CFG_TUD_MSC_DEFERRED_WRITE_RETRY 1" in config

    # WRITE10 BUSY owns its buffered bytes until the bootloader explicitly
    # retries them. READ10 retains TinyUSB's existing behavior; this
    # bootloader's read callback is synchronous and never returns BUSY.
    write_start = msc.rindex("static void proc_write10_new_data(")
    write_body = msc[write_start : msc.index("\n#endif", write_start)]
    deferred_start = write_body.index("#if CFG_TUD_MSC_DEFERRED_WRITE_RETRY")
    deferred_end = write_body.index("#else", deferred_start)
    deferred_body = write_body[deferred_start:deferred_end]
    assert "dcd_event_xfer_complete" not in deferred_body
    assert "write10_retry_pending = true" in deferred_body
    assert "write10_retry_bytes = xferred_bytes-nbytes" in deferred_body
    assert "write10_retry_generation = next_write10_retry_generation()" in deferred_body
    assert "dcd_event_xfer_complete" in write_body[deferred_end:]
    assert "bool tud_msc_write10_retry_snapshot(uint32_t* generation)" in msc
    assert "bool tud_msc_write10_retry(uint32_t generation)" in msc
    assert "p_msc->write10_retry_generation != generation" in msc
    assert "bool tud_msc_write10_retry_snapshot(uint32_t* generation);" in msc_header
    assert "bool tud_msc_write10_retry(uint32_t generation);" in msc_header

    reset_start = msc.index("static void proc_bot_reset")
    reset_body = msc[reset_start : msc.index("// Invoked when", reset_start)]
    assert "clear_write10_retry(p_msc);" in reset_body
    fail_start = msc.index("static void fail_scsi_op")
    fail_body = msc[fail_start : msc.index("static inline uint32_t", fail_start)]
    assert "clear_write10_retry(p_msc);" in fail_body

    # A retry generated in the current tud_task() pass must wait for the next
    # pass. Real control/CDC events are fully drained before a prior retry runs.
    snapshot = bootloader.index(
        "tud_msc_write10_retry_snapshot(&msc_retry_generation);"
    )
    task = bootloader.index("tud_task();", snapshot)
    cdc_flush = bootloader.index("tud_cdc_write_flush();", task)
    retry = bootloader.index(
        "if (msc_retry_pending) tud_msc_write10_retry(msc_retry_generation);",
        cdc_flush,
    )
    assert snapshot < task < cdc_flush < retry

    # Keep the hardware-proven synchronous full-page erase; only its retry
    # scheduling changes. The former partial-NVMC state must stay absent.
    for source in (flash, flash_header, ghostfat):
        assert "flash_nrf5x_erase_step" not in source
    for stale_state in (
        "appEraseAddress",
        "appEraseInProgress",
        "bootloaderEraseInProgress",
    ):
        assert stale_state not in uf2_header
        assert stale_state not in ghostfat

    staging_start = ghostfat.index("static bool erase_bootloader_staging")
    staging_end = ghostfat.index("static bool prepare_app_block", staging_start)
    staging_source = ghostfat[staging_start:staging_end]
    assert staging_source.count("flash_nrf5x_erase(") == 1
    assert "return false;" in staging_source[staging_source.index("flash_nrf5x_erase(") :]

    # Ten staging-page erases require ten separate loop passes. Control and CDC
    # events queued beside the initial WRITE are handled in the first pass, and
    # events arriving during later flash work are handled before the next retry.
    model = MscRetryModel(busy_flash_steps=10)
    model.events.extend(("write", "control", "cdc"))
    model.pass_once()
    assert model.handled == ["control", "cdc"]
    assert model.pending

    while model.pending:
        model.events.extend(("control", "cdc"))
        model.pass_once()

    assert model.handled.count("control") == 11
    assert model.handled.count("cdc") == 11
    assert model.handled[-1] == "write-complete"
    assert len(model.flash_ms_each_pass) == 11
    assert max(model.flash_ms_each_pass) == NRF52840_PAGE_ERASE_MS
    assert sum(model.flash_ms_each_pass) == 10 * NRF52840_PAGE_ERASE_MS

    # A BOT/bus reset can be queued after the main loop snapshots a retry. If
    # tud_task() accepts a new WRITE in that same pass, the stale snapshot must
    # not consume or advance the new command. The generation, unlike a boolean,
    # distinguishes those two pieces of work.
    model = MscRetryModel(busy_flash_steps=3)
    model.events.append("write")
    model.pass_once()
    first_generation = model.pending_generation
    assert first_generation != 0

    model.events.extend(("reset", "write", "control"))
    model.pass_once()
    assert model.pending_generation != 0
    assert model.pending_generation != first_generation
    assert model.stale_retries == 1
    assert model.handled == ["control"]
    assert max(model.flash_ms_each_pass) == NRF52840_PAGE_ERASE_MS

    while model.pending:
        model.pass_once()
    assert model.handled[-1] == "write-complete"
    assert max(model.flash_ms_each_pass) == NRF52840_PAGE_ERASE_MS

    print(
        "USB MSC retry regression passed: real events drain first, "
        f"{max(model.flash_ms_each_pass)} ms max deferred flash per loop"
    )


if __name__ == "__main__":
    main()
