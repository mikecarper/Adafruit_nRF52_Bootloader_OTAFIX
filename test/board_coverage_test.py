#!/usr/bin/env python3
"""Keep all missing hardware classified and qualification metadata fail-closed."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_board_coverage import validate_coverage


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.mapping = json.loads((ROOT / "docs/bootloader_profiles.json").read_text())

    def candidate(self, board):
        return next(item for item in self.mapping["unavailableProfiles"] if item["id"] == board)

    def test_all_hardware_is_honestly_classified(self):
        self.assertEqual({"releasedProfiles": 23, "releasedHardware": 40,
                          "pendingProfiles": 9, "pendingHardware": 12,
                          "blockedProfiles": 2, "blockedHardware": 2,
                          "retiredProfiles": 1, "retiredHardware": 1},
                         validate_coverage(self.mapping))
        x1 = self.candidate("meshtracker_x1")["qualification"]
        self.assertEqual("internal", x1["storage"])
        self.assertEqual("source-pending", x1["status"])
        self.assertFalse(x1["hardwareQualified"])

    def test_pending_port_cannot_be_omitted(self):
        self.mapping["unavailableProfiles"].remove(self.candidate("meshtracker_x1"))
        with self.assertRaisesRegex(ValueError, "every pending source"):
            validate_coverage(self.mapping)

    def test_source_and_storage_cannot_be_substituted(self):
        for field, value in (("sourceBoard", "wio_tracker_l1"), ("storage", "qspi")):
            with self.subTest(field=field):
                mapping = copy.deepcopy(self.mapping)
                next(item for item in mapping["unavailableProfiles"] if item["id"] ==
                     "meshtracker_x1")["qualification"][field] = value
                with self.assertRaises(ValueError):
                    validate_coverage(mapping)

    def test_unavailable_cannot_claim_files_or_physical_qualification(self):
        x1 = self.candidate("meshtracker_x1")
        x1["files"] = {"uf2": {"url": "https://example.invalid/not-qualified.uf2"}}
        with self.assertRaisesRegex(ValueError, "cannot claim qualified downloads"):
            validate_coverage(self.mapping)
        del x1["files"]
        x1["qualification"]["hardwareQualified"] = True
        with self.assertRaisesRegex(ValueError, "cannot claim qualified downloads"):
            validate_coverage(self.mapping)

    def test_unknown_identity_must_not_be_reported_as_verified(self):
        self.candidate("thinknode_m8")["qualification"]["factoryIdentity"] = "verified"
        with self.assertRaisesRegex(ValueError, "verified identity is invalid"):
            validate_coverage(self.mapping)

    def test_blocked_profile_cannot_pretend_to_have_source(self):
        self.candidate("thinknode_m4")["qualification"]["sourceBoard"] = "thinknode_m3"
        with self.assertRaisesRegex(ValueError, "blocked metadata disagrees"):
            validate_coverage(self.mapping)

    def test_retired_tower_requires_local_exact_replacement(self):
        self.candidate("heltec_mesh_tower_v2")["qualification"]["localMigrationOnly"] = False
        with self.assertRaisesRegex(ValueError, "local-only replacement"):
            validate_coverage(self.mapping)

    def test_metadata_requires_evidence_and_remaining_blockers(self):
        self.candidate("meshtracker_x1")["qualification"]["blockers"] = []
        with self.assertRaisesRegex(ValueError, "explicit blockers and primary evidence"):
            validate_coverage(self.mapping)


if __name__ == "__main__":
    unittest.main()
