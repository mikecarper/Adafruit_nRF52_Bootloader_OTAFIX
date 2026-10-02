#!/usr/bin/env python3
"""Validate a clean recovery source tag without moving its distribution tag."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from derive_otafix_version import derive

ROOT = Path(__file__).resolve().parents[1]


def recovery_version(tag):
    if not tag or not tag.startswith("R_"):
        raise ValueError("source and distribution tags must be canonical R_ recovery tags")
    return derive(tag, recovery_allow_all_boards=True)


def validate(root, source_tag, release_tag):
    """Return immutable Git provenance after checking source and wire versions."""
    packed = recovery_version(source_tag)
    if packed != recovery_version(release_tag):
        raise ValueError("source and distribution recovery tags have different packed versions")

    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(root), *args],
                                           text=True, stderr=subprocess.PIPE).strip()
        except subprocess.CalledProcessError as exc:
            raise ValueError("recovery provenance requires existing local source and distribution tags") from exc

    source_ref = "refs/tags/" + source_tag
    distribution_ref = "refs/tags/" + release_tag
    source_commit = git("rev-parse", "--verify", source_ref + "^{commit}")
    distribution_commit = git("rev-parse", "--verify", distribution_ref + "^{commit}")
    distribution_object = git("rev-parse", "--verify", distribution_ref)
    if git("rev-parse", "HEAD") != source_commit:
        raise ValueError("checkout does not match the exact recovery source tag")
    if git("status", "--porcelain"):
        raise ValueError("recovery source checkout must be clean")
    if git("describe", "--dirty", "--always", "--tags") != source_tag:
        raise ValueError("Git build version does not match the exact recovery source tag")
    return {"source_tag": source_tag, "source_commit": source_commit,
            "distribution_tag": release_tag,
            "distribution_tag_object": distribution_object,
            "distribution_tag_commit": distribution_commit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        provenance = validate(ROOT, args.source_tag, args.release_tag)
    except ValueError as exc:
        print(f"recovery_release_provenance: {exc}", file=sys.stderr)
        return 2
    if args.github_output:
        with args.github_output.open("a", encoding="ascii") as output:
            for name, value in provenance.items():
                output.write(f"{name}={value}\n")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
