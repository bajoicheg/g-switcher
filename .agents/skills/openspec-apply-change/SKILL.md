---
name: openspec-apply-change
description: Implement an approved OpenSpec change task-by-task with tests and evidence.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Implement tasks from an approved OpenSpec change.

## Workflow

1. Select the intended active change; if ambiguous, use `openspec list --json` and ask the user to choose.
2. Run `openspec status --change "<name>" --json` and `openspec instructions apply --change "<name>" --json`.
3. Read every context file returned by OpenSpec plus affected baseline specs and nearby tests/code.
4. Obey `openspec/config.yaml`, especially fail-open, secure-input, privacy, local-only, privilege, and release-gate invariants.
5. Work through `tasks.md` in order. For behavior changes use test-first development: observe the relevant test fail, implement the minimum change, then make the test pass.
6. Run the task's required unit/integration/E2E or documentation validation before checking its box.
7. Mark `- [ ]` as `- [x]` only after completion evidence exists.
8. Stop on a material blocker or if implementation would require expanding approved scope; update the planning artifacts before continuing.
9. When all tasks are complete, run strict OpenSpec validation and the relevant existing repository gates. Then use `openspec-verify-change` before archive.

Never treat successful compilation or OpenSpec validation alone as evidence that G-switcher release compatibility is complete.
