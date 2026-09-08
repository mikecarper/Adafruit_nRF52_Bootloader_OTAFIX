#!/usr/bin/env python3
"""Docker build contracts and the real installer shell with harmless tools."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="ascii")
RUNS = [line[4:] for line in re.sub(r"\\\n", " ", DOCKERFILE).splitlines()
        if line.startswith("RUN ")]
INSTALL = next(command for command in RUNS if "toolchain_host=" in command)
HASHES = {
    "amd64": "62a63b981fe391a9cbad7ef51b17e49aeaa3e7b0d029b36ca1e9c3b2a9b78823",
    "arm64": "87330bab085dd8749d4ed0ad633674b9dc48b237b61069e3b481abd364d0a684",
}

# All commands that could download or mutate the host are replaced. The
# actual Docker RUN body still controls architecture selection and ordering.
HARMLESS_TOOLS = r"""
dpkg() { printf '%s\n' "$OTAFIX_TEST_ARCH"; }
curl() {
    printf 'download:%s\n' "$*"
    test "$OTAFIX_TEST_CURL_FAIL" = 0
}
sha256sum() {
    read -r digest filename
    printf 'verify:%s:%s\n' "$digest" "$filename"
    test "$digest" = "$OTAFIX_TEST_HASH" || return 1
    test "$OTAFIX_TEST_HASH_FAIL" = 0
}
mkdir() { printf 'mkdir:%s\n' "$*"; }
tar() { printf 'extract:%s\n' "$*"; }
rm() { printf 'remove:%s\n' "$*"; }
"""


class DockerBuildTest(unittest.TestCase):
    def run_installer(self, arch, *, bad_hash=False, download_failure=False):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX shell is required for the Docker RUN test")
        env = dict(os.environ, OTAFIX_TEST_ARCH=arch,
                   OTAFIX_TEST_HASH=HASHES.get(arch, "unsupported"),
                   OTAFIX_TEST_HASH_FAIL=str(int(bad_hash)),
                   OTAFIX_TEST_CURL_FAIL=str(int(download_failure)))
        return subprocess.run([shell, "-c", HARMLESS_TOOLS + INSTALL],
                              env=env, capture_output=True, text=True, timeout=5)

    def test_both_supported_architectures_verify_before_extracting(self):
        for arch, host in (("amd64", "x86_64"), ("arm64", "aarch64")):
            with self.subTest(arch=arch):
                result = self.run_installer(arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = result.stdout
                self.assertIn(f"14.2.rel1-{host}-arm-none-eabi.tar.xz", output)
                self.assertIn("verify:" + HASHES[arch], output)
                self.assertLess(output.index("verify:"), output.index("extract:"))
                self.assertLess(output.index("extract:"), output.index("remove:"))

    def test_bad_checksum_never_extracts_or_installs(self):
        result = self.run_installer("amd64", bad_hash=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verify:", result.stdout)
        self.assertNotIn("mkdir:", result.stdout)
        self.assertNotIn("extract:", result.stdout)

    def test_failed_download_never_verifies_or_extracts(self):
        result = self.run_installer("arm64", download_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("verify:", result.stdout)
        self.assertNotIn("extract:", result.stdout)

    def test_unsupported_architecture_never_downloads(self):
        result = self.run_installer("armhf")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Only linux/amd64 and linux/arm64", result.stderr)
        self.assertNotIn("download:", result.stdout)

    def test_run_instructions_have_valid_posix_shell_syntax(self):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX shell is unavailable")
        for command in RUNS:
            result = subprocess.run([shell, "-n"], input=command, text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_toolchain_and_default_board_match_this_fork(self):
        self.assertNotIn("gcc-arm-none-eabi ", DOCKERFILE)
        self.assertIn("arm-none-eabi-gcc -dumpfullversion", DOCKERFILE)
        self.assertIn("= 14.2.1", DOCKERFILE)
        self.assertIn("      cmake ", DOCKERFILE)
        # Make's default PYTHON is "python", not "python3".
        self.assertIn("      python-is-python3 ", DOCKERFILE)
        command = json.loads(next(line[4:] for line in DOCKERFILE.splitlines()
                                  if line.startswith("CMD ")))
        self.assertEqual(command, ["make", "BOARD=wismesh_tag", "all"])
        self.assertTrue((ROOT / "src/boards/wismesh_tag/board.mk").is_file())

    def test_readme_distinguishes_qualification_and_release_builds(self):
        readme = (ROOT / "README.md").read_text(encoding="ascii")
        section = readme.split("## Building from source (Docker)", 1)[1]
        section = section.split("## Installation", 1)[0]
        self.assertIn("clean, exact OTAFIX release tag", section)
        self.assertIn("MOTA_BOOTLOADER_TEST_BUILD=1", section)
        self.assertIn("MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040601", section)
        self.assertIn("_mbr.uf2", section)
        self.assertNotIn("_nosd.uf2", section)

    def test_build_context_excludes_existing_artifacts_and_virtualenvs(self):
        excludes = (ROOT / ".dockerignore").read_text(encoding="ascii").splitlines()
        for pattern in ("_build-*", "cmake-build-*", ".venv", "venv", "**/.git"):
            self.assertIn(pattern, excludes)


if __name__ == "__main__":
    unittest.main()
