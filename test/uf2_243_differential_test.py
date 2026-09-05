#!/usr/bin/env python3
"""Synthetic A/B regression for the OTAFIX 2.4.3 application-UF2 failure.

The injected partial-NVMC disconnect is derived from the physical 2.4.3
failure. This model proves the old policy reaches that failing operation after
invalidating the application and proves the current policy cannot reach it.
It does not claim to emulate the nRF52840 USB/NVMC peripherals electrically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import hashlib
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
OTAFIX_243_TAG = "0.11.0-OTAFIX2.4.3"
OTAFIX_243_COMMIT = "243b061f60130b8f2d0b930af6c49955be8ca537"
OTAFIX_243_GHOSTFAT_SHA256 = (
    "bd924cc68756c5ff4b63e51e9f82d2ea9ebd46112cf4d7021f07ed29846f4c87"
)
OTAFIX_243_FLASH_SHA256 = (
    "fb2e1f7b6952ded5ffb4ec8fb41b4bc066b29306841c308b6eb7654113534a4e"
)


class UsbDisconnected(RuntimeError):
    """The hardware-derived partial-erase fault removed the MSC device."""


class CallbackResult(Enum):
    BUSY = auto()
    COMPLETE = auto()


@dataclass
class ApplicationState:
    settings_invalidated: bool = False
    page_marked_erased: bool = False
    erase_in_progress: bool = False


class NvmcFaultOracle:
    """Minimal flash oracle with an optional first-partial-operation fault."""

    def __init__(self, disconnect_on_partial: bool) -> None:
        self.disconnect_on_partial = disconnect_on_partial
        self.connected = True
        self.settings_valid = True
        self.partial_calls = 0
        self.partial_steps_remaining = 43
        self.full_page_calls = 0
        self.program_calls = 0

    def invalidate_settings(self) -> None:
        self.settings_valid = False

    def partial_page_erase(self) -> bool:
        self.partial_calls += 1
        if self.disconnect_on_partial:
            self.connected = False
            raise UsbDisconnected("MSC disappeared during partial NVMC erase")
        self.partial_steps_remaining -= 1
        return self.partial_steps_remaining == 0

    def full_page_erase(self) -> None:
        self.full_page_calls += 1

    def program_block(self) -> None:
        if not self.connected:
            raise UsbDisconnected("cannot program after USB disconnect")
        self.program_calls += 1

    def finalize_single_block_image(self) -> None:
        if self.program_calls != 1:
            raise AssertionError("synthetic image was not completely programmed")
        self.settings_valid = True


def next_action(state: ApplicationState) -> str:
    if not state.settings_invalidated:
        state.settings_invalidated = True
        return "invalidate"
    if not state.page_marked_erased:
        state.page_marked_erased = True
        return "erase"
    return "program"


def legacy_243_callback(
    state: ApplicationState, flash: NvmcFaultOracle
) -> CallbackResult:
    """Model 2.4.3's prepare_app_block() state machine exactly."""
    if state.erase_in_progress:
        if flash.partial_page_erase():
            state.erase_in_progress = False
        return CallbackResult.BUSY

    action = next_action(state)
    if action == "invalidate":
        flash.invalidate_settings()
        return CallbackResult.BUSY
    if action == "erase":
        state.erase_in_progress = not flash.partial_page_erase()
        return CallbackResult.BUSY
    flash.program_block()
    return CallbackResult.COMPLETE


def current_244_callback(
    state: ApplicationState, flash: NvmcFaultOracle
) -> CallbackResult:
    """Model 2.4.4's complete-page prepare_app_block() policy."""
    action = next_action(state)
    if action == "invalidate":
        flash.invalidate_settings()
        return CallbackResult.BUSY
    if action == "erase":
        flash.full_page_erase()
        return CallbackResult.BUSY
    flash.program_block()
    return CallbackResult.COMPLETE


def run_single_block_image(callback, flash: NvmcFaultOracle) -> bool:
    state = ApplicationState()
    try:
        for _ in range(100):
            if callback(state, flash) == CallbackResult.COMPLETE:
                flash.finalize_single_block_image()
                return True
    except UsbDisconnected:
        return False
    raise AssertionError("synthetic UF2 callback never completed")


def git_blob(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{OTAFIX_243_TAG}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


class HistoricalSourceTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / ".git").exists(), "Git history is not available")
    def test_model_is_bound_to_exact_243_sources(self) -> None:
        commit = subprocess.run(
            ["git", "rev-list", "-n", "1", OTAFIX_243_TAG],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(commit, OTAFIX_243_COMMIT)

        ghostfat = git_blob("src/usb/uf2/ghostfat.c")
        flash = git_blob("src/flash_nrf5x.c")
        self.assertEqual(
            hashlib.sha256(ghostfat).hexdigest(), OTAFIX_243_GHOSTFAT_SHA256
        )
        self.assertEqual(hashlib.sha256(flash).hexdigest(), OTAFIX_243_FLASH_SHA256)
        self.assertIn(b"state->appEraseInProgress", ghostfat)
        self.assertIn(b"flash_nrf5x_erase_step(block->targetAddr, true)", ghostfat)
        self.assertIn(b"nrfx_nvmc_page_partial_erase_init", flash)
        self.assertIn(b"nrfx_nvmc_page_partial_erase_continue", flash)

    def test_current_source_uses_only_complete_application_page_erase(self) -> None:
        ghostfat = (ROOT / "src/usb/uf2/ghostfat.c").read_text(encoding="ascii")
        flash = (ROOT / "src/flash_nrf5x.c").read_text(encoding="ascii")
        flash_header = (ROOT / "src/flash_nrf5x.h").read_text(encoding="ascii")
        app_erase = ghostfat[
            ghostfat.index("case UF2_APP_FLASH_ERASE_PAGE:") :
            ghostfat.index("case UF2_APP_FLASH_PROGRAM_BLOCK:")
        ]
        self.assertIn(
            "flash_nrf5x_erase(block->targetAddr, CODE_PAGE_SIZE);", app_erase
        )
        for source in (ghostfat, flash, flash_header):
            self.assertNotIn("flash_nrf5x_erase_step", source)
            self.assertNotIn("nrfx_nvmc_page_partial_erase", source)


class DifferentialBehaviorTests(unittest.TestCase):
    def test_243_fault_disconnects_after_invalidation_before_programming(self) -> None:
        flash = NvmcFaultOracle(disconnect_on_partial=True)
        self.assertFalse(run_single_block_image(legacy_243_callback, flash))
        self.assertFalse(flash.connected)
        self.assertFalse(flash.settings_valid)
        self.assertEqual(flash.partial_calls, 1)
        self.assertEqual(flash.full_page_calls, 0)
        self.assertEqual(flash.program_calls, 0)

    def test_244_avoids_fault_and_completes_same_synthetic_image(self) -> None:
        flash = NvmcFaultOracle(disconnect_on_partial=True)
        self.assertTrue(run_single_block_image(current_244_callback, flash))
        self.assertTrue(flash.connected)
        self.assertTrue(flash.settings_valid)
        self.assertEqual(flash.partial_calls, 0)
        self.assertEqual(flash.full_page_calls, 1)
        self.assertEqual(flash.program_calls, 1)

    def test_243_model_completes_when_fault_is_not_injected(self) -> None:
        flash = NvmcFaultOracle(disconnect_on_partial=False)
        self.assertTrue(run_single_block_image(legacy_243_callback, flash))
        self.assertTrue(flash.connected)
        self.assertEqual(flash.partial_calls, 43)
        self.assertEqual(flash.program_calls, 1)


if __name__ == "__main__":
    unittest.main()
