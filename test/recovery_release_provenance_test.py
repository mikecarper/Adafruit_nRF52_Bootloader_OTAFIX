#!/usr/bin/env python3
"""Recovery repair must preserve the old tag and use clean equivalent source."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import recovery_release_provenance as provenance

RELEASE = "R_0.11.0-OTAFIX2.4.11"
SOURCE = "R_v0.11.0-OTAFIX2.4.11"


class RecoveryProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Recovery test")
        self.file = self.root / "source.txt"
        self.file.write_text("Original release\n", encoding="ascii")
        self.git("add", "source.txt")
        self.git("commit", "-qm", "Original")
        self.original_commit = self.git("rev-parse", "HEAD")
        self.git("tag", "-am", "Original distribution", RELEASE)
        self.original_object = self.git("rev-parse", "refs/tags/" + RELEASE)
        self.file.write_text("Corrected source\n", encoding="ascii")
        self.git("commit", "-qam", "Correction")
        self.source_commit = self.git("rev-parse", "HEAD")
        self.git("tag", "-am", "Source-only correction", SOURCE)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args],
                                       text=True, stderr=subprocess.PIPE).strip()

    def test_equivalent_source_records_both_provenances_and_leaves_old_tag_unchanged(self):
        result = provenance.validate(self.root, SOURCE, RELEASE)
        self.assertEqual(result, {"source_tag": SOURCE, "source_commit": self.source_commit,
            "distribution_tag": RELEASE, "distribution_tag_object": self.original_object,
            "distribution_tag_commit": self.original_commit})
        self.assertEqual(self.git("rev-parse", "refs/tags/" + RELEASE), self.original_object)
        self.assertNotEqual(self.source_commit, self.original_commit)
        self.assertEqual(provenance.recovery_version(SOURCE), 0x02040BFF)

    def test_same_source_and_distribution_remains_supported(self):
        self.git("checkout", "-q", RELEASE)
        result = provenance.validate(self.root, RELEASE, RELEASE)
        self.assertEqual(result["source_commit"], self.original_commit)

    def test_different_packed_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "different packed versions"):
            provenance.validate(self.root, "R_v0.11.0-OTAFIX2.4.12", RELEASE)

    def test_preview_and_stable_versions_are_not_equivalent(self):
        with self.assertRaisesRegex(ValueError, "different packed versions"):
            provenance.validate(self.root, "R_v0.11.0-OTAFIX2.4.11-preview.1", RELEASE)

    def test_noncanonical_or_nonrecovery_tag_is_rejected(self):
        for source in (None, "v0.11.0-OTAFIX2.4.11", SOURCE + "-dirty", SOURCE + "-1-gabc"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                provenance.validate(self.root, source, RELEASE)

    def test_dirty_tracked_or_untracked_source_is_rejected(self):
        self.file.write_text("Uncommitted source\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "must be clean"):
            provenance.validate(self.root, SOURCE, RELEASE)
        self.git("checkout", "--", "source.txt")
        (self.root / "untracked.txt").write_text("untracked\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "must be clean"):
            provenance.validate(self.root, SOURCE, RELEASE)

    def test_ignored_generated_artifacts_do_not_dirty_the_source(self):
        # CI downloads verified build outputs into an ignored directory before
        # packaging. Those outputs must not weaken checks on source files.
        (self.root / ".git/info/exclude").write_text("/_recovery-release/\n", encoding="ascii")
        generated = self.root / "_recovery-release"
        generated.mkdir()
        (generated / "R_board.zip").write_bytes(b"qualification artifact")
        result = provenance.validate(self.root, SOURCE, RELEASE)
        self.assertEqual(result["source_commit"], self.source_commit)

    def test_checkout_must_match_the_exact_source_tag(self):
        self.file.write_text("Later source\n", encoding="ascii")
        self.git("commit", "-qam", "Later")
        with self.assertRaisesRegex(ValueError, "checkout does not match"):
            provenance.validate(self.root, SOURCE, RELEASE)

    def test_build_git_description_must_select_the_source_tag(self):
        self.git("tag", "Z-conflicting-version")
        # The real describe call can prefer an annotated tag over a lightweight
        # alias; mock only that call to exercise a conflicting build version.
        original = subprocess.check_output
        def describe_conflict(command, **kwargs):
            if "describe" in command:
                return "Z-conflicting-version\n"
            return original(command, **kwargs)
        with mock.patch("subprocess.check_output", side_effect=describe_conflict):
            with self.assertRaisesRegex(ValueError, "Git build version"):
                provenance.validate(self.root, SOURCE, RELEASE)

    def test_missing_distribution_tag_is_rejected(self):
        self.git("tag", "-d", RELEASE)
        with self.assertRaisesRegex(ValueError, "existing local"):
            provenance.validate(self.root, SOURCE, RELEASE)

    def test_cli_records_provenance_as_github_outputs(self):
        output = self.root / ".git/github-output"
        with mock.patch.object(provenance, "ROOT", self.root), \
             mock.patch.object(sys, "argv", ["recovery_release_provenance.py", "--source-tag", SOURCE,
                 "--release-tag", RELEASE, "--github-output", str(output)]), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(provenance.main(), 0)
        result = json.loads(printed.call_args.args[0])
        self.assertIn("distribution_tag_object=" + self.original_object + "\n", output.read_text())
        self.assertEqual(result["source_commit"], self.source_commit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
