---
name: openspec-verify-change
description: Verify that an implementation matches its OpenSpec proposal, specs, design, tasks, tests, and project constraints before archive.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires OpenSpec CLI 1.13.0 for this repository.
metadata:
  author: openspec
  version: "1.13.0"
---

Verify an implemented OpenSpec change before archive. This workflow is report-only.

## Workflow

1. Select the intended active change; if ambiguous, list active changes and ask the user to choose.
2. Run `openspec status --change "<name>" --json` and `openspec instructions apply --change "<name>" --json`.
3. Read all returned proposal/spec/design/task context files, affected living specs, implementation, and tests.
4. Build a scorecard for:
   - **Completeness** — every task complete and every delta requirement represented in implementation/evidence.
   - **Correctness** — implementation matches requirement intent and scenarios have appropriate test/manual evidence.
   - **Coherence** — implementation follows approved design and repository patterns without violating `openspec/config.yaml`.
5. Classify findings as CRITICAL, WARNING, or SUGGESTION. Every finding must name concrete evidence and an actionable fix.
6. Treat incomplete tasks, missing requirement implementation, or violation of hard security/privacy/fail-open constraints as CRITICAL.
7. Treat missing scenario coverage or spec/design divergence as WARNING unless it proves a hard requirement is unmet.
8. Finish with an archive-readiness assessment. Do not edit code, specs, tasks, or archive anything in this workflow.

For G-switcher, explicitly check security/privacy, secure-input exclusion, fail-open behavior, runtime network/persistence/privilege changes, and required Windows/manual compatibility evidence.
