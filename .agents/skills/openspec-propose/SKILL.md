---
name: openspec-propose
description: Create a complete OpenSpec change proposal with specs, design when needed, and tasks, without implementing code.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Create a reviewable OpenSpec change plan. Planning only: do not edit project code.

## Workflow

1. Resolve project context with `openspec context --json`; stop if no OpenSpec root exists.
2. Read `openspec/config.yaml`, relevant baseline specs, implementation, tests, and docs.
3. Derive or use a kebab-case change name and create it with `openspec new change "<name>"`.
4. Repeatedly run `openspec status --change "<name>" --json` and build the required artifacts in dependency order.
5. Before writing each artifact, run `openspec instructions <artifact-id> --change "<name>" --json` and obey its template, project context, and artifact rules.
6. Re-read completed dependency artifacts from disk before drafting dependent artifacts.
7. Create all artifacts transitively required for apply. Respect `skip_specs` and conditional design guidance only when OpenSpec says they apply.
8. Run `openspec validate "<name>" --strict --no-interactive` before presenting the proposal.
9. Stop after planning. Summarize the created artifacts and ask for explicit review/approval before implementation.

For G-switcher, proposals must explicitly cover security, privacy/data, privilege, compatibility, rollback, and test/release impact as required by `openspec/config.yaml`.
