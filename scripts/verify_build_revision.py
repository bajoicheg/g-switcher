#!/usr/bin/env python3
"""Verify that a CI build uses the exact event commit, not a moving branch tip."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


class VerificationError(RuntimeError):
    """A build cannot be bound to its requested source revision."""


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError("Git revision check could not execute.") from error
    if result.returncode != 0:
        # Do not echo stderr or filenames: a dirty tree may contain private data.
        raise VerificationError("Git revision check failed.")
    return result.stdout.strip()


def verify_revision(expected: str, root: Path, *, require_clean: bool = False) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{40}", expected) is None:
        raise VerificationError("Expected source revision must be a full 40-character Git SHA.")
    actual = _git(root, "rev-parse", "--verify", "HEAD")
    if actual.lower() != expected.lower():
        raise VerificationError("Checked-out HEAD does not match the exact event source SHA.")
    if require_clean and _git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise VerificationError("Build checkout is not clean; source provenance cannot be accepted.")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", default=os.environ.get("EXPECTED_SOURCE_SHA", ""))
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        actual = verify_revision(args.expected, Path.cwd(), require_clean=args.require_clean)
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Verified exact source revision: {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
