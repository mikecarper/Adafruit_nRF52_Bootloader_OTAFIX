#!/usr/bin/env python3
"""Run the actual recovery publisher against simulated GitHub asset metadata."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/recovery.yml").read_text(encoding="ascii")
SOURCE = textwrap.dedent(re.search(
    r"          python3 - <<'PY'\n(.*?)\n          PY", WORKFLOW, re.S).group(1))


class RecoveryPublisherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, previous)
        self.files = [Path("_recovery-release/R_test.zip"),
                      Path("_recovery-release/update-R_test.uf2"),
                      Path("_recovery-bundle/OTAFIX-2.4.11-R_recovery.zip"),
                      Path("_recovery-bundle/OTAFIX-2.4.11-R_recovery.zip.sha256"),
                      Path("_recovery-bundle/manifest.json")]
        self.assets = []
        for path in self.files:
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(path.name.encode("ascii"))
            self.assets.append({"name": path.name,
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()})

    def publish(self, assets, failure=None, source_tag=None):
        with mock.patch.dict(os.environ, {
            "RECOVERY_RELEASE_TAG": "R_0.11.0-OTAFIX2.4.11", "GH_REPO": "owner/repo",
            "RECOVERY_SOURCE_TAG": source_tag or "R_0.11.0-OTAFIX2.4.11"}), \
             mock.patch("subprocess.check_output", return_value=json.dumps({"assets": assets})), \
             mock.patch("subprocess.run", side_effect=failure) as run, \
             mock.patch("time.sleep") as sleep, mock.patch("sys.stdout", io.StringIO()):
            self.last_run = run
            exec(compile(SOURCE, "<recovery publisher>", "exec"), {})
        return run.call_args_list, sleep.call_args_list

    def test_identical_assets_are_preserved_and_release_remains_non_latest(self):
        calls, pauses = self.publish(self.assets)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0], ["gh", "release", "edit",
            "R_0.11.0-OTAFIX2.4.11", "--prerelease", "--latest=false"])
        self.assertEqual(pauses, [])

    def test_only_missing_and_changed_assets_are_uploaded_sequentially(self):
        self.assets[0]["digest"] = "sha256:damaged"
        self.assets.pop()
        calls, pauses = self.publish(self.assets)
        uploads = [call.args[0] for call in calls if call.args[0][2] == "upload"]
        self.assertEqual([call[-1] for call in uploads], [str(self.files[0]), str(self.files[-1])])
        self.assertEqual(pauses, [mock.call(1), mock.call(1)])
        self.assertTrue(all(call[3:5] == ["R_0.11.0-OTAFIX2.4.11", "--clobber"]
                            for call in uploads))

    def test_missing_bundle_is_rejected_before_any_release_mutation(self):
        self.files[2].unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing"):
            self.publish(self.assets)
        self.last_run.assert_not_called()

    def test_failed_upload_stops_further_changes(self):
        calls = []
        def fail_upload(command, **kwargs):
            calls.append(command)
            if command[2] == "upload":
                raise subprocess.CalledProcessError(1, command)
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish([], failure=fail_upload)
        self.assertEqual(len(calls), 2)

    def test_source_only_repair_preserves_external_names_and_distribution_release(self):
        self.assets[0]["digest"] = "sha256:old-recovery-image"
        calls, pauses = self.publish(self.assets, source_tag="R_v0.11.0-OTAFIX2.4.11")
        self.assertEqual(calls[0].args[0], ["gh", "release", "edit",
            "R_0.11.0-OTAFIX2.4.11", "--prerelease", "--latest=false"])
        self.assertEqual(calls[1].args[0], ["gh", "release", "upload",
            "R_0.11.0-OTAFIX2.4.11", "--clobber", str(self.files[0])])
        self.assertEqual(pauses, [mock.call(1)])

    def test_source_only_repair_cannot_add_or_drop_existing_asset_names(self):
        self.assets[0]["name"] = "R_source_only_filename.zip"
        with self.assertRaisesRegex(RuntimeError, "preserve every existing asset name"):
            self.publish(self.assets, source_tag="R_v0.11.0-OTAFIX2.4.11")
        self.last_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
