#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "derive_otafix_version.py"
SPEC = importlib.util.spec_from_file_location("derive_otafix_version", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class VersionDerivationTest(unittest.TestCase):
    def test_preview_and_stable_are_monotonic(self):
        preview = MODULE.derive("0.9.2-OTAFIX2.4.1-preview.12")
        stable = MODULE.derive("0.9.2-OTAFIX2.4.1")
        next_patch = MODULE.derive("0.9.2-OTAFIX2.4.2-preview.1")
        self.assertEqual(preview, 0x0204010C)
        self.assertEqual(stable, 0x020401FF)
        self.assertLess(preview, stable)
        self.assertLess(stable, next_patch)

    def test_noncanonical_descriptions_fail(self):
        for value in (
            "0.9.2-OTAFIX2.4.1-preview.12-dirty",
            "0.9.2-OTAFIX2.4.1-preview.12-7-gdeadbeef",
            "57b805c0",
            "prefix-0.9.2-OTAFIX2.4.1-preview.12",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.derive(value)

    def test_invalid_channels_fail(self):
        for value in (
            "0.9.2-OTAFIX2.4.1-preview.0",
            "0.9.2-OTAFIX2.4.1-preview.255",
            "0.9.2-OTAFIX256.1.1-preview.1",
            "0.9.2-OTAFIX255.255.255",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.derive(value)

    def test_recovery_tags_require_explicit_opt_in_and_remain_exact(self):
        tag = "R_0.11.0-OTAFIX2.4.6"
        with self.assertRaises(ValueError):
            MODULE.derive(tag)
        self.assertEqual(0x020406FF, MODULE.derive(tag, recovery_allow_all_boards=True))
        self.assertEqual(0x020406FF, MODULE.derive("0.11.0-OTAFIX2.4.6", recovery_allow_all_boards=True))
        for suffix in ("-dirty", "-2-gdeadbeef", "-recovery-allow-all"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                MODULE.derive(tag + suffix, recovery_allow_all_boards=True)
        with self.assertRaises(ValueError):
            MODULE.derive("R_" + tag, recovery_allow_all_boards=True)


if __name__ == "__main__":
    unittest.main()
