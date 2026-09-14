#!/usr/bin/env python3
"""Structural guard for the G-switcher OpenSpec baseline.

This is intentionally small and dependency-free. OpenSpec itself performs schema
validation; this guard protects the project-specific capability inventory,
Codex workflow inventory, repository policy, and a few non-negotiable invariants
against accidental deletion or migration drift.
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

EXPECTED_SKILLS = (
    ".agents/skills/openspec-apply-change/SKILL.md",
    ".agents/skills/openspec-archive-change/SKILL.md",
    ".agents/skills/openspec-explore/SKILL.md",
    ".agents/skills/openspec-propose/SKILL.md",
    ".agents/skills/openspec-sync-specs/SKILL.md",
    ".agents/skills/openspec-update-change/SKILL.md",
    ".agents/skills/openspec-verify-change/SKILL.md",
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

    policy_path = REPO_ROOT / "AGENTS.md"
    if not policy_path.is_file():
        failures.append("missing repository agent policy: AGENTS.md")
    else:
        policy_text = policy_path.read_text(encoding="utf-8").casefold()
        for phrase in ("openspec", "explicit human approval", "fails open", "unsupported/fail-open"):
            if phrase.casefold() not in policy_text:
                failures.append(f"AGENTS.md: missing workflow/safety phrase {phrase!r}")

    config_path = REPO_ROOT / "openspec/config.yaml"
    if not config_path.is_file():
        failures.append("missing OpenSpec project config: openspec/config.yaml")
    else:
        config_text = config_path.read_text(encoding="utf-8")
        if "schema: spec-driven" not in config_text:
            failures.append("openspec/config.yaml: expected stock schema 'spec-driven'")
        for invariant in ("fails open", "Clipboard fallback", "must not be persisted or transmitted"):
            if invariant.casefold() not in config_text.casefold():
                failures.append(f"openspec/config.yaml: missing project invariant {invariant!r}")

    for relative_path in EXPECTED_SKILLS:
        path = REPO_ROOT / relative_path
        if not path.is_file():
            failures.append(f"missing Codex OpenSpec skill: {relative_path}")
            continue
        text = path.read_text(encoding="utf-8")
        expected_name = path.parent.name
        if f"name: {expected_name}" not in text:
            failures.append(f"{relative_path}: frontmatter name does not match {expected_name!r}")

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
            continue
        folded = path.read_text(encoding="utf-8").casefold()
        for phrase in required_phrases:
            if phrase.casefold() not in folded:
                failures.append(f"{relative_path}: missing invariant phrase {phrase!r}")

    if failures:
        for message in failures:
            fail(message)
        return 1

    print(
        "OpenSpec baseline guard: PASS "
        f"({len(EXPECTED_SPECS)} capability specs, {len(EXPECTED_SKILLS)} Codex skills, AGENTS policy)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
