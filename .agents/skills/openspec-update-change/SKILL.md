---
name: openspec-update-change
description: Revise existing OpenSpec planning artifacts so proposal, specs, design, and tasks remain coherent; never edit code.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Revise an existing change's planning artifacts without implementing code.

## Workflow

1. Select the active change and run `openspec status --change "<name>" --json`.
2. Read all existing artifact paths returned by status plus `openspec/config.yaml` and relevant baseline specs.
3. Identify inconsistencies, missing requirements, stale decisions, or task gaps introduced by the requested revision.
4. Revise only artifacts that already exist. Before a substantial rewrite, get current guidance with `openspec instructions <artifact-id> --change "<name>" --json`.
5. Show material proposed revisions and obtain user approval before writing them.
6. After edits, run `openspec validate "<name>" --strict --no-interactive`.
7. If implementation already exists, warn that code may now diverge and recommend applying/verifying the revised change.

Do not create missing artifacts in this workflow and do not edit project code.
