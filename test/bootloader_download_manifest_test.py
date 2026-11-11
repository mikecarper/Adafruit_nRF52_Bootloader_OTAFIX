#!/usr/bin/env python3
"""Verify download identities, storage variants and rejection of unsafe catalogs."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_bootloader_download_manifest import build_manifest


class DownloadManifestTests(unittest.TestCase):
    def setUp(self):
        self.mapping = json.loads((ROOT / "docs/bootloader_profiles.json").read_text())
        tag = "v0.11.0-OTAFIX2.4.10"
        base = "https://github.com/" + self.mapping["repository"]
        self.release = {"tag_name": tag, "html_url": base + "/releases/tag/" + tag,
                        "draft": False, "prerelease": False, "assets": []}
        for profile in self.mapping["profiles"]:
            prefix = profile["id"] + "_bootloader-" + tag
            sd_version = "7.3.0" if profile["id"] == "meshtracker_x1" else "6.1.1"
            for name in ("update-" + prefix + "_mbr.uf2", prefix + "_s140_" + sd_version + ".zip",
                         prefix + "_s140_" + sd_version + ".hex"):
                self.release["assets"].append({"name": name, "size": 100,
                    "digest": "sha256:" + "a" * 64,
                    "browser_download_url": base + "/releases/download/" + tag + "/" + name})

    def test_all_normal_profiles_and_exact_storage(self):
        manifest = build_manifest(self.release, self.mapping)
        self.assertEqual(24, len(manifest["profiles"]))
        profiles = {p["id"]: p for p in manifest["profiles"]}
        self.assertNotIn("heltec_mesh_tower_v2", profiles)
        for board, storage in (("heltec_t096", "internal"), ("heltec_t114", "internal"),
                ("heltec_mesh_tower_v2_sdcard", "sd"),
                ("wiscore_rak3401_auto", "adaptive"), ("wiscore_rak4631_auto", "adaptive")):
            self.assertEqual(storage, profiles[board]["storage"])
            self.assertEqual({"uf2", "zip", "hex"}, set(profiles[board]["files"]))
        self.assertEqual("4631_DFU", profiles["wiscore_rak4631_auto"]["deviceName"])

    def test_recovery_assets_are_not_normal_downloads(self):
        extra = copy.deepcopy(self.release["assets"][0])
        extra["name"] = extra["name"].replace("update-", "update-R_")
        self.release["assets"].append(extra)
        manifest = build_manifest(self.release, self.mapping)
        self.assertNotIn("update-R_", manifest["profiles"][0]["files"]["uf2"]["name"])

    def test_x1_requires_actual_assets_not_a_synthetic_download(self):
        self.release["assets"] = [asset for asset in self.release["assets"]
                                  if not asset["name"].startswith("meshtracker_x1_")]
        with self.assertRaisesRegex(ValueError, "meshtracker_x1: expected one exact zip asset"):
            build_manifest(self.release, self.mapping)

    def test_legacy_rak_release_identity_does_not_claim_supplemental_sd(self):
        # Current source flags must not retroactively grant an old release SD
        # support. Neither filenames nor the preserved adaptive identity prove
        # the exact device image contains a valid MOTASDRA capability marker.
        manifest = build_manifest(self.release, self.mapping)
        rak = next(p for p in manifest["profiles"] if p["id"] == "wiscore_rak4631_auto")
        self.assertEqual("adaptive", rak["storage"])
        self.assertEqual("4631_DFU", rak["deviceName"])
        self.assertNotIn("RAK15002", rak["label"])
        self.assertNotIn("sd", rak["label"].lower())

    def test_carrier_aliases_and_real_port_gaps(self):
        manifest = build_manifest(self.release, self.mapping)
        aliases = {h: p["id"] for p in manifest["profiles"] for h in p["meshcoreHardware"]}
        for h in ("ikoka_stick_nrf_33dbm", "ikoka_nano_nrf_30dbm",
                  "ikoka_handheld_nrf_e22_30dbm_096", "solarxiao_33S"):
            self.assertEqual("xiao_nrf52840_ble", aliases[h])
        for h in ("WioTrackerL1-1W", "WioTrackerL1Eink"):
            self.assertEqual("wio_tracker_l1", aliases[h])
        self.assertEqual("heltec_mesh_tower_v2_sdcard", aliases["Heltec_tower_v2_sdcard"])
        gaps = {h: p for p in manifest["unavailableProfiles"] for h in p["meshcoreHardware"]}
        self.assertEqual(14, len(gaps))
        self.assertEqual("meshtracker_x1", aliases["MeshTracker_X1"])
        self.assertEqual("internal", next(p for p in manifest["profiles"]
                                         if p["id"] == "meshtracker_x1")["storage"])
        x1 = next(p for p in manifest["profiles"] if p["id"] == "meshtracker_x1")
        self.assertEqual("X1INT_DFU", x1["deviceName"])
        self.assertTrue(x1["files"]["zip"]["name"].endswith("_s140_7.3.0.zip"))
        self.assertTrue(x1["files"]["hex"]["name"].endswith("_s140_7.3.0.hex"))
        for h in ("wio_wm1110", "GAT562_Mesh_Watch13", "ThinkNode_M8", "LilyGo_T-Echo_Card",
                  "Heltec_tower_v2"):
            self.assertNotIn(h, aliases)
            self.assertTrue(gaps[h]["reason"])
            self.assertNotIn("files", gaps[h])

    def test_unavailable_profile_cannot_shadow_a_download(self):
        self.mapping["unavailableProfiles"][0]["meshcoreHardware"].append("Xiao_nrf52")
        with self.assertRaisesRegex(ValueError, "ambiguous hardware"):
            build_manifest(self.release, self.mapping)
        self.mapping["unavailableProfiles"][0]["meshcoreHardware"].pop()
        self.mapping["unavailableProfiles"][0]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "invalid unavailable"):
            build_manifest(self.release, self.mapping)

    def test_missing_or_ambiguous_file_rejected(self):
        self.release["assets"].append(copy.deepcopy(self.release["assets"][0]))
        with self.assertRaisesRegex(ValueError, "expected one exact uf2"):
            build_manifest(self.release, self.mapping)
        self.release["assets"] = self.release["assets"][1:-1]
        with self.assertRaisesRegex(ValueError, "expected one exact uf2"):
            build_manifest(self.release, self.mapping)

    def test_bad_url_or_digest_rejected(self):
        for field, value in (("browser_download_url", "https://example.com/file.uf2"),
                             ("digest", None)):
            release = copy.deepcopy(self.release)
            release["assets"][0][field] = value
            with self.assertRaises(ValueError):
                build_manifest(release, self.mapping)

    def test_ambiguous_hardware_or_incomplete_coverage_rejected(self):
        self.mapping["profiles"][1]["meshcoreHardware"] = self.mapping["profiles"][0]["meshcoreHardware"]
        with self.assertRaisesRegex(ValueError, "ambiguous hardware"):
            build_manifest(self.release, self.mapping)
        self.mapping["profiles"].pop()
        with self.assertRaisesRegex(ValueError, "every normal release profile"):
            build_manifest(self.release, self.mapping)


if __name__ == "__main__":
    unittest.main()
