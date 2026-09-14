# G-switcher agent workflow

This repository uses OpenSpec as the required change-control layer for non-trivial product behavior changes.

## Before changing behavior

1. Read `openspec/config.yaml`.
2. Read the affected capability specs under `openspec/specs/`.
3. Check active changes with `openspec list --json`.
4. For a new non-trivial behavior change, use the `openspec-propose` workflow and create the proposal, delta specs, design when applicable, and tasks **before editing runtime code**.
5. Obtain explicit human approval of the planning artifacts before starting implementation.
6. Use `openspec-apply-change` for implementation and follow `tasks.md` with test-first evidence.
7. Before archive, use `openspec-verify-change`, strict validation, required repository tests, and any applicable manual compatibility evidence.
8. Sync approved delta specs into the living baseline and archive the completed change.

## Hard project invariants

Unless an explicitly approved OpenSpec change modifies the corresponding capability, preserve these rules:

- Runtime is local-only: no network dependency, cloud service, online account, telemetry, remote dictionary, or remote model.
- Normal operation runs as a standard user and does not request elevation to gain broader text access.
- Ambiguous, stale, unsupported, or unverifiable text state fails open: preserve the user's text rather than guess.
- Password and recognized secure/credential targets are excluded from text processing and mutation.
- The clipboard is not a fallback text-mutation mechanism.
- Typed, selected, contextual, pending-correction, and Undo text state is volatile and is not persisted or transmitted.
- Existing Windows E2E, security, provenance, malware-scan, and manual compatibility gates are additive requirements; OpenSpec validation never replaces them.
- `UNSUPPORTED/FAIL-OPEN` means safe non-support, not functional compatibility.

## What may bypass a full OpenSpec change

Pure spelling/comment corrections and similarly trivial documentation-only edits may be made directly. A pure internal refactor may omit a behavioral spec delta only when externally observable behavior, security/privacy boundaries, privileges, persistence, network behavior, mutation paths, and release gates are unchanged.

If uncertain whether a change is behavioral, treat it as behavioral and use OpenSpec.

## Agent skills

Codex-compatible workflows are committed under `.agents/skills/`:

- `openspec-explore`
- `openspec-propose`
- `openspec-apply-change`
- `openspec-update-change`
- `openspec-sync-specs`
- `openspec-verify-change`
- `openspec-archive-change`

Use the repository-pinned OpenSpec validation helper:

```powershell
pwsh -File scripts/openspec-validate.ps1
```

The CLI is pinned by repository tooling to OpenSpec 1.13.0 and telemetry is disabled in CI/helper scripts.
