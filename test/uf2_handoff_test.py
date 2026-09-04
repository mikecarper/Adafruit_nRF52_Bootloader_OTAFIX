#!/usr/bin/env python3
"""Model and source guards for clean UF2 application handoff."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MSC_SOURCE = (ROOT / "src" / "usb" / "msc_uf2.c").read_text()
USB_SOURCE = (ROOT / "src" / "usb" / "usb.c").read_text()
GHOSTFAT_SOURCE = (ROOT / "src" / "usb" / "uf2" / "ghostfat.c").read_text()
TINYUSB_MSC_SOURCE = (
    ROOT / "lib" / "tinyusb" / "src" / "class" / "msc" / "msc_device.c"
).read_text()
TINYUSB_MSC_HEADER = (
    ROOT / "lib" / "tinyusb" / "src" / "class" / "msc" / "msc_device.h"
).read_text()

RTC_MASK = (1 << 24) - 1
IDLE_TICKS = 32768
MIN_TICKS = 5


class HandoffModel:
    def __init__(self) -> None:
        self.pending = False
        self.after_eject = False
        self.command_active = False
        self.aborted = False
        self.last_activity = 0
        self.timer_due = None
        self.completions = 0

    @staticmethod
    def diff(now: int, before: int) -> int:
        return (now - before) & RTC_MASK

    def defer(self, now: int) -> None:
        self.last_activity = now
        if self.pending:
            return
        self.pending = True
        self.timer_due = (now + IDLE_TICKS) & RTC_MASK

    def command_begin(self, now: int) -> None:
        self.command_active = True
        if self.pending:
            self.last_activity = now

    def command_complete(self, now: int, *, eject: bool = False) -> None:
        # TinyUSB invokes the command-specific completion first. Eject can take
        # the pending image there; the generic lifecycle callback then releases
        # the CBW-to-CSW guard.
        if eject and self.after_eject:
            self.take()
        self.command_active = False
        if self.pending:
            self.last_activity = now

    def timer(self, now: int) -> None:
        if not self.pending:
            return
        if self.command_active:
            self.last_activity = now
            self.timer_due = (now + IDLE_TICKS) & RTC_MASK
            return
        elapsed = self.diff(now, self.last_activity)
        if elapsed + MIN_TICKS < IDLE_TICKS:
            self.timer_due = (now + IDLE_TICKS - elapsed) & RTC_MASK
            return
        self.take()

    def request_eject(self) -> None:
        self.after_eject = self.pending

    def transport_reset(self, now: int) -> None:
        # BOT/bus reset abandons a command without blessing or cancelling an
        # otherwise complete application image.
        self.command_active = False
        self.after_eject = False
        if self.pending:
            self.last_activity = now

    def reset(self) -> None:
        self.pending = False
        self.after_eject = False
        self.command_active = False

    def close(self) -> None:
        if self.pending:
            self.take()
        self.reset()

    def take(self) -> None:
        can_complete = self.pending and not self.aborted
        self.pending = False
        self.after_eject = False
        if can_complete:
            self.completions += 1


def source_guards() -> None:
    compact_condition = (
        "defined(MOTA_INTERNAL_BOOTLOADER_UPDATE) || \\\n"
        "    defined(MOTA_QSPI_BOOTLOADER_UPDATE) || \\\n"
        "    defined(MOTA_SD_BOOTLOADER_UPDATE)"
    )
    if compact_condition not in GHOSTFAT_SOURCE:
        raise AssertionError("every self-update backend must use the compact recovery volume")
    for required in (
        "#define UF2_COMPACT_RECOVERY_VOLUME 1",
        "#define NUM_FILES 0U",
        "SoftDevice expected: S",
        "#if defined(UF2_HAS_CURRENT_FILE)",
    ):
        if required not in GHOSTFAT_SOURCE:
            raise AssertionError(f"missing compact-volume guard: {required}")
    for obsolete in ("utoa(", "strcat("):
        if obsolete in GHOSTFAT_SOURCE:
            raise AssertionError(f"runtime INFO_UF2 formatter survived: {obsolete}")

    callback_start = MSC_SOURCE.index("void tud_msc_write10_complete_cb")
    callback_end = MSC_SOURCE.index("void tud_msc_scsi_complete_cb", callback_start)
    write_complete = MSC_SOURCE[callback_start:callback_end]
    app_branch = write_complete[write_complete.index("}else"):]
    if "defer_app_completion();" not in app_branch:
        raise AssertionError("application UF2 completion must enter the idle handoff")
    if app_branch.index("defer_app_completion();") >= app_branch.index("return;"):
        raise AssertionError("application completion must return before the immediate reset path")

    boot_branch_start = write_complete.index(
        "if ( _wr_state.updateKind == UF2_UPDATE_KIND_BOOTLOADER )"
    )
    boot_branch_end = write_complete.index("}else", boot_branch_start)
    boot_branch = write_complete[boot_branch_start:boot_branch_end]
    for required in ("SD_MBR_COMMAND_COPY_BL", "sd_mbr_command(&command);"):
        if required not in boot_branch:
            raise AssertionError("bootloader UF2 must retain immediate COPY_BL semantics")

    for required in (
        "APP_TIMER_DEF(_app_completion_timer);",
        "app_timer_cnt_diff_compute(now, _app_completion_last_activity)",
        "UF2_APP_COMPLETION_IDLE_TICKS - idle_ticks",
        "if (_app_msc_command_active)",
        "void tud_msc_command_begin_cb",
        "void tud_msc_command_complete_cb",
        "void tud_msc_reset_cb",
        "_app_completion_last_activity = app_timer_cnt_get();",
        "case 0x35: // SCSI SYNCHRONIZE CACHE (10)",
        "void tud_msc_scsi_complete_cb",
        "take_pending_app_completion()",
    ):
        if required not in MSC_SOURCE:
            raise AssertionError(f"missing clean-handoff guard: {required}")

    for stale_guard in ("_app_write10_active", "_app_scsi_status_active"):
        if stale_guard in MSC_SOURCE:
            raise AssertionError(f"narrow command guard survived: {stale_guard}")

    begin = MSC_SOURCE[
        MSC_SOURCE.index("void tud_msc_command_begin_cb") :
        MSC_SOURCE.index("void tud_msc_command_complete_cb")
    ]
    complete = MSC_SOURCE[
        MSC_SOURCE.index("void tud_msc_command_complete_cb") :
        MSC_SOURCE.index("void tud_msc_reset_cb")
    ]
    reset = MSC_SOURCE[
        MSC_SOURCE.index("void tud_msc_reset_cb") :
        MSC_SOURCE.index("// tinyusb callbacks")
    ]
    if "_app_msc_command_active = true;" not in begin:
        raise AssertionError("every accepted CBW must open the command guard")
    if "_app_msc_command_active = false;" not in complete:
        raise AssertionError("an accepted CSW must close the command guard")
    if "_app_msc_command_active = false;" not in reset:
        raise AssertionError("transport reset must release an abandoned command")
    if "_app_completion_after_eject = false;" not in reset:
        raise AssertionError("transport reset must cancel an incomplete eject")
    if "_app_completion_pending = false" in reset or "take_pending_app_completion" in reset:
        raise AssertionError("transport reset must not bless or cancel a complete image")

    for declaration in (
        "tud_msc_command_begin_cb(uint8_t lun, uint8_t const scsi_cmd[16]);",
        "tud_msc_command_complete_cb(uint8_t lun, uint8_t const scsi_cmd[16]);",
        "tud_msc_reset_cb(void);",
    ):
        if declaration not in TINYUSB_MSC_HEADER:
            raise AssertionError(f"missing TinyUSB lifecycle API: {declaration}")

    cbw_valid = TINYUSB_MSC_SOURCE.index(
        "xferred_bytes == sizeof(msc_cbw_t) && p_cbw->signature == MSC_CBW_SIGNATURE"
    )
    command_begin = TINYUSB_MSC_SOURCE.index(
        "if (tud_msc_command_begin_cb) tud_msc_command_begin_cb", cbw_valid
    )
    parse_command = TINYUSB_MSC_SOURCE.index(
        "/*------------- Parse command and prepare DATA -------------*/", command_begin
    )
    if not cbw_valid < command_begin < parse_command:
        raise AssertionError("command guard must begin after validation and before SCSI work")

    specialized_complete = TINYUSB_MSC_SOURCE.index(
        "switch(p_cbw->command[0])", command_begin
    )
    command_complete = TINYUSB_MSC_SOURCE.index(
        "if (tud_msc_command_complete_cb) tud_msc_command_complete_cb",
        specialized_complete,
    )
    next_cbw = TINYUSB_MSC_SOURCE.index(
        "TU_ASSERT( prepare_cbw(rhport, p_msc) );", command_complete
    )
    if not specialized_complete < command_complete < next_cbw:
        raise AssertionError("command guard must end after specialized completion and before next CBW")
    if TINYUSB_MSC_SOURCE.count("if (tud_msc_reset_cb) tud_msc_reset_cb();") < 2:
        raise AssertionError("both BOT and USB bus resets must abandon command state")

    sync_case = MSC_SOURCE[
        MSC_SOURCE.index("case 0x35: // SCSI SYNCHRONIZE CACHE (10)") :
        MSC_SOURCE.index("default:", MSC_SOURCE.index("case 0x35: // SCSI SYNCHRONIZE CACHE (10)"))
    ]
    if "_app_completion_after_eject" in sync_case or "take_pending_app_completion" in sync_case:
        raise AssertionError("SYNCHRONIZE CACHE must not authorize immediate completion")

    scsi_complete = MSC_SOURCE[
        MSC_SOURCE.index("void tud_msc_scsi_complete_cb") :
        MSC_SOURCE.index("void tud_msc_capacity_cb")
    ]
    sync_complete = scsi_complete[
        scsi_complete.index("if (scsi_cmd[0] == 0x35)") :
        scsi_complete.index("if (_app_completion_after_eject")
    ]
    if "take_pending_app_completion" in sync_complete or "complete_app_update" in sync_complete:
        raise AssertionError("SYNCHRONIZE CACHE CSW must only restart the idle interval")

    init = USB_SOURCE.index("uf2_init();")
    session_init = USB_SOURCE.index("uf2_write_session_init();", init)
    tusb_init = USB_SOURCE.index("tusb_init();", session_init)
    if not init < session_init < tusb_init:
        raise AssertionError("handoff timer must be initialized before TinyUSB callbacks")
    umount = USB_SOURCE.index("void tud_umount_cb")
    if "uf2_write_session_close();" not in USB_SOURCE[umount:]:
        raise AssertionError("physical disconnect must commit a complete application")

    # The handoff fix must not weaken the hardware-proven erase pacing.
    staging = GHOSTFAT_SOURCE[
        GHOSTFAT_SOURCE.index("static bool erase_bootloader_staging") :
        GHOSTFAT_SOURCE.index("static bool prepare_app_block")
    ]
    if staging.count("flash_nrf5x_erase(") != 1 or "return false;" not in staging:
        raise AssertionError("bootloader staging must still erase one page per retry")
    app_erase = GHOSTFAT_SOURCE[
        GHOSTFAT_SOURCE.index("case UF2_APP_FLASH_ERASE_PAGE:") :
        GHOSTFAT_SOURCE.index("case UF2_APP_FLASH_PROGRAM_BLOCK:")
    ]
    if "flash_nrf5x_erase(block->targetAddr, CODE_PAGE_SIZE);" not in app_erase:
        raise AssertionError("application UF2 must retain complete-page erasure")


def behavior_regressions() -> None:
    # The final data status alone cannot complete the update. Later metadata
    # writes move the idle deadline without issuing timer stop/start per sector.
    model = HandoffModel()
    model.defer(100)
    model.command_complete(100)
    assert model.pending and model.completions == 0
    model.command_begin(100 + IDLE_TICKS // 2)
    model.timer(100 + IDLE_TICKS)
    assert model.pending and model.completions == 0
    assert model.timer_due == 100 + 2 * IDLE_TICKS
    model.command_complete(100 + IDLE_TICKS + IDLE_TICKS // 2)
    model.timer(model.timer_due)
    assert model.pending and model.completions == 0
    model.timer(model.timer_due)
    assert not model.pending and model.completions == 1

    # A subsequent host WRITE10 can span many 4 KiB chunks and take longer than
    # the fallback interval. It remains guarded from CBW acceptance until its
    # CSW, then receives one complete idle window.
    model = HandoffModel()
    model.defer(100)
    model.command_begin(200)
    model.timer(100 + IDLE_TICKS)
    assert model.pending and model.completions == 0
    model.timer(model.timer_due)
    assert model.pending and model.completions == 0
    command_complete = model.timer_due + 100
    model.command_complete(command_complete)
    model.timer(command_complete + IDLE_TICKS)
    assert not model.pending and model.completions == 1

    # The lifecycle must cover commands that never call WRITE10 hooks. READ10
    # and built-in commands (for example INQUIRY/TUR) crossing the idle deadline
    # each defer handoff until their CSW plus one full quiet interval.
    for command_name in ("READ10", "INQUIRY", "TEST UNIT READY"):
        model = HandoffModel()
        model.defer(100)
        model.command_begin(200)
        model.timer(100 + IDLE_TICKS)
        assert model.pending and model.completions == 0, command_name
        completed_at = model.timer_due + 100
        model.command_complete(completed_at)
        model.timer(completed_at + IDLE_TICKS)
        assert not model.pending and model.completions == 1, command_name

    # A delayed WRITE10 is guarded from its CBW, before the first OUT data packet
    # reaches the application callback. That closes the old pre-data idle race.
    model = HandoffModel()
    model.defer(100)
    model.command_begin(100 + IDLE_TICKS - 10)
    model.timer(100 + IDLE_TICKS)
    assert model.pending and model.completions == 0
    completed_at = model.timer_due + 10
    model.command_complete(completed_at)
    model.timer(completed_at + IDLE_TICKS)
    assert not model.pending and model.completions == 1

    # Linux can complete SYNCHRONIZE CACHE while additional virtual-FAT bios
    # remain queued. Its CSW is activity, never an immediate-reset boundary.
    model = HandoffModel()
    model.defer(500)
    model.command_begin(600)
    model.timer(500 + IDLE_TICKS)
    assert model.pending and model.completions == 0
    sync_complete = model.timer_due + 100
    model.command_complete(sync_complete)
    assert model.pending and model.completions == 0
    model.timer(sync_complete + IDLE_TICKS)
    assert not model.pending and model.completions == 1

    # Explicit media eject can complete, but only after its CSW reached the
    # host; a repeated completion callback cannot bless the image twice.
    model = HandoffModel()
    model.defer(500)
    model.command_begin(600)
    model.request_eject()
    assert model.pending and model.completions == 0
    model.command_complete(700, eject=True)
    assert not model.pending and model.completions == 1
    model.command_complete(800, eject=True)
    assert model.completions == 1

    # BOT/bus reset abandons an active command without a CSW. It must clear an
    # incomplete eject and release the guard, while preserving a fully received
    # application's pending handoff so the next quiet interval can complete it.
    model = HandoffModel()
    model.defer(500)
    model.command_begin(600)
    model.request_eject()
    model.timer(500 + IDLE_TICKS)
    assert model.pending and model.command_active
    reset_at = model.timer_due + 100
    model.transport_reset(reset_at)
    assert model.pending and not model.command_active and not model.after_eject
    model.timer(reset_at + IDLE_TICKS)
    assert not model.pending and model.completions == 1

    # A physical disconnect safely commits a complete image, while an explicit
    # session reset/abort cancels a pending handoff and leaves it invalid.
    model = HandoffModel()
    model.defer(700)
    model.close()
    assert model.completions == 1 and not model.pending
    model = HandoffModel()
    model.defer(700)
    model.aborted = True
    model.close()
    model.timer(700 + IDLE_TICKS)
    assert model.completions == 0 and not model.pending
    model = HandoffModel()
    model.defer(700)
    model.reset()
    model.timer(700 + IDLE_TICKS)
    assert model.completions == 0 and not model.pending

    # app_timer_cnt_diff_compute is 24-bit wrap-safe; pin that contract around
    # the RTC rollover so long-running bootloader sessions cannot hang.
    model = HandoffModel()
    start = RTC_MASK - 100
    model.defer(start)
    model.timer((start + IDLE_TICKS) & RTC_MASK)
    assert model.completions == 1 and not model.pending


if __name__ == "__main__":
    source_guards()
    behavior_regressions()
    print("UF2 clean application-handoff regression passed")
