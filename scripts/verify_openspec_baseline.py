#!/usr/bin/env python3
"""Structural guard for the G-switcher OpenSpec baseline.

This is intentionally small and dependency-free. OpenSpec itself performs schema
validation; this guard protects the project-specific capability inventory and a
few non-negotiable invariants against accidental deletion or migration drift.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SPECS = (
    "openspec/specs/configuration-and-ui/spec.md",
    "openspec/specs/conversion-core/spec.md",
    "openspec/specs/correction-feedback/spec.md",
    "openspec/specs/detector-and-context/spec.md",
    "openspec/specs/input-safety/spec.md",
    "openspec/specs/manual-controls-and-undo/spec.md",
    "openspec/specs/release-assurance/spec.md",
    "openspec/specs/secure-input-and-privacy/spec.md",
    "openspec/specs/verified-text-adapters/spec.md",
)

REQUIRED_SECTIONS = (
    "## Purpose",
    "## Requirements",
    "### Requirement:",
    "#### Scenario:",
)

REQUIRED_INVARIANTS = {
    "openspec/specs/input-safety/spec.md": ["fail open", "generation"],
    "openspec/specs/verified-text-adapters/spec.md": ["clipboard"],
    "openspec/specs/secure-input-and-privacy/spec.md": ["password", "network", "persist"],
    "openspec/specs/correction-feedback/spec.md": ["20%", "Undo"],
    "openspec/specs/release-assurance/spec.md": ["manual", "green CI"],
}


def fail(message: str) -> None:
    print(f"OpenSpec baseline guard: FAIL: {message}", file=sys.stderr)


def main() -> int:
    failures: list[str] = []

    for relative_path in EXPECTED_SPECS:
        path = REPO_ROOT / relative_path
        if not path.is_file():
            failures.append(f"missing capability spec: {relative_path}")
            continue

        text = path.read_text(encoding="utf-8")
        for marker in REQUIRED_SECTIONS:
            if marker not in text:
                failures.append(f"{relative_path}: missing required section/marker {marker!r}")

    for relative_path, required_phrases in REQUIRED_INVARIANTS.items():
        path = REPO_ROOT / relative_path
        if not path.is_file():
            # The missing-file error above is already more useful.
            continue
        folded = path.read_text(encoding="utf-8").casefold()
        for phrase in required_phrases:
            if phrase.casefold() not in folded:
                failures.append(f"{relative_path}: missing invariant phrase {phrase!r}")

    if failures:
        for message in failures:
            fail(message)
        return 1

    print(f"OpenSpec baseline guard: PASS ({len(EXPECTED_SPECS)} capability specs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
