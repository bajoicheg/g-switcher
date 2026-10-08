# Diagnostic result recovery implementation plan

**Goal:** Preserve the exact already validated Word diagnostic candidate and identify publication rejection before further execution.
**Architecture:** A read-only host preflight reconstructs the lost Git object against base10b and accepts it only if its SHA is exactly3407a2d. It preserves a bundle and checks the exact conditional push in dry-run mode. A later package-managed takeover needs separately reviewed, independently authenticated quiescence and a concrete publication remedy.
**Tech stack:** Python, Git, Rustfmt1.98.1, GitHub Actions, canonical CDC2.12.1.
**Spec:** Previous blocked-handoff.json and canonical references/execution-ownership.md.

- Preserve all prior CI budgets, failed journal and successful result history; no package edits, release, source writes or lease changes in preflight.
- Validate worker/payload/evidence hashes, exact base, exact formatted tree and bounded commit timestamp reconstruction.
- Reject altered payload, missing checks, unmatched commit hash, or live source drift.
- Save result.bundle and formatted files before any remote dry-run.
- Query the completed original job and authenticate cleanup2943; save numeric/static conclusions only.
- Capture only allow-listed push rejection reason classes; never print credential-bearing Gitstderr.
- Required Windows exact-candidate gates remain mandatory before delivering an EXE.
