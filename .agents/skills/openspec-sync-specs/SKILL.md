---
name: openspec-sync-specs
description: Merge an implemented change's delta specs into the living OpenSpec baseline without archiving the change.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Synchronize delta specs from an active change into `openspec/specs/` without archiving it.

## Workflow

1. Select the change and run `openspec status --change "<name>" --json`.
2. Read every delta spec path returned by status and the corresponding current main capability spec.
3. Obtain current specs guidance with `openspec instructions specs --change "<name>" --json` when available and obey `openspec/config.yaml`.
4. Apply ADDED, MODIFIED, REMOVED, and RENAMED requirements carefully; preserve unrelated requirements and scenarios.
5. Never invent behavior to resolve a conflict. If a delta cannot be reconciled with the living spec or implementation, stop and report the mismatch.
6. Run `openspec validate --all --strict --no-interactive --report findings` after the merge.
7. Confirm each delta is reflected exactly once in the main specs and that no empty or placeholder capability remains.

This workflow edits specifications only; it does not archive the change or implement code.
