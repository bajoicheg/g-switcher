# OpenSpec adoption design for G-switcher

Date: 2026-09-14
Status: design for review
Baseline: `release/2.0.1` at `6aaa3146cf9b077f708c65d7cefe70d064badff5`

## Context

G-switcher already has unusually strong product and release documentation: `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md`, `docs/SECURITY_MODEL.md`, release notes, compatibility matrices, manual test instructions, Rust unit/integration tests, Windows E2E tests, provenance checks, security checks, and a manual compatibility gate.

The problem is not lack of documentation. The problem is that feature intent, design decisions, implementation tasks, tests, and the final shipped behavior can still evolve in separate places. This is especially risky when AI agents perform a substantial part of the implementation: a chat instruction can be implemented correctly at the time but be difficult to reconstruct or verify later.

OpenSpec will be introduced as the change-control layer between an idea/bug and code. It must strengthen the existing release discipline, not replace or weaken it.

The current 2.0.1 release candidate is frozen behind PR #28 and manual Windows/browser compatibility testing. OpenSpec adoption must not change runtime behavior or silently redefine the 2.0.1 acceptance bar.

## Goals

1. Make each non-trivial behavior change start from an explicit, versioned proposal and delta specification before implementation.
2. Keep an auditable history of why a change was made, what behavior was intended, how it was designed, and which tasks implemented it.
3. Maintain a living baseline specification of the shipped product after changes are archived.
4. Give AI coding agents persistent project constraints, especially fail-open, privacy, secure-input, privilege, local-only, compatibility, and test requirements.
5. Make divergence between implementation and specification visible in CI/review before release.
6. Preserve the existing Rust/Windows release assurance and manual compatibility gates.
7. Keep the process lightweight enough that tiny documentation-only changes do not require unnecessary ceremony.

## Non-goals

- Do not rewrite G-switcher as part of OpenSpec adoption.
- Do not change detector thresholds, mutation logic, UI, hotkeys, data handling, privileges, or supported applications.
- Do not remove the current 2.0.1 release/manual gates.
- Do not replace GitHub pull requests, code review, unit tests, E2E tests, Clippy, provenance checks, Defender checks, or manual compatibility testing.
- Do not introduce a runtime Node.js dependency. OpenSpec is a development/CI tool only.
- Do not introduce runtime network access, telemetry, cloud services, or user-account requirements into G-switcher.
- Do not create a custom OpenSpec schema until the standard schema proves insufficient.

## Options considered

### Option A — OpenSpec as an additional documentation folder only

Keep the existing functional specification as the permanent source of truth and use OpenSpec only for change proposals.

Advantages: lowest migration effort.

Disadvantages: two long-term sources of behavioral truth would drift. AI agents could satisfy one while missing the other.

Decision: rejected as the long-term model.

### Option B — Standard OpenSpec workflow plus G-switcher project rules

Use OpenSpec's built-in `spec-driven` workflow (`proposal -> specs/design -> tasks -> apply`) and put G-switcher-specific requirements into `openspec/config.yaml`. Migrate the current product behavior into capability specs, then use delta specs for future changes.

Advantages: minimal custom machinery, easy OpenSpec upgrades, strong agent guidance, explicit change history, and a clear path to one living behavioral baseline.

Disadvantages: requires a one-time baseline migration and careful cross-checking against the existing specification and tests.

Decision: **selected**.

### Option C — Custom OpenSpec schema with separate security/release artifacts

Fork the schema and make security review, privacy review, or release evidence mandatory first-class artifacts.

Advantages: maximum enforcement.

Disadvantages: more local schema code to maintain and more coupling to OpenSpec internals before we know that it is necessary.

Decision: defer. Reconsider only after real usage demonstrates a gap that cannot be expressed cleanly with project context, artifact rules, tasks, and CI.

## Architecture and source-of-truth model

OpenSpec will live in the repository root.

```text
openspec/
  config.yaml
  specs/
    conversion-core/spec.md
    detector-and-context/spec.md
    input-safety/spec.md
    verified-text-adapters/spec.md
    secure-input-and-privacy/spec.md
    manual-controls-and-undo/spec.md
    configuration-and-ui/spec.md
    correction-feedback/spec.md
    release-assurance/spec.md
  changes/
    <change-name>/
      proposal.md
      specs/<capability>/spec.md
      design.md
      tasks.md
    archive/
```

The initial adoption is transitional:

1. During baseline creation, the existing 2.0.1 documentation and tests remain authoritative for the release candidate.
2. Baseline OpenSpec capability specs are derived from the reviewed 2.0.1 behavior and cross-checked against `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md`, `docs/SECURITY_MODEL.md`, README, and the implementation.
3. No runtime code change is allowed in the baseline migration.
4. After the baseline is reviewed and accepted, `openspec/specs/` becomes the primary living behavioral specification for future changes. Release-specific documents remain release evidence/snapshots rather than a competing live specification.
5. `docs/SECURITY_MODEL.md` remains the deeper threat/security model unless a later dedicated migration decides to decompose it. OpenSpec changes must reference and preserve its invariants.

## Capability boundaries

The first baseline should be split by stable behavior rather than by source file.

### `conversion-core`

RU/EN physical-layout conversion semantics, boundaries, case preservation, layout switching, successful replacement semantics.

### `detector-and-context`

Detector v3 decision model, confidence profiles, dictionaries/frequency data, short-token ambiguity, context retention, code-safe behavior.

### `input-safety`

Generation-bound state, focus/process/thread/layout/caret checks, hook-thread constraints, fail-open rules, liveness requirements, bounded failure behavior.

### `verified-text-adapters`

Supported Edit/RichEdit/UIA mutation paths, exact pre/post verification, no clipboard fallback, unsupported-target behavior.

### `secure-input-and-privacy`

Password/credential exclusion, UIA metadata-only password checks, volatile typed context, persistence boundaries, no runtime network/telemetry/cloud.

### `manual-controls-and-undo`

Current word, previous word, selected text, Undo, Pause/Resume, hotkey semantics, stale-context refusal.

### `configuration-and-ui`

Settings, first-run flow, per-application modes, user dictionary, sensitivity, autostart, hotkey validation, standard-user behavior.

### `correction-feedback`

Successful-correction sound, default enabled state, 20% default volume, 0-100% control, in-memory waveform, no sound on refused/failed operations or Undo.

### `release-assurance`

Required automated and manual evidence for release promotion, including locked dependencies, formatting/tests/Clippy, Windows E2E, stress/failure paths, release checks, provenance, malware scan evidence, and the rule that green CI alone is insufficient where manual compatibility remains required.

## Project configuration

Use the stock `spec-driven` schema. Do not fork it in the first adoption.

`openspec/config.yaml` will inject permanent context that includes at least:

- Rust 2021 Windows desktop application.
- Standard-user execution; no elevation required for normal use.
- Local-only runtime; no runtime network access, cloud services, account, telemetry, remote dictionary, or remote model.
- Ambiguity and unverifiable state fail open: preserve the user's text rather than guess.
- Password/secure inputs are excluded from processing.
- Clipboard fallback is forbidden for text mutation.
- Typed/selected text must not be persisted or transmitted.
- Existing release and manual compatibility gates may be strengthened but not weakened implicitly.
- Dependency graph is locked for release assurance.
- Runtime behavior changes require tests at the lowest practical level plus the relevant Windows E2E/manual evidence.

Artifact-specific rules will require the following.

### Proposal rules

Every non-trivial behavior change must explicitly cover:

- Problem
- Goal
- Non-goals
- User-visible changes
- Security impact
- Data/privacy impact
- Privilege impact
- Dependencies
- Compatibility impact
- Rollback
- Test/acceptance impact

A proposal that changes network behavior, persistence, secure-input handling, privilege requirements, text-access scope, mutation paths, or release gates must call that out explicitly.

### Spec rules

- State behavior normatively and testably.
- Include explicit success and failure scenarios.
- Preserve fail-open behavior unless the proposal explicitly changes it and receives review.
- For security/privacy-sensitive behavior, include negative scenarios showing what the program must *not* do.
- Do not claim support for applications or control classes without corresponding evidence requirements.

### Design rules

When `design.md` is warranted, include:

- current architecture/context;
- proposed architecture;
- alternatives considered;
- data/control flow;
- security and privacy analysis;
- failure modes and fail-open behavior;
- backward compatibility/migration;
- observability/logging impact;
- test strategy;
- rollback strategy.

### Task rules

- Prefer test-first tasks for behavior changes.
- Separate spec/tests, implementation, verification, and documentation/release evidence tasks.
- Every task must have an observable completion condition.
- Do not mark a task complete merely because code compiles.
- Add relevant unit/integration/E2E/manual verification tasks based on the affected capability.

## Development workflow

For a normal non-trivial change:

```text
Idea / bug
  -> explore
  -> proposal
  -> delta specs + design where needed
  -> tasks
  -> human review/approval
  -> test-first implementation
  -> automated verification
  -> manual compatibility evidence where required
  -> OpenSpec validation/verification
  -> PR/release gate
  -> archive
  -> living specs updated
```

Tiny typo/comment-only changes can bypass OpenSpec. Pure internal refactors with no behavior change may use a lightweight proposal/tasks path or explicitly declare that no spec delta is required, but they still must not silently alter security/privacy/release invariants.

## AI-agent policy

AI agents working on the repository must treat OpenSpec and repository constraints as binding project context, not suggestions.

Before implementation of a non-trivial behavior change, the agent must:

1. identify the affected capabilities;
2. read the current capability specs;
3. read the active change artifacts;
4. resolve material open questions before coding;
5. implement against `tasks.md` and mark tasks complete only with evidence;
6. surface out-of-scope findings instead of silently expanding scope.

For Codex/OpenSpec integration, use OpenSpec's Codex skills support. Generated tool instructions must be committed so a fresh agent session receives the same workflow.

## CI integration

OpenSpec validation is additive to the existing Windows/Rust gates.

Initial CI design:

1. Pin the OpenSpec CLI to a reviewed version rather than tracking `latest` implicitly. Initial target: `@fission-ai/openspec@1.13.0`.
2. Use Node.js >= 20.19 only in the OpenSpec validation job; do not add Node to the application runtime.
3. Set `OPENSPEC_TELEMETRY=0` in CI.
4. Run strict validation for the complete OpenSpec workspace on pull requests that modify OpenSpec artifacts and on release branches.
5. Fail CI on invalid OpenSpec structure or invalid delta specifications.
6. Keep OpenSpec validation logically separate from the Windows binary build so a documentation/tooling failure cannot obscure runtime test results.
7. Do not allow OpenSpec validation to substitute for unit, integration, Clippy, E2E, provenance, Defender, or manual compatibility gates.

A later iteration may add a repository helper script so developers and agents run exactly the same pinned validation command locally and in CI.

## Baseline migration strategy

The baseline migration is a documentation/specification exercise, not a feature release.

1. Create OpenSpec structure and project rules.
2. Create the nine baseline capability specs from the 2.0.1 reviewed state.
3. Build a traceability map from current requirements/tests to capability specs.
4. Check for contradictions, omissions, and accidental weakening of requirements.
5. Run OpenSpec validation.
6. Add CI validation.
7. Only after the baseline is accepted, require new behavioral work to go through OpenSpec changes.

Existing historical documents are not deleted during adoption. This keeps release evidence intact and gives us a safe comparison point during migration.

## First real OpenSpec change

The first *behavioral* change after baseline adoption should be deliberately small but testable. It must exercise the whole workflow: proposal, delta spec, design decision if needed, tasks, test-first implementation, CI validation, verification, and archive.

Do not use the baseline migration itself as proof that the behavioral workflow works; baseline migration does not change runtime behavior.

## Branch and rollout plan

The adoption work starts from the validated 2.0.1 candidate commit `6aaa3146cf9b077f708c65d7cefe70d064badff5` on a separate branch, `chore/openspec-adoption`.

This branch must not modify PR #28's release candidate while its manual gate is open.

Expected rollout:

1. Design-only commit.
2. Review design.
3. Add OpenSpec scaffold/config and baseline specs.
4. Add agent instructions and pinned validation helper/CI job.
5. Validate all artifacts and review traceability against the existing 2.0.1 specification/tests.
6. After PR #28 is merged to `main`, rebase/retarget the adoption work onto the resulting `main` history before merge. Do not merge adoption into the frozen release candidate solely to obtain OpenSpec.

## Security and privacy impact

OpenSpec itself is a development-time dependency. It must not be linked into or shipped with the G-switcher executable.

The OpenSpec CLI version used in CI is pinned and telemetry is disabled in CI. Local developer telemetry is a machine-level OpenSpec setting and should be disabled in the documented setup for this security-sensitive project.

No project specification may contain captured user text, passwords, secrets, production data, or sensitive test content. Test strings must remain synthetic/public fixtures.

OpenSpec adoption must not broaden G-switcher's text-reading surface, persistence, network access, privilege requirements, secure-input behavior, or telemetry.

## Failure modes and rollback

### OpenSpec tooling breaks or changes incompatibly

The application remains buildable because OpenSpec is not a runtime dependency. Pinning limits surprise upgrades. If the tool becomes unavailable, the Markdown specs and archived changes remain readable in Git and the last known working CLI can be restored.

### Baseline spec contradicts current behavior

Treat this as a migration defect, not as permission to change code. Resolve the discrepancy against reviewed 2.0.1 behavior, tests, and release evidence before declaring the baseline authoritative.

### Process becomes too heavy

Use the standard schema's ability to omit unnecessary design work and allow lightweight handling for no-behavior refactors. Do not solve process friction by removing security/privacy/release invariants.

### OpenSpec CI fails while runtime CI passes

The PR remains unmergeable until the specification defect is corrected. Runtime success is not evidence that the intended behavior is documented correctly.

## Acceptance criteria for adoption

OpenSpec adoption is complete when all of the following are true:

1. `openspec/config.yaml` exists and validates with the standard `spec-driven` schema.
2. Baseline capability specs cover the reviewed 2.0.1 behavior without intentionally changing runtime behavior.
3. Security/privacy/fail-open/local-only constraints are encoded in persistent project context/rules.
4. Codex-compatible OpenSpec skills/instructions are present in the repository.
5. A pinned OpenSpec validation command is reproducible locally and in CI.
6. CI rejects structurally invalid OpenSpec changes.
7. Existing Rust/Windows/security/manual release gates remain intact.
8. A traceability review finds no known material contradiction between baseline OpenSpec specs, current functional/security/acceptance documents, and tested 2.0.1 behavior.
9. The first later behavioral change can be executed end-to-end through proposal -> specs/design -> tasks -> implementation -> verification -> archive.

## Decision

Adopt OpenSpec using the built-in `spec-driven` workflow, repository-local specs and changes, G-switcher-specific project rules, pinned validation, and Codex skills. Migrate the current 2.0.1 behavior into capability specs before making OpenSpec the living source of behavioral truth. Keep the existing release assurance intact and keep OpenSpec out of the runtime binary.
