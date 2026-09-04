#!/usr/bin/env python3
"""Host-only tests for the strict OTAFIX Legacy BLE DFU client."""

from __future__ import annotations

import asyncio
import binascii
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "otafix_legacy_ble_dfu", ROOT / "tools" / "otafix_legacy_ble_dfu.py"
)
assert SPEC is not None and SPEC.loader is not None
dfu = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dfu
SPEC.loader.exec_module(dfu)


def make_package(
    directory: Path,
    kind: str,
    *,
    unsafe_bin_name: str | None = None,
    extra_member: bool = False,
    corrupt_init_crc: bool = False,
    softdevice_req_count: int = 1,
    duplicate_manifest_key: bool = False,
    signed: bool = False,
    corrupt_init_hash: bool = False,
) -> tuple[Path, str]:
    if kind == "application":
        firmware = bytes((index * 17 + 3) & 0xFF for index in range(1024))
        item_extra: dict[str, int] = {}
    elif kind == "softdevice_bootloader":
        sd_size = 32
        firmware = bytes(
            (index * 29 + 7) & 0xFF
            for index in range(sd_size + dfu.OTAFIX_BOOTLOADER_BYTES)
        )
        item_extra = {"sd_size": sd_size, "bl_size": dfu.OTAFIX_BOOTLOADER_BYTES}
    else:
        raise AssertionError(kind)

    device_type = 82
    device_revision = 52840
    app_version = 0xFFFFFFFF
    softdevice_req = [0xFFFE] * softdevice_req_count
    crc = binascii.crc_hqx(firmware, 0xFFFF)
    packet_crc = crc ^ 1 if corrupt_init_crc else crc
    init_base = (
        struct.pack(
            "<HHIH",
            device_type,
            device_revision,
            app_version,
            len(softdevice_req),
        )
        + struct.pack(f"<{len(softdevice_req)}H", *softdevice_req)
    )
    if signed:
        firmware_hash = hashlib.sha256(firmware).digest()
        packet_hash = (
            bytes((firmware_hash[0] ^ 1,)) + firmware_hash[1:]
            if corrupt_init_hash
            else firmware_hash
        )
        signature = bytes((index * 11 + 5) & 0xFF for index in range(64))
        init_packet = init_base + struct.pack(
            "<II32s64s", 2, len(firmware), packet_hash, signature
        )
        init_metadata = {
            "application_version": app_version,
            "device_revision": device_revision,
            "device_type": device_type,
            "ext_packet_id": 2,
            "firmware_hash": packet_hash.hex(),
            "firmware_length": len(firmware),
            "init_packet_ecds": signature.hex(),
            "softdevice_req": softdevice_req,
        }
        dfu_version = 0.8
    else:
        init_packet = init_base + struct.pack("<H", packet_crc)
        init_metadata = {
            "application_version": app_version,
            "device_revision": device_revision,
            "device_type": device_type,
            "firmware_crc16": packet_crc,
            "softdevice_req": softdevice_req,
        }
        dfu_version = 0.5
    bin_name = unsafe_bin_name or "firmware.bin"
    dat_name = "firmware.dat"
    item = {
        "bin_file": bin_name,
        "dat_file": dat_name,
        "init_packet_data": init_metadata,
        **item_extra,
    }
    manifest = {"manifest": {"dfu_version": dfu_version, kind: item}}
    manifest_text = json.dumps(manifest)
    if duplicate_manifest_key:
        inner = json.dumps(manifest["manifest"])
        manifest_text = f'{{"manifest":{inner},"manifest":{inner}}}'
    path = directory / f"{kind}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_text)
        archive.writestr(bin_name, firmware)
        archive.writestr(dat_name, init_packet)
        if extra_member:
            archive.writestr("unreferenced.bin", b"not selected")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeTransport:
    """Deterministic target that implements just the Legacy DFU wire contract."""

    def __init__(
        self,
        total_firmware: int,
        clock: FakeClock,
        *,
        packet_seconds: float = 0.010,
        receipt_delta: int = 0,
        drop_first_receipt: bool = False,
        duplicate_first_receipt: bool = False,
        omit_final_receipt: bool = True,
        final_response_seconds: float = 0.0,
    ) -> None:
        self.total_firmware = total_firmware
        self.clock = clock
        self.packet_seconds = packet_seconds
        self.receipt_delta = receipt_delta
        self.drop_first_receipt = drop_first_receipt
        self.duplicate_first_receipt = duplicate_first_receipt
        self.omit_final_receipt = omit_final_receipt
        self.final_response_seconds = final_response_seconds
        self.session = None
        self.stage = "idle"
        self.mode = None
        self.sizes = None
        self.prn = 0
        self.prn_history: list[int] = []
        self.window_packets = 0
        self.received = 0
        self.receive_packets = 0
        self.receipts_emitted = 0
        self.activated = False

    def bind(self, session) -> None:
        self.session = session

    def notify_response(self, opcode: int, result: int = dfu.RESULT_SUCCESS) -> None:
        assert self.session is not None
        self.session.notification(None, bytes((dfu.OP_RESPONSE, opcode, result)))

    async def write_control(self, payload: bytes) -> None:
        opcode = payload[0]
        if opcode == dfu.OP_START:
            self.mode = payload[1]
            self.stage = "start_size"
        elif opcode == dfu.OP_INITIALIZE and payload[1] == 0:
            self.stage = "init"
        elif opcode == dfu.OP_INITIALIZE and payload[1] == 1:
            self.stage = "idle"
            self.notify_response(dfu.OP_INITIALIZE)
        elif opcode == dfu.OP_PRN_REQUEST:
            self.prn = struct.unpack_from("<H", payload, 1)[0]
            self.prn_history.append(self.prn)
            self.window_packets = 0
        elif opcode == dfu.OP_RECEIVE:
            self.stage = "receive"
            self.window_packets = 0
        elif opcode == dfu.OP_VALIDATE:
            if self.received != self.total_firmware:
                self.notify_response(dfu.OP_VALIDATE, 0x05)
            else:
                self.notify_response(dfu.OP_VALIDATE)
        elif opcode == dfu.OP_ACTIVATE_RESET:
            self.activated = True
        else:
            raise AssertionError(f"unexpected control payload {payload.hex()}")

    async def write_packet(self, payload: bytes) -> None:
        if self.stage == "start_size":
            self.sizes = struct.unpack("<III", payload)
            self.stage = "idle"
            self.notify_response(dfu.OP_START)
            return
        if self.stage == "init":
            return
        if self.stage != "receive":
            raise AssertionError(f"packet in stage {self.stage}")

        self.clock.advance(self.packet_seconds)
        self.received += len(payload)
        self.receive_packets += 1
        self.window_packets += 1
        final_packet = self.received == self.total_firmware
        if self.prn and self.window_packets == self.prn:
            self.receipts_emitted += 1
            if not (
                (self.drop_first_receipt and self.receipts_emitted == 1)
                or (self.omit_final_receipt and final_packet)
            ):
                assert self.session is not None
                count = self.received + self.receipt_delta
                self.session.notification(
                    None, bytes((dfu.OP_PRN,)) + struct.pack("<I", count)
                )
                if self.duplicate_first_receipt and self.receipts_emitted == 1:
                    self.session.notification(
                        None, bytes((dfu.OP_PRN,)) + struct.pack("<I", count)
                    )
            self.window_packets = 0
        if final_packet:
            if self.final_response_seconds:
                async def delayed_final_response() -> None:
                    await asyncio.sleep(0)
                    self.clock.advance(self.final_response_seconds)
                    self.notify_response(dfu.OP_RECEIVE)

                asyncio.create_task(delayed_final_response())
            else:
                self.notify_response(dfu.OP_RECEIVE)


def synthetic_package(kind: str, firmware: bytes) -> object:
    if kind == "application":
        return dfu.Package(
            kind=kind,
            mode=dfu.MODE_APPLICATION,
            firmware=firmware,
            init_packet=b"0123456789abcd",
            softdevice_size=0,
            bootloader_size=0,
            application_size=len(firmware),
            sha256="0" * 64,
        )
    return dfu.Package(
        kind=kind,
        mode=dfu.MODE_SD_BOOTLOADER,
        firmware=firmware,
        init_packet=b"0123456789abcd",
        softdevice_size=len(firmware) - dfu.OTAFIX_BOOTLOADER_BYTES,
        bootloader_size=dfu.OTAFIX_BOOTLOADER_BYTES,
        application_size=0,
        sha256="0" * 64,
    )


class CliTests(unittest.TestCase):
    def test_nonfinite_timeouts_are_rejected_before_ble_work(self) -> None:
        base = [
            "--address", "AA:BB:CC:DD:EE:FF",
            "--expected-name", "TEST_DFU",
            "--package", "unused.zip",
            "--sha256", "0" * 64,
            "--expected-model", "TEST",
        ]
        options = (
            "--timeout",
            "--receipt-timeout",
            "--scan-timeout",
            "--connect-timeout",
            "--activation-timeout",
        )
        for option in options:
            for value in ("nan", "inf", "-inf"):
                with self.subTest(option=option, value=value):
                    with mock.patch.object(dfu.asyncio, "run") as run:
                        self.assertEqual(dfu.main([*base, f"{option}={value}"]), 2)
                        run.assert_not_called()

    def test_lab_pre_start_pause_must_be_finite_and_nonnegative(self) -> None:
        base = [
            "--address", "AA:BB:CC:DD:EE:FF",
            "--expected-name", "TEST_DFU",
            "--package", "unused.zip",
            "--sha256", "0" * 64,
            "--expected-model", "TEST",
        ]
        for value in ("-1", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with mock.patch.object(dfu.asyncio, "run") as run:
                    self.assertEqual(
                        dfu.main(
                            [*base, f"--lab-pre-start-pause={value}"]
                        ),
                        2,
                    )
                    run.assert_not_called()

        def close_coroutine(coroutine: object) -> None:
            coroutine.close()

        with mock.patch.object(
            dfu.asyncio, "run", side_effect=close_coroutine
        ) as run:
            self.assertEqual(
                dfu.main([*base, "--lab-pre-start-pause=0"]), 0
            )
            run.assert_called_once()


class LabPreStartPauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_pause_has_no_async_delay(self) -> None:
        client = mock.Mock(is_connected=True)
        disconnected = asyncio.Event()
        with mock.patch.object(
            dfu.asyncio, "sleep", new=mock.AsyncMock()
        ) as sleep:
            await dfu.lab_pre_start_pause(0, client, disconnected)
        sleep.assert_not_awaited()

    async def test_disconnect_during_pause_fails_before_start(self) -> None:
        client = mock.Mock(is_connected=True)
        disconnected = asyncio.Event()

        async def disconnect(_seconds: float) -> None:
            disconnected.set()

        with mock.patch.object(dfu.asyncio, "sleep", side_effect=disconnect):
            with self.assertRaisesRegex(
                dfu.DfuError, "disconnected during the lab pre-START pause"
            ):
                await dfu.lab_pre_start_pause(1, client, disconnected)


class PackageTests(unittest.TestCase):
    def test_application_package_is_fully_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(Path(temporary), "application")
            package = dfu.read_package(path, digest.upper())
        self.assertEqual(package.kind, "application")
        self.assertEqual(package.mode, dfu.MODE_APPLICATION)
        self.assertEqual(package.application_size, len(package.firmware))
        self.assertEqual(package.softdevice_size, 0)
        self.assertEqual(package.bootloader_size, 0)

    def test_combined_recovery_retains_exact_40k_bootloader_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(Path(temporary), "softdevice_bootloader")
            package = dfu.read_package(path, digest)
        self.assertEqual(package.mode, dfu.MODE_SD_BOOTLOADER)
        self.assertEqual(package.bootloader_size, 0xA000)
        self.assertEqual(
            package.softdevice_size + package.bootloader_size,
            len(package.firmware),
        )
        self.assertEqual(package.application_size, 0)

    def test_wrong_hash_is_rejected_before_archive_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, _digest = make_package(Path(temporary), "application")
            with self.assertRaisesRegex(dfu.DfuError, "SHA-256 mismatch"):
                dfu.read_package(path, "0" * 64)

    def test_unsafe_manifest_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(
                Path(temporary), "application", unsafe_bin_name="../firmware.bin"
            )
            with self.assertRaisesRegex(dfu.DfuError, "unsafe"):
                dfu.read_package(path, digest)

    def test_unreferenced_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(
                Path(temporary), "application", extra_member=True
            )
            with self.assertRaisesRegex(dfu.DfuError, "unreferenced"):
                dfu.read_package(path, digest)

    def test_duplicate_manifest_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(
                Path(temporary), "application", duplicate_manifest_key=True
            )
            with self.assertRaisesRegex(dfu.DfuError, "duplicate JSON key"):
                dfu.read_package(path, digest)

    def test_init_packet_crc_is_verified_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(
                Path(temporary), "application", corrupt_init_crc=True
            )
            with self.assertRaisesRegex(dfu.DfuError, "firmware CRC mismatch"):
                dfu.read_package(path, digest)

    def test_standard_signed_package_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(
                Path(temporary), "softdevice_bootloader", signed=True
            )
            package = dfu.read_package(path, digest)
        self.assertEqual(package.mode, dfu.MODE_SD_BOOTLOADER)
        self.assertEqual(len(package.init_packet), 116)

    def test_signed_init_hash_is_verified_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(
                Path(temporary),
                "application",
                signed=True,
                corrupt_init_hash=True,
            )
            with self.assertRaisesRegex(dfu.DfuError, "firmware hash"):
                dfu.read_package(path, digest)

    def test_init_packet_cannot_exceed_sdk11_target_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # 59 requirements make a 130-byte packet.  Both SDK11 bank
            # implementations have an exact 128-byte init-packet buffer.
            path, digest = make_package(
                Path(temporary), "application", softdevice_req_count=59
            )
            with self.assertRaisesRegex(dfu.DfuError, "init-packet member"):
                dfu.read_package(path, digest)

    def test_archive_is_parsed_from_the_exact_hashed_bytes(self) -> None:
        class ReplacedAfterRead:
            def __init__(self, path: Path) -> None:
                self.path = path

            def stat(self):
                return self.path.stat()

            def read_bytes(self) -> bytes:
                authenticated = self.path.read_bytes()
                # Simulate replacement after the digest input has been read.
                self.path.write_bytes(b"not the authenticated zip")
                return authenticated

        with tempfile.TemporaryDirectory() as temporary:
            path, digest = make_package(Path(temporary), "application")
            package = dfu.read_package(ReplacedAfterRead(path), digest)
        self.assertEqual(package.kind, "application")


class IdentityAndMtuTests(unittest.TestCase):
    class Device:
        def __init__(self, address: str) -> None:
            self.address = address

    class Advertisement:
        def __init__(self, name: str, services: list[str]) -> None:
            self.local_name = name
            self.service_uuids = services

    def test_bleak_3_adapter_uses_non_deprecated_bluez_options(self) -> None:
        class Bleak3Factory:
            def __init__(self, _device, *, bluez=None, **_kwargs) -> None:
                pass

        self.assertEqual(
            dfu.bleak_adapter_kwargs(Bleak3Factory, "hci7"),
            {"bluez": {"adapter": "hci7"}},
        )

    def test_bleak_2_adapter_keeps_legacy_explicit_adapter(self) -> None:
        class Bleak2Factory:
            def __init__(self, _device, *, adapter=None, **_kwargs) -> None:
                pass

        self.assertEqual(
            dfu.bleak_adapter_kwargs(Bleak2Factory, "hci7"),
            {"adapter": "hci7"},
        )

    def test_uninspectable_bleak_wrapper_keeps_explicit_adapter(self) -> None:
        with mock.patch.object(
            dfu.inspect, "signature", side_effect=ValueError("opaque wrapper")
        ):
            self.assertEqual(
                dfu.bleak_adapter_kwargs(object(), "hci7"),
                {"adapter": "hci7"},
            )

    def test_address_name_and_advertised_service_are_all_required(self) -> None:
        device = self.Device("AA:BB:CC:DD:EE:FF")
        advertisement = self.Advertisement("RAK3401_OTA", [dfu.DFU_SERVICE])
        selected, _ = dfu.select_advertisement(
            {"one": (device, advertisement)},
            "aa:bb:cc:dd:ee:ff",
            "RAK3401_OTA",
        )
        self.assertIs(selected, device)
        with self.assertRaisesRegex(dfu.DfuError, "name mismatch"):
            dfu.select_advertisement(
                {"one": (device, advertisement)}, device.address, "OTHER"
            )
        advertisement.service_uuids = []
        with self.assertRaisesRegex(dfu.DfuError, "does not advertise"):
            dfu.select_advertisement(
                {"one": (device, advertisement)}, device.address, "RAK3401_OTA"
            )

    def test_high_mtu_requires_two_consistent_observations(self) -> None:
        self.assertEqual(
            dfu.select_packet_size(
                high_mtu_requested=True,
                mtu_acquired=False,
                negotiated_mtu=247,
                max_write_without_response=244,
            ),
            20,
        )
        self.assertEqual(
            dfu.select_packet_size(
                high_mtu_requested=True,
                mtu_acquired=True,
                negotiated_mtu=247,
                max_write_without_response=20,
            ),
            20,
        )
        self.assertEqual(
            dfu.select_packet_size(
                high_mtu_requested=True,
                mtu_acquired=True,
                negotiated_mtu=247,
                max_write_without_response=244,
            ),
            244,
        )
        self.assertEqual(
            dfu.select_packet_size(
                high_mtu_requested=True,
                mtu_acquired=True,
                negotiated_mtu=186,
                max_write_without_response=182,
            ),
            180,
        )

    def test_dis_model_gate_is_mandatory_at_the_cli(self) -> None:
        model_action = next(
            action
            for action in dfu.parser()._actions
            if action.dest == "expected_model"
        )
        self.assertTrue(model_action.required)


class AdaptiveTests(unittest.TestCase):
    def test_every_fast_promotion_is_a_bounded_probe(self) -> None:
        adaptive = dfu.AdaptivePrn()
        self.assertEqual(adaptive.window, 8)
        adaptive.observe_exact_receipt(0.08, 8)
        self.assertEqual(adaptive.window, 8)
        adaptive.observe_exact_receipt(0.08, 8)
        self.assertEqual(adaptive.window, 16)
        self.assertTrue(adaptive.probe_active)
        self.assertEqual(adaptive.last_decision.kind, "probe_started")
        adaptive.observe_exact_receipt(0.16, 16)
        adaptive.observe_exact_receipt(0.16, 16)
        self.assertEqual(adaptive.window, 16)
        self.assertFalse(adaptive.probe_active)
        self.assertEqual(adaptive.last_decision.kind, "probe_kept")
        adaptive.observe_exact_receipt(0.16, 16)
        adaptive.observe_exact_receipt(0.16, 16)
        self.assertEqual(adaptive.window, 32)
        self.assertTrue(adaptive.probe_active)

    def test_slow_exact_receipt_reduces_one_level(self) -> None:
        adaptive = dfu.AdaptivePrn(fast_receipts_to_increase=1)
        adaptive.observe_exact_receipt(0.08, 8)
        adaptive.observe_exact_receipt(0.08, 16)
        adaptive.observe_exact_receipt(0.16, 16)
        adaptive.observe_exact_receipt(0.16, 32)
        self.assertEqual(adaptive.window, 32)
        adaptive.observe_exact_receipt(6.4, 32)
        self.assertEqual(adaptive.window, 16)

    def test_failed_upper_probe_can_continue_down_after_latching(self) -> None:
        adaptive = dfu.AdaptivePrn(fast_receipts_to_increase=1)

        adaptive.observe_exact_receipt(0.08, 8, 160)
        self.assertEqual(adaptive.window, 16)
        adaptive.observe_exact_receipt(0.08, 16, 320)
        self.assertEqual(adaptive.last_decision.kind, "probe_kept")

        adaptive.observe_exact_receipt(0.16, 16, 320)
        self.assertEqual(adaptive.window, 32)
        adaptive.observe_exact_receipt(6.4, 32, 640)
        self.assertEqual(adaptive.window, 16)
        self.assertEqual(adaptive.last_decision.kind, "probe_rolled_back")
        self.assertTrue(adaptive.probe_blocked)

        # The failed upper probe permanently blocks promotion, but it must not
        # prevent another exact slow receipt from selecting the final lower
        # safe level.
        adaptive.observe_exact_receipt(3.2, 16, 320)
        self.assertEqual(adaptive.window, 8)
        self.assertEqual(adaptive.last_decision.kind, "slow_demoted")
        self.assertTrue(adaptive.probe_blocked)

        for _ in range(4):
            adaptive.observe_exact_receipt(0.08, 8, 160)
        self.assertEqual(adaptive.window, 8)
        self.assertFalse(adaptive.probe_active)

    def test_xiao_high_mtu_rate_promotes_after_two_exact_receipts(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        measured_elapsed = 4 * 244 / 2110.0

        adaptive.observe_exact_receipt(measured_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 4)
        adaptive.observe_exact_receipt(measured_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 8)
        for _ in range(4):
            adaptive.observe_exact_receipt(8 * 244 / 2110.0, 8, 8 * 244)
        self.assertEqual(adaptive.window, 8)

    def test_xiao_870_rate_uses_bounded_adjacent_probe(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        neutral_elapsed = 4 * 244 / 870.0

        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 4)
        self.assertFalse(adaptive.probe_active)
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 8)
        self.assertTrue(adaptive.probe_active)
        self.assertFalse(adaptive.probe_blocked)

    def test_neutral_probe_keeps_a_clear_improvement(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        neutral_elapsed = 4 * 244 / 870.0
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)

        adaptive.observe_exact_receipt(8 * 244 / 1100.0, 8, 8 * 244)
        self.assertEqual(adaptive.window, 8)
        self.assertFalse(adaptive.probe_active)
        self.assertFalse(adaptive.probe_blocked)

    def test_neutral_probe_rolls_back_a_close_but_repeatable_regression(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        neutral_elapsed = 4 * 244 / 870.0
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)

        # 820 B/s is still inside the ordinary neutral band and less than ten
        # percent below baseline, so the bounded probe compares two receipts.
        probe_elapsed = 8 * 244 / 820.0
        adaptive.observe_exact_receipt(probe_elapsed, 8, 8 * 244)
        self.assertEqual(adaptive.window, 8)
        self.assertTrue(adaptive.probe_active)
        adaptive.observe_exact_receipt(probe_elapsed, 8, 8 * 244)
        self.assertEqual(adaptive.window, 4)
        self.assertFalse(adaptive.probe_active)
        self.assertTrue(adaptive.probe_blocked)

    def test_failed_neutral_probe_is_session_blocked_without_churn(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        neutral_elapsed = 4 * 244 / 870.0
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)
        adaptive.observe_exact_receipt(neutral_elapsed, 4, 4 * 244)
        adaptive.observe_exact_receipt(8 * 244 / 780.0, 8, 8 * 244)
        self.assertEqual(adaptive.window, 4)
        self.assertTrue(adaptive.probe_blocked)

        for _ in range(20):
            adaptive.observe_exact_receipt(
                neutral_elapsed, 4, 4 * 244
            )
        for _ in range(4):
            adaptive.observe_exact_receipt(
                4 * 244 / 2110.0, 4, 4 * 244
            )
        self.assertEqual(adaptive.window, 4)
        self.assertFalse(adaptive.probe_active)

    def test_neutral_band_prevents_churn_and_slow_receipt_demotes_once(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        fast_elapsed = 4 * 244 / 2110.0
        adaptive.observe_exact_receipt(fast_elapsed, 4, 4 * 244)
        adaptive.observe_exact_receipt(fast_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 8)
        adaptive.observe_exact_receipt(8 * 244 / 2110.0, 8, 8 * 244)
        adaptive.observe_exact_receipt(8 * 244 / 2110.0, 8, 8 * 244)
        self.assertFalse(adaptive.probe_active)

        payload_bytes = 8 * 244
        fast_budget = adaptive._receipt_budget(
            payload_bytes, adaptive.fast_payload_rate
        )
        slow_budget = adaptive._receipt_budget(
            payload_bytes, adaptive.slow_payload_rate
        )
        adaptive.observe_exact_receipt(
            (fast_budget + slow_budget) / 2, 8, payload_bytes
        )
        self.assertEqual(adaptive.window, 8)

        adaptive.observe_exact_receipt(slow_budget + 0.001, 8, payload_bytes)
        self.assertEqual(adaptive.window, 4)
        self.assertTrue(adaptive.probe_blocked)
        for _ in range(30):
            adaptive.observe_exact_receipt(fast_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 4)
        self.assertFalse(adaptive.probe_active)

    def test_failed_fast_promotion_blocks_repeated_oscillation(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        fast_elapsed = 4 * 244 / 2110.0
        slow_elapsed = 8 * 244 / 500.0

        adaptive.observe_exact_receipt(fast_elapsed, 4, 4 * 244)
        adaptive.observe_exact_receipt(fast_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 8)
        adaptive.observe_exact_receipt(slow_elapsed, 8, 8 * 244)
        self.assertEqual(adaptive.window, 4)
        self.assertTrue(adaptive.probe_blocked)
        self.assertEqual(adaptive.last_decision.kind, "probe_rolled_back")

        for _ in range(30):
            adaptive.observe_exact_receipt(fast_elapsed, 4, 4 * 244)
        self.assertEqual(adaptive.window, 4)
        self.assertFalse(adaptive.probe_active)

    def test_slow_receipt_at_minimum_does_not_block_initial_probe(self) -> None:
        adaptive = dfu.AdaptivePrn(packet_size=244, levels=(4, 8))
        payload_bytes = 4 * 244
        slow_budget = adaptive._receipt_budget(
            payload_bytes, adaptive.slow_payload_rate
        )
        adaptive.observe_exact_receipt(
            slow_budget + 0.001, 4, payload_bytes
        )
        self.assertEqual(adaptive.window, 4)
        self.assertFalse(adaptive.probe_blocked)

        fast_elapsed = payload_bytes / 2110.0
        adaptive.observe_exact_receipt(fast_elapsed, 4, payload_bytes)
        adaptive.observe_exact_receipt(fast_elapsed, 4, payload_bytes)
        self.assertEqual(adaptive.window, 8)
        self.assertTrue(adaptive.probe_active)

    def test_levels_must_be_strictly_increasing_uint16_values(self) -> None:
        for levels in ((), (8, 8), (16, 8), (0, 8), (8, 65536), (True, 8)):
            with self.subTest(levels=levels):
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    dfu.AdaptivePrn(levels=levels)

    def test_timing_samples_and_packet_geometry_are_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "packet size"):
            dfu.AdaptivePrn(packet_size=242)
        with self.assertRaisesRegex(ValueError, "timing thresholds"):
            dfu.AdaptivePrn(fast_payload_rate=800, slow_payload_rate=800)
        with self.assertRaisesRegex(ValueError, "timing thresholds"):
            dfu.AdaptivePrn(fast_payload_rate=True)
        with self.assertRaisesRegex(ValueError, "receipt allowance"):
            dfu.AdaptivePrn(receipt_latency_allowance="slow")
        adaptive = dfu.AdaptivePrn()
        for elapsed, packets, payload_bytes in (
            (float("nan"), 8, 160),
            (True, 8, 160),
            (0.0, 8, 160),
            (0.1, 0, 160),
            (0.1, 8, 0),
            (0.1, 8, 161),
        ):
            with self.subTest(
                elapsed=elapsed, packets=packets, payload_bytes=payload_bytes
            ):
                with self.assertRaisesRegex(ValueError, "sample"):
                    adaptive.observe_exact_receipt(
                        elapsed, packets, payload_bytes
                    )


class ActivationAndCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_connect_starts_a_fresh_disconnect_generation(self) -> None:
        disconnected = asyncio.Event()
        disconnected.set()

        dfu.begin_connected_generation(disconnected)

        self.assertFalse(disconnected.is_set())
        disconnected.set()
        self.assertTrue(disconnected.is_set())

    def test_disconnect_cannot_turn_failed_activate_write_into_success(self) -> None:
        write_error = RuntimeError("peer reset raced the GATT response")
        with self.assertRaisesRegex(dfu.DfuError, "unconfirmed ACTIVATE"):
            dfu.require_confirmed_activation_write(False, write_error)
        dfu.require_confirmed_activation_write(True, None)

    async def test_stop_notify_failure_still_disconnects(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.is_connected = True
                self.stop_attempted = False
                self.disconnect_attempted = False

            async def stop_notify(self, _uuid: str) -> None:
                self.stop_attempted = True
                raise RuntimeError("synthetic stop-notify failure")

            async def disconnect(self) -> None:
                self.disconnect_attempted = True
                self.is_connected = False

        client = Client()
        with self.assertRaisesRegex(RuntimeError, "stop-notify"):
            await dfu.cleanup_before_activation(client, notify_started=True)
        self.assertTrue(client.stop_attempted)
        self.assertTrue(client.disconnect_attempted)
        self.assertFalse(client.is_connected)


class WriteCapabilityTests(unittest.IsolatedAsyncioTestCase):
    class Characteristic:
        handle = 0x0010

        def __init__(self, values: list[int]) -> None:
            self.values = values
            self.index = 0

        @property
        def max_write_without_response_size(self) -> int:
            value = self.values[min(self.index, len(self.values) - 1)]
            self.index += 1
            return value

    class Services:
        def __init__(self, characteristic) -> None:
            self.characteristic = characteristic

        def get_characteristic(self, uuid: str):
            if uuid != dfu.DFU_PACKET:
                raise AssertionError(uuid)
            return self.characteristic

    class Client:
        def __init__(self, characteristic) -> None:
            self.is_connected = True
            self.services = WriteCapabilityTests.Services(characteristic)

    class Backend:
        def __init__(self, error: Exception | None = None) -> None:
            self.error = error
            self.calls = 0

        async def _acquire_mtu(self) -> None:
            self.calls += 1
            if self.error is not None:
                raise self.error

    class NegotiationClient(Client):
        def __init__(
            self,
            characteristic,
            *,
            mtu_size=247,
            acquire_error: Exception | None = None,
        ) -> None:
            super().__init__(characteristic)
            self.mtu_size = mtu_size
            self._backend = WriteCapabilityTests.Backend(acquire_error)

    async def run_wait(self, values: list[int], timeout: float = 0.3):
        characteristic = self.Characteristic(values)
        client = self.Client(characteristic)
        clock = FakeClock()

        async def sleep(seconds: float) -> None:
            clock.advance(seconds)

        result = await dfu.wait_for_max_write_without_response(
            client,
            characteristic,
            timeout=timeout,
            poll_interval=0.1,
            clock=clock,
            sleep=sleep,
        )
        return result, client, clock

    async def test_delayed_bluez_property_promotes_to_high_mtu(self) -> None:
        (max_write, waited), _, _ = await self.run_wait([20, 20, 244])
        self.assertEqual(max_write, 244)
        self.assertAlmostEqual(waited, 0.2)

    async def test_partial_capability_is_returned_for_word_alignment(self) -> None:
        (max_write, _), _, _ = await self.run_wait([20, 182])
        self.assertEqual(max_write, 182)
        self.assertEqual(
            dfu.select_packet_size(
                high_mtu_requested=True,
                mtu_acquired=True,
                negotiated_mtu=247,
                max_write_without_response=max_write,
            ),
            180,
        )

    async def test_permanent_default_times_out_to_safe_fallback(self) -> None:
        (max_write, waited), _, _ = await self.run_wait([20])
        self.assertEqual(max_write, 20)
        self.assertAlmostEqual(waited, 0.3)

    async def test_disconnect_during_wait_aborts_before_start(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)
        clock = FakeClock()

        async def sleep(seconds: float) -> None:
            clock.advance(seconds)
            client.is_connected = False

        with self.assertRaisesRegex(dfu.DfuError, "disconnected while waiting"):
            await dfu.wait_for_max_write_without_response(
                client,
                characteristic,
                timeout=0.3,
                poll_interval=0.1,
                clock=clock,
                sleep=sleep,
            )

    async def test_characteristic_object_replacement_is_rejected_even_with_same_handle(
        self,
    ) -> None:
        original = self.Characteristic([20])
        replacement = self.Characteristic([244])
        client = self.Client(original)
        client.services.characteristic = replacement

        with self.assertRaisesRegex(dfu.DfuError, "object changed"):
            await dfu.wait_for_max_write_without_response(
                client, original, timeout=0.1, poll_interval=0.05
            )

    async def test_characteristic_object_identity_is_required_without_handles(
        self,
    ) -> None:
        original = self.Characteristic([20])
        replacement = self.Characteristic([244])
        original.handle = None
        replacement.handle = None
        client = self.Client(original)
        client.services.characteristic = replacement

        with self.assertRaisesRegex(dfu.DfuError, "object changed"):
            await dfu.wait_for_max_write_without_response(
                client, original, timeout=0.1, poll_interval=0.05
            )

    async def test_service_collection_replacement_during_wait_is_rejected(
        self,
    ) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)
        clock = FakeClock()

        async def sleep(seconds: float) -> None:
            clock.advance(seconds)
            client.services = self.Services(characteristic)

        with self.assertRaisesRegex(dfu.DfuError, "service collection identity"):
            await dfu.wait_for_max_write_without_response(
                client,
                characteristic,
                timeout=0.3,
                poll_interval=0.1,
                clock=clock,
                sleep=sleep,
            )

    async def test_characteristic_handle_mutation_during_wait_is_rejected(
        self,
    ) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)
        clock = FakeClock()

        async def sleep(seconds: float) -> None:
            clock.advance(seconds)
            characteristic.handle += 1

        with self.assertRaisesRegex(dfu.DfuError, "identity changed"):
            await dfu.wait_for_max_write_without_response(
                client,
                characteristic,
                timeout=0.3,
                poll_interval=0.1,
                clock=clock,
                sleep=sleep,
            )

    async def test_disappearing_characteristic_is_rejected(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)
        client.services.characteristic = None

        with self.assertRaisesRegex(dfu.DfuError, "disappeared"):
            await dfu.wait_for_max_write_without_response(
                client, characteristic, timeout=0.1, poll_interval=0.05
            )

    async def test_service_lookup_disconnect_race_is_canonicalized(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)

        class RacingServices:
            def get_characteristic(self, _uuid: str):
                client.is_connected = False
                raise RuntimeError("BlueZ object vanished")

        client.services = RacingServices()
        with self.assertRaisesRegex(dfu.DfuError, "disconnected while waiting"):
            await dfu.wait_for_max_write_without_response(
                client, characteristic, timeout=0.1, poll_interval=0.05
            )

    async def test_capability_getter_disconnect_race_is_canonicalized(self) -> None:
        client = None

        class DisconnectingCharacteristic:
            handle = 0x0010

            @property
            def max_write_without_response_size(self):
                assert client is not None
                client.is_connected = False
                raise RuntimeError("BlueZ object vanished")

        characteristic = DisconnectingCharacteristic()
        client = self.Client(characteristic)
        with self.assertRaisesRegex(dfu.DfuError, "disconnected while waiting"):
            await dfu.wait_for_max_write_without_response(
                client, characteristic, timeout=0.1, poll_interval=0.05
            )

    def test_capability_integer_parsing_is_strict(self) -> None:
        class StaticCharacteristic:
            def __init__(self, value) -> None:
                self.max_write_without_response_size = value

        for value in (True, "244", 244.0, None, 0, 19, 515):
            with self.subTest(value=value):
                with self.assertRaises(dfu.WriteCapabilityUnavailable):
                    dfu._read_max_write_without_response(
                        StaticCharacteristic(value)
                    )
        self.assertEqual(
            dfu._read_max_write_without_response(StaticCharacteristic(20)), 20
        )
        self.assertEqual(
            dfu._read_max_write_without_response(StaticCharacteristic(244)), 244
        )

    def test_capability_getter_exception_is_contextualized(self) -> None:
        class BrokenCharacteristic:
            @property
            def max_write_without_response_size(self):
                raise RuntimeError("synthetic getter failure")

        with self.assertRaisesRegex(
            dfu.WriteCapabilityUnavailable, "could not be read"
        ):
            dfu._read_max_write_without_response(BrokenCharacteristic())

    def test_mtu_integer_parsing_is_strict(self) -> None:
        class Client:
            def __init__(self, value) -> None:
                self.mtu_size = value

        for value in (True, "247", 247.0, None, 22, 518):
            with self.subTest(value=value):
                with self.assertRaises(dfu.WriteCapabilityUnavailable):
                    dfu._read_negotiated_mtu(Client(value))
        self.assertEqual(dfu._read_negotiated_mtu(Client(23)), 23)
        self.assertEqual(dfu._read_negotiated_mtu(Client(247)), 247)

    async def test_wait_bounds_must_be_finite_and_positive(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)
        for field, value in (
            ("timeout", True),
            ("timeout", 0),
            ("timeout", -1),
            ("timeout", float("nan")),
            ("timeout", float("inf")),
            ("poll_interval", True),
            ("poll_interval", 0),
            ("poll_interval", -1),
            ("poll_interval", float("nan")),
            ("poll_interval", float("inf")),
        ):
            kwargs = {"timeout": 0.1, "poll_interval": 0.05, field: value}
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    await dfu.wait_for_max_write_without_response(
                        client, characteristic, **kwargs
                    )

    async def test_wait_sleeps_only_to_the_exact_finite_deadline(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)
        clock = FakeClock()
        delays: list[float] = []

        async def sleep(seconds: float) -> None:
            delays.append(seconds)
            clock.advance(seconds)

        max_write, waited = await dfu.wait_for_max_write_without_response(
            client,
            characteristic,
            timeout=0.25,
            poll_interval=0.1,
            clock=clock,
            sleep=sleep,
        )
        self.assertEqual(max_write, 20)
        self.assertAlmostEqual(waited, 0.25)
        self.assertEqual(len(delays), 3)
        self.assertAlmostEqual(delays[0], 0.1)
        self.assertAlmostEqual(delays[1], 0.1)
        self.assertAlmostEqual(delays[2], 0.05)

    async def test_wait_rejects_nonfinite_or_regressing_clocks(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.Client(characteristic)

        for values in ((float("nan"),), (1.0, 0.5)):
            iterator = iter(values)

            def clock() -> float:
                return next(iterator)

            with self.subTest(values=values):
                with self.assertRaisesRegex(dfu.DfuError, "clock"):
                    await dfu.wait_for_max_write_without_response(
                        client,
                        characteristic,
                        timeout=0.1,
                        poll_interval=0.05,
                        clock=clock,
                    )

    async def test_negotiate_waits_for_delayed_bluez_capability(self) -> None:
        characteristic = self.Characteristic([20, 244])
        client = self.NegotiationClient(characteristic)
        self.assertEqual(await dfu.negotiate_packet_size(client, True), 244)
        self.assertEqual(client._backend.calls, 1)

    async def test_negotiate_permanent_default_falls_back_to_20(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.NegotiationClient(characteristic)
        with mock.patch.object(
            dfu,
            "wait_for_max_write_without_response",
            new=mock.AsyncMock(return_value=(20, 3.0)),
        ):
            self.assertEqual(await dfu.negotiate_packet_size(client, True), 20)

    async def test_negotiate_acquire_failure_cannot_promote(self) -> None:
        characteristic = self.Characteristic([244])
        client = self.NegotiationClient(
            characteristic, acquire_error=RuntimeError("not supported")
        )
        self.assertEqual(await dfu.negotiate_packet_size(client, True), 20)

    async def test_negotiate_invalid_wait_observation_falls_back_to_20(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.NegotiationClient(characteristic)
        with mock.patch.object(
            dfu,
            "wait_for_max_write_without_response",
            new=mock.AsyncMock(
                side_effect=dfu.WriteCapabilityUnavailable("malformed cache")
            ),
        ):
            self.assertEqual(await dfu.negotiate_packet_size(client, True), 20)

    async def test_negotiate_disconnect_during_acquire_is_fatal(self) -> None:
        characteristic = self.Characteristic([20])
        client = self.NegotiationClient(characteristic)

        async def disconnecting_acquire() -> None:
            client.is_connected = False
            raise RuntimeError("link lost")

        client._backend._acquire_mtu = disconnecting_acquire
        with self.assertRaisesRegex(dfu.DfuError, "disconnected during"):
            await dfu.negotiate_packet_size(client, True)

    async def test_negotiate_capability_getter_disconnect_is_fatal(self) -> None:
        client = None

        class DisconnectingCharacteristic:
            @property
            def max_write_without_response_size(self):
                assert client is not None
                client.is_connected = False
                raise RuntimeError("link lost")

        characteristic = DisconnectingCharacteristic()
        client = self.NegotiationClient(characteristic)
        with self.assertRaisesRegex(dfu.DfuError, "disconnected while reading"):
            await dfu.negotiate_packet_size(client, True)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def make_session(
        self,
        firmware: bytes,
        **transport_options,
    ):
        clock = FakeClock()
        transport = FakeTransport(len(firmware), clock, **transport_options)
        session = dfu.LegacyDfu(
            transport,
            packet_size=20,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
        )
        transport.bind(session)
        return session, transport

    async def test_application_transfer_negotiates_8_16_32_and_validates(self) -> None:
        firmware = bytes(2200)
        package = synthetic_package("application", firmware)
        session, transport = await self.make_session(firmware)
        await session.start(package)
        await session.initialize(package.init_packet)
        await session.send_firmware(firmware)
        await session.validate()
        await session.activate()
        self.assertEqual(transport.mode, dfu.MODE_APPLICATION)
        self.assertEqual(transport.sizes, (0, 0, len(firmware)))
        self.assertEqual(transport.prn_history, [8, 16, 32])
        self.assertEqual(transport.received, len(firmware))
        self.assertTrue(transport.activated)

    async def test_prn_levels_are_bounded_by_packet_storage_horizon(self) -> None:
        expected = {
            20: (8, 16, 32),
            60: (8, 16, 32),
            64: (8, 16),
            68: (4, 8),
            244: (4, 8),
        }
        for packet_size, levels in expected.items():
            with self.subTest(packet_size=packet_size):
                clock = FakeClock()
                transport = FakeTransport(4096, clock)
                session = dfu.LegacyDfu(
                    transport,
                    packet_size=packet_size,
                    response_timeout=0.1,
                    receipt_timeout=0.02,
                    clock=clock,
                )
                self.assertEqual(session.prn.levels, levels)
                self.assertEqual(session.prn.packet_size, packet_size)

        clock = FakeClock()
        transport = FakeTransport(4096, clock)
        with self.assertRaisesRegex(ValueError, "start/bounds"):
            dfu.LegacyDfu(
                transport,
                packet_size=244,
                response_timeout=0.1,
                receipt_timeout=0.02,
                clock=clock,
                adaptive_prn=dfu.AdaptivePrn(),
            )
        with self.assertRaisesRegex(ValueError, "start/bounds"):
            dfu.LegacyDfu(
                transport,
                packet_size=244,
                response_timeout=0.1,
                receipt_timeout=0.02,
                clock=clock,
                adaptive_prn=dfu.AdaptivePrn(
                    packet_size=244, levels=(8,)
                ),
            )
        with self.assertRaisesRegex(ValueError, "start/bounds"):
            dfu.LegacyDfu(
                transport,
                packet_size=20,
                response_timeout=0.1,
                receipt_timeout=0.02,
                clock=clock,
                adaptive_prn=dfu.AdaptivePrn(levels=(8, 32)),
            )

    async def test_xiao_high_mtu_transfer_promotes_only_to_prn8(self) -> None:
        firmware = bytes(20 * 244)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=244 / 2110.0
        )
        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history, [4, 8])
        self.assertLessEqual(max(transport.prn_history), 8)
        self.assertEqual(transport.received, len(firmware))

    async def test_xiao_870_rate_probe_keeps_an_improved_prn8(self) -> None:
        firmware = bytes(40 * 244)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=244 / 870.0
        )

        def window_changed(
            old: int, new: int, _elapsed: float, _packets: int
        ) -> None:
            if (old, new) == (4, 8):
                transport.packet_seconds = 244 / 1100.0

        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            window_changed=window_changed,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history, [4, 8])
        self.assertEqual(transport.received, len(firmware))

    async def test_xiao_degraded_probe_rolls_back_once_without_churn(self) -> None:
        firmware = bytes(72 * 244)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=244 / 870.0
        )

        def window_changed(
            old: int, new: int, _elapsed: float, _packets: int
        ) -> None:
            if (old, new) == (4, 8):
                transport.packet_seconds = 244 / 820.0
            elif (old, new) == (8, 4):
                transport.packet_seconds = 244 / 870.0

        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            window_changed=window_changed,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history, [4, 8, 4])
        self.assertTrue(session.prn.probe_blocked)
        self.assertEqual(transport.received, len(firmware))

    async def test_high_mtu_clean_slow_window_demotes_immediately(self) -> None:
        firmware = bytes(28 * 244)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=244 / 2110.0
        )

        def window_changed(
            old: int, new: int, _elapsed: float, _packets: int
        ) -> None:
            if (old, new) == (4, 8):
                transport.packet_seconds = 0.5

        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            window_changed=window_changed,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history[:3], [4, 8, 4])
        self.assertEqual(transport.received, len(firmware))

    async def test_high_mtu_failed_fast_probe_does_not_oscillate(self) -> None:
        firmware = bytes(60 * 244)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=244 / 2110.0
        )
        promotions = 0

        def window_changed(
            old: int, new: int, _elapsed: float, _packets: int
        ) -> None:
            nonlocal promotions
            if (old, new) == (4, 8):
                promotions += 1
                if promotions == 1:
                    transport.packet_seconds = 0.5
            elif (old, new) == (8, 4):
                transport.packet_seconds = 244 / 2110.0

        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            window_changed=window_changed,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history, [4, 8, 4])
        self.assertTrue(session.prn.probe_blocked)
        self.assertEqual(transport.received, len(firmware))

    async def test_kept_probe_then_slow_demotion_does_not_oscillate(self) -> None:
        firmware = bytes(100 * 244)
        clock = FakeClock()
        fast_packet_seconds = 244 / 2110.0
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=fast_packet_seconds
        )
        decisions: list[str] = []

        def adaptation_event(
            decision: dfu.PrnDecision, _elapsed: float, _packets: int
        ) -> None:
            decisions.append(decision.kind)
            if decision.kind == "probe_kept":
                transport.packet_seconds = 0.5
            elif decision.kind == "slow_demoted":
                transport.packet_seconds = fast_packet_seconds

        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            adaptation_event=adaptation_event,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertIn("probe_kept", decisions)
        self.assertIn("slow_demoted", decisions)
        self.assertEqual(transport.prn_history, [4, 8, 4])
        self.assertTrue(session.prn.probe_blocked)
        self.assertEqual(transport.received, len(firmware))

    async def test_multiple_safe_levels_can_negotiate_back_down(self) -> None:
        firmware = bytes(320 * 20)
        clock = FakeClock()
        fast_packet_seconds = 20 / 2110.0
        transport = FakeTransport(
            len(firmware), clock, packet_seconds=fast_packet_seconds
        )

        def adaptation_event(
            decision: dfu.PrnDecision, _elapsed: float, _packets: int
        ) -> None:
            if (
                decision.kind == "probe_kept"
                and (decision.old_window, decision.new_window) == (32, 32)
            ):
                transport.packet_seconds = 0.2

        session = dfu.LegacyDfu(
            transport,
            packet_size=20,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            adaptation_event=adaptation_event,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history, [8, 16, 32, 16, 8])
        self.assertTrue(session.prn.probe_blocked)
        self.assertEqual(transport.received, len(firmware))

    async def test_high_mtu_ahead_receipt_still_aborts_at_prn4(self) -> None:
        firmware = bytes(3000)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, receipt_delta=4
        )
        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        with self.assertRaisesRegex(dfu.DfuError, "ahead packet receipt"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 4)
        self.assertEqual(transport.prn_history, [4])

    async def test_exact_slow_receipt_negotiates_window_back_down(self) -> None:
        firmware = bytes(2600)
        clock = FakeClock()
        transport = FakeTransport(len(firmware), clock)

        def window_changed(old: int, new: int, _elapsed: float, _packets: int) -> None:
            if (old, new) == (16, 32):
                transport.packet_seconds = 0.200

        session = dfu.LegacyDfu(
            transport,
            packet_size=20,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            window_changed=window_changed,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.prn_history[:4], [8, 16, 32, 16])
        self.assertEqual(transport.received, len(firmware))

    async def test_combined_start_uses_sd_and_bootloader_sizes(self) -> None:
        firmware = bytes(dfu.OTAFIX_BOOTLOADER_BYTES + 32)
        package = synthetic_package("softdevice_bootloader", firmware)
        session, transport = await self.make_session(firmware)
        await session.start(package)
        self.assertEqual(transport.mode, dfu.MODE_SD_BOOTLOADER)
        self.assertEqual(transport.sizes, (32, dfu.OTAFIX_BOOTLOADER_BYTES, 0))

    async def test_exact_final_prn_boundary_is_split_for_legacy_targets(self) -> None:
        # The original Nordic path omits PRN when final DATA completion and a
        # receipt boundary coincide.  The host makes packet eight non-final,
        # gets its exact receipt, then sends the remaining tail.
        firmware = bytes(8 * 20)
        session, transport = await self.make_session(firmware)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.received, len(firmware))
        self.assertEqual(transport.receive_packets, 9)

    async def test_four_byte_final_boundary_tail_is_split_one_packet_earlier(self) -> None:
        firmware = bytes(7 * 20 + 4)
        session, transport = await self.make_session(firmware)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.received, len(firmware))
        self.assertEqual(transport.receive_packets, 9)

    async def test_high_mtu_final_boundary_uses_safe_nonfinal_receipt(self) -> None:
        firmware = bytes(8 * 244)
        clock = FakeClock()
        transport = FakeTransport(len(firmware), clock)
        session = dfu.LegacyDfu(
            transport,
            packet_size=244,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        await session.send_firmware(firmware)
        self.assertEqual(transport.received, len(firmware))
        self.assertEqual(transport.receive_packets, 9)
        self.assertEqual(transport.prn_history, [4, 8])
        self.assertLessEqual(max(transport.prn_history), 8)

    async def test_response_at_nonfinal_receipt_boundary_is_fatal(self) -> None:
        firmware = bytes(1000)
        session, transport = await self.make_session(firmware, drop_first_receipt=True)
        await session.initialize(b"0123456789abcd")
        session.notification(
            None,
            bytes((dfu.OP_RESPONSE, dfu.OP_RECEIVE, dfu.RESULT_SUCCESS)),
        )
        with self.assertRaisesRegex(dfu.DfuError, "missing packet receipt"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 8)

    async def test_duplicate_stale_receipt_is_not_reused_for_a_later_window(
        self,
    ) -> None:
        firmware = bytes(1000)
        session, transport = await self.make_session(
            firmware, duplicate_first_receipt=True
        )
        await session.initialize(b"0123456789abcd")
        with self.assertRaisesRegex(dfu.DfuError, "short packet receipt"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 16)
        self.assertEqual(transport.received, 320)

    async def test_progress_distinguishes_sent_prn_and_final_confirmation(
        self,
    ) -> None:
        firmware = bytes(10 * 20)
        clock = FakeClock()
        transport = FakeTransport(
            len(firmware), clock, final_response_seconds=2.0
        )
        progress: list[tuple[int, int, int, float]] = []
        session = dfu.LegacyDfu(
            transport,
            packet_size=20,
            response_timeout=0.1,
            receipt_timeout=0.02,
            clock=clock,
            progress=lambda sent, confirmed, total, rate: progress.append(
                (sent, confirmed, total, rate)
            ),
        )
        transport.bind(session)
        await session.initialize(b"0123456789abcd")
        stats = await session.send_firmware(firmware)

        self.assertGreaterEqual(len(progress), 2)
        self.assertEqual(progress[-2][:3], (len(firmware), 160, len(firmware)))
        self.assertEqual(
            progress[-1][:3], (len(firmware), len(firmware), len(firmware))
        )
        self.assertAlmostEqual(stats.elapsed, 2.1)
        self.assertAlmostEqual(stats.payload_rate, len(firmware) / 2.1)
        self.assertAlmostEqual(progress[-1][3], stats.payload_rate)

    async def test_empty_firmware_is_rejected_before_receive(self) -> None:
        session, transport = await self.make_session(b"")
        await session.initialize(b"0123456789abcd")
        with self.assertRaisesRegex(dfu.DfuError, "nonempty"):
            await session.send_firmware(b"")
        self.assertEqual(transport.receive_packets, 0)

    async def test_short_receipt_aborts_without_sending_more(self) -> None:
        firmware = bytes(1000)
        session, transport = await self.make_session(firmware, receipt_delta=-4)
        await session.initialize(b"0123456789abcd")
        with self.assertRaisesRegex(dfu.DfuError, "short packet receipt"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 8)

    async def test_ahead_receipt_aborts_without_sending_more(self) -> None:
        firmware = bytes(1000)
        session, transport = await self.make_session(firmware, receipt_delta=4)
        await session.initialize(b"0123456789abcd")
        with self.assertRaisesRegex(dfu.DfuError, "ahead packet receipt"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 8)

    async def test_missing_receipt_aborts_without_sending_more(self) -> None:
        firmware = bytes(1000)
        session, transport = await self.make_session(
            firmware, drop_first_receipt=True
        )
        await session.initialize(b"0123456789abcd")
        with self.assertRaisesRegex(dfu.DfuError, "timed out waiting"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 8)

    async def test_malformed_notification_is_fatal(self) -> None:
        firmware = bytes(1000)
        session, transport = await self.make_session(firmware)
        await session.initialize(b"0123456789abcd")
        session.notification(None, b"\x11\x00")
        with self.assertRaisesRegex(dfu.DfuError, "malformed"):
            await session.send_firmware(firmware)
        self.assertEqual(transport.receive_packets, 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
