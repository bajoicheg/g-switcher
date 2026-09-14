---
name: openspec-archive-change
description: Archive a completed and verified OpenSpec change after syncing its delta specs into the living baseline.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Archive a completed OpenSpec change only after implementation and required evidence are complete.

## Workflow

1. Select the active change and inspect `openspec status --change "<name>" --json`.
2. Refuse archive if implementation tasks are incomplete or required G-switcher Windows/manual compatibility evidence is still outstanding.
3. Run `openspec validate --all --strict --no-interactive --report findings`.
4. Run the `openspec-verify-change` workflow and resolve CRITICAL findings before archive.
5. Synchronize the change's delta specs into the living baseline using `openspec-sync-specs` and verify the resulting main specs.
6. Run `openspec archive "<name>"` only after the sync and verification are clean.
7. Validate the resulting active specs and archived record again.
8. Summarize what shipped, which baseline capabilities changed, and the evidence used.

Archive is not a substitute for G-switcher's existing release promotion gates.
