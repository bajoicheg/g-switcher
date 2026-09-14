# OpenSpec Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce OpenSpec 1.13.0 as the repository's spec-driven change-control layer without changing G-switcher 2.0.1 runtime behavior or weakening existing release gates.

**Architecture:** Keep the stock OpenSpec `spec-driven` schema, store persistent G-switcher constraints in `openspec/config.yaml`, migrate the reviewed 2.0.1 behavior into nine capability specs, install Codex-compatible OpenSpec skills including optional verify, and add a separate strict validation workflow. Existing Rust/Windows/security/manual compatibility gates remain authoritative for 2.0.1 and continue unchanged.

**Tech Stack:** Rust 2021, Windows desktop APIs, Markdown/YAML, OpenSpec `@fission-ai/openspec@1.13.0`, Node.js >= 20.19.0 for development/CI only, PowerShell 7 for helper scripts, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-14-openspec-adoption-design.md`

## Global Constraints

- Baseline is `release/2.0.1` commit `6aaa3146cf9b077f708c65d7cefe70d064badff5`.
- Work remains on `chore/openspec-adoption`; do not modify the frozen `release/2.0.1` candidate or PR #28.
- Runtime behavior, detector thresholds, mutation logic, UI, hotkeys, data handling, privileges and supported applications MUST NOT change during baseline migration.
- OpenSpec is a development/CI dependency only; no Node.js or OpenSpec runtime dependency is added to G-switcher.
- OpenSpec CLI is pinned to `@fission-ai/openspec@1.13.0`; Node.js floor is `20.19.0`.
- Set `OPENSPEC_TELEMETRY=0` in repository helper scripts and CI.
- Keep the built-in `spec-driven` schema; do not fork a custom schema in this adoption.
- Standard-user execution, local-only runtime, fail-open behavior, secure-input exclusion, no clipboard fallback, volatile typed/selected text, and no runtime telemetry/network/cloud remain hard invariants.
- Existing Rust/Windows/security/provenance/Defender/manual compatibility release gates may be strengthened but MUST NOT be replaced or weakened by OpenSpec validation.
- Baseline specs use OpenSpec main-spec format: `# ... Specification`, `## Purpose`, `## Requirements`, `### Requirement: ...`, and one or more `#### Scenario: ...` blocks for every requirement.
- Future non-trivial behavior changes follow proposal -> specs/design -> tasks -> human approval -> test-first implementation -> automated/manual evidence -> verify -> archive.

---

### Task 1: Add OpenSpec project configuration and reproducible tooling

**Files:**
- Create: `openspec/config.yaml`
- Create: `scripts/openspec-validate.ps1`
- Create: `scripts/openspec-refresh-skills.ps1`
- Create: `.agents/skills/openspec-explore/SKILL.md`
- Create: `.agents/skills/openspec-propose/SKILL.md`
- Create: `.agents/skills/openspec-apply-change/SKILL.md`
- Create: `.agents/skills/openspec-update-change/SKILL.md`
- Create: `.agents/skills/openspec-sync-specs/SKILL.md`
- Create: `.agents/skills/openspec-archive-change/SKILL.md`
- Create: `.agents/skills/openspec-verify-change/SKILL.md`

**Interfaces:**
- Consumes: OpenSpec 1.13.0 `spec-driven` schema and Codex skill generator.
- Produces: repository-local OpenSpec config, one canonical strict-validation command, and seven committed Codex-compatible workflows.

- [ ] **Step 1: Create `openspec/config.yaml` with stock schema and project invariants**

Use this structure exactly; keep rules concise because they are injected into every artifact instruction:

```yaml
schema: spec-driven

context: |
  Product: G-switcher 2.0.x, a Rust 2021 Windows desktop utility for RU/EN keyboard-layout correction.
  Normal runtime is local-only: no network access, cloud service, account, telemetry, remote dictionary, or remote model.
  Normal operation runs as a standard user and does not require elevation.
  Ambiguous or unverifiable state fails open: preserve the user's text rather than guess or mutate an unverified target.
  Password and recognized secure/credential inputs are excluded from processing.
  Clipboard fallback for text mutation is forbidden.
  Typed, selected, contextual, pending-correction and Undo text state is volatile and must not be persisted or transmitted.
  Existing Rust/Windows/security/provenance/Defender/manual compatibility gates may be strengthened but not weakened implicitly.
  Runtime behavior changes require tests at the lowest practical level plus relevant Windows E2E/manual compatibility evidence.
  Specs describe behavior; design/tasks hold implementation detail.

rules:
  proposal:
    - Include explicit Problem, Goal, Non-goals, User-visible changes, Security impact, Data/privacy impact, Privilege impact, Dependencies, Compatibility impact, Rollback, and Test/acceptance impact coverage.
    - Explicitly call out any change to network behavior, persistence, secure-input handling, privilege requirements, text-access scope, mutation paths, or release gates.
    - Do not claim application/control support without corresponding evidence requirements.
  specs:
    - Use SHALL/MUST for normative behavior and include explicit success and failure scenarios.
    - Preserve fail-open behavior unless the approved proposal explicitly changes it.
    - Security/privacy-sensitive behavior requires negative scenarios describing what G-switcher must not do.
    - Keep implementation choices out of behavioral requirements.
  design:
    - Cover current context, proposed architecture, alternatives, data/control flow, security/privacy, failure modes, fail-open behavior, compatibility/migration, observability/logging impact, test strategy, and rollback when relevant.
    - Resolve questions that would change scope, requirements, or task breakdown before implementation.
  tasks:
    - Prefer test-first ordering for behavior changes.
    - Separate specification/tests, implementation, verification, and documentation/release-evidence work.
    - Every checkbox must have an observable completion condition; compiling alone is not completion.
    - Add unit/integration/E2E/manual verification tasks appropriate to the affected capability.

operations:
  apply:
    guidance:
      - Read affected baseline specs and the active change artifacts before editing code.
      - Run the relevant tests before marking each implementation task complete.
      - Surface out-of-scope findings instead of silently expanding scope.
  archive:
    guidance:
      - Run strict OpenSpec validation and openspec-verify-change before archive.
      - Do not archive while required Windows/manual compatibility evidence is incomplete.
```

- [ ] **Step 2: Add one pinned validation helper**

Create `scripts/openspec-validate.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$env:OPENSPEC_TELEMETRY = '0'

$package = '@fission-ai/openspec@1.13.0'
& npx --yes $package validate --all --strict --no-interactive --report findings
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
```

- [ ] **Step 3: Add reproducible Codex skill refresh helper**

Create `scripts/openspec-refresh-skills.ps1`. It MUST isolate OpenSpec's machine-level profile under a temporary `XDG_CONFIG_HOME`, select skills-only delivery, configure the custom workflow set `propose, explore, apply, update, sync, archive, verify`, run pinned `openspec init --tools codex --profile custom`, and restore the previous environment in `finally`. The script MUST set `OPENSPEC_TELEMETRY=0` and MUST NOT modify the user's real OpenSpec profile.

Use a temporary config file with this exact JSON model before calling init:

```json
{
  "profile": "custom",
  "delivery": "skills",
  "workflows": ["propose", "explore", "apply", "update", "sync", "archive", "verify"]
}
```

- [ ] **Step 4: Generate the seven Codex skills from OpenSpec 1.13.0**

Run from repository root:

```powershell
pwsh -File scripts/openspec-refresh-skills.ps1
```

Expected repository output:

```text
.agents/skills/openspec-explore/SKILL.md
.agents/skills/openspec-propose/SKILL.md
.agents/skills/openspec-apply-change/SKILL.md
.agents/skills/openspec-update-change/SKILL.md
.agents/skills/openspec-sync-specs/SKILL.md
.agents/skills/openspec-archive-change/SKILL.md
.agents/skills/openspec-verify-change/SKILL.md
```

Codex uses skills, so no slash-command directory is required.

- [ ] **Step 5: Verify configuration and generated skill inventory**

Run:

```powershell
$env:OPENSPEC_TELEMETRY='0'
npx --yes @fission-ai/openspec@1.13.0 list --specs
Get-ChildItem .agents/skills -Directory | Select-Object -ExpandProperty Name | Sort-Object
```

Expected: OpenSpec resolves the project without configuration warnings, and the sorted skill list contains exactly the seven `openspec-*` directories listed above.

- [ ] **Step 6: Commit Task 1**

```bash
git add openspec/config.yaml scripts/openspec-validate.ps1 scripts/openspec-refresh-skills.ps1 .agents/skills
git commit -m "build: initialize OpenSpec workflow"
```

---

### Task 2: Migrate G-switcher 2.0.1 into nine baseline capability specs

**Files:**
- Create: `openspec/specs/conversion-core/spec.md`
- Create: `openspec/specs/detector-and-context/spec.md`
- Create: `openspec/specs/input-safety/spec.md`
- Create: `openspec/specs/verified-text-adapters/spec.md`
- Create: `openspec/specs/secure-input-and-privacy/spec.md`
- Create: `openspec/specs/manual-controls-and-undo/spec.md`
- Create: `openspec/specs/configuration-and-ui/spec.md`
- Create: `openspec/specs/correction-feedback/spec.md`
- Create: `openspec/specs/release-assurance/spec.md`
- Read-only source material: `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md`, `docs/SECURITY_MODEL.md`, `README.md`, `COMPATIBILITY_2.0.1.md`

**Interfaces:**
- Consumes: reviewed 2.0.1 behavioral/security/release documentation and tested behavior.
- Produces: primary living behavior baseline for future OpenSpec deltas after adoption is accepted.

- [ ] **Step 1: Write `conversion-core` main spec**

Requirements MUST cover supported RU/EN layout pair, physical-key mapping, token boundaries including OEM-key cases, case preservation, exact focused-target semantics, layout switching/confirmation, and fail-open behavior when safe replacement cannot be proven.

Include scenarios for at least:

```text
rjhj,jxrf. -> коробочка.
,kz -> бля
lowercase / Initial / ALL CAPS preservation
unsupported layout remains unchanged
```

- [ ] **Step 2: Write `detector-and-context` main spec**

Requirements MUST cover Detector v3 evidence classes and precedence, conservative default, sensitivity profiles, exact source protection, deterministic target recognition, generated frequency layer constraints, short-token ambiguity, two-word volatile context, user dictionary influence, code-safe behavior, and unchanged fail-open collision policy.

- [ ] **Step 3: Write `input-safety` main spec**

Requirements MUST cover dedicated low-level hook dispatch, bounded callback work, generation-bound context, re-checking focus/process/thread/layout/caret/selection/exact range state, invalidation events, partial/zero-progress `SendInput`, bounded hung/closing target behavior, and recovery on a fresh target after failure.

- [ ] **Step 4: Write `verified-text-adapters` main spec**

Requirements MUST cover plain Win32 Edit, supported RichEdit/UIA path, browser UIA/LegacyIAccessible verified paths only to the extent currently claimed, exact pre/post verification, bounded liveness preflight, unsupported target fail-open, and the explicit prohibition on clipboard fallback.

- [ ] **Step 5: Write `secure-input-and-privacy` main spec**

Requirements MUST cover native password/credential exclusion, metadata-only UIA `IsPassword` probing for secure-input decisions, refusal when a non-plain target cannot be safely verified, volatile candidate/context/selection/Undo state, persistence limited to explicit settings, local-only runtime, and no telemetry/network/cloud/account requirement.

- [ ] **Step 6: Write `manual-controls-and-undo` main spec**

Requirements MUST cover current-word conversion, previous-word conversion, selected-text conversion, five configurable hotkeys with current defaults, duplicate-hotkey rejection, Pause/Resume, one-shot verified Undo, stale context refusal, modifier handling, and Disabled-mode/secure-input overrides.

- [ ] **Step 7: Write `configuration-and-ui` main spec**

Requirements MUST cover settings categories, first-run flow, autostart state synchronization, per-application Auto/Manual only/Disabled modes, user dictionary, sensitivity, hotkeys, standard-user operation, startup failure reporting, 900x680 settings usability target, and cancellation of first-run without marking onboarding complete.

- [ ] **Step 8: Write `correction-feedback` main spec**

Requirements MUST cover one short sound only after confirmed successful automatic/manual/previous/selected-text conversion, default enabled state, 20% default volume, 0-100% control in 5% steps, no sound for refused/failed conversion, secure input, Pause, or Undo, and in-memory generated PCM with no external asset/network/recorded text.

- [ ] **Step 9: Write `release-assurance` main spec**

Requirements MUST cover locked dependency graph, format/tests/Clippy, Windows same-process and cross-process E2E, browser adapter tests, 100,000-callback stress gate, hung/closing-target failure tests, release/branding/provenance checks, Defender scan evidence, SHA-256 artifacts, GUI subsystem/version metadata checks, and the rule that green CI is necessary but not sufficient while manual compatibility evidence is incomplete.

- [ ] **Step 10: Strictly validate all nine baseline specs**

Run:

```powershell
pwsh -File scripts/openspec-validate.ps1
```

Expected:

```text
9 specs validated
0 failed
```

Warnings fail because `--strict` is enabled.

- [ ] **Step 11: Confirm no runtime file changed in Task 2**

Run:

```bash
git diff --name-only HEAD -- src tests Cargo.toml Cargo.lock build.rs assets
```

Expected: no output.

- [ ] **Step 12: Commit Task 2**

```bash
git add openspec/specs
git commit -m "docs: add OpenSpec 2.0.1 baseline specs"
```

---

### Task 3: Add traceability and machine-check the adoption baseline

**Files:**
- Create: `docs/OPENSPEC_TRACEABILITY.md`
- Create: `scripts/verify_openspec_baseline.py`

**Interfaces:**
- Consumes: the nine baseline specs and existing 2.0.1 specification/security/acceptance sources.
- Produces: human-reviewable mapping plus a lightweight structural guard against accidental deletion of baseline capabilities or core invariants.

- [ ] **Step 1: Create the traceability matrix**

`docs/OPENSPEC_TRACEABILITY.md` MUST contain one row per OpenSpec capability with these columns:

```text
OpenSpec capability | Primary legacy sources | Existing automated evidence | Existing manual/release evidence | Migration notes
```

Each row MUST point to concrete repository files/tests rather than generic phrases. Include an explicit statement that any discrepancy discovered during baseline migration is a migration defect, not authorization to change 2.0.1 runtime behavior.

- [ ] **Step 2: Write baseline guard tests first**

Create `scripts/verify_openspec_baseline.py` that exits non-zero unless all nine expected spec paths exist and each contains `## Purpose`, `## Requirements`, at least one `### Requirement:`, and at least one `#### Scenario:`. The script MUST also check these invariant phrases across the appropriate capability specs:

```python
REQUIRED_INVARIANTS = {
    "openspec/specs/input-safety/spec.md": ["fail open", "generation"],
    "openspec/specs/verified-text-adapters/spec.md": ["clipboard"],
    "openspec/specs/secure-input-and-privacy/spec.md": ["password", "network", "persist"],
    "openspec/specs/correction-feedback/spec.md": ["20%", "Undo"],
    "openspec/specs/release-assurance/spec.md": ["manual", "green CI"],
}
```

Comparison may be case-insensitive, but failure output MUST name the missing file/section/invariant.

- [ ] **Step 3: Run the baseline guard**

```bash
python scripts/verify_openspec_baseline.py
```

Expected output:

```text
OpenSpec baseline guard: PASS (9 capability specs)
```

- [ ] **Step 4: Run OpenSpec strict validation again**

```powershell
pwsh -File scripts/openspec-validate.ps1
```

Expected: all nine specs pass with no strict warnings.

- [ ] **Step 5: Commit Task 3**

```bash
git add docs/OPENSPEC_TRACEABILITY.md scripts/verify_openspec_baseline.py
git commit -m "test: add OpenSpec baseline traceability guard"
```

---

### Task 4: Add an independent GitHub Actions OpenSpec gate

**Files:**
- Create: `.github/workflows/openspec.yml`

**Interfaces:**
- Consumes: `scripts/openspec-validate.ps1`, `scripts/verify_openspec_baseline.py`, committed specs/config.
- Produces: a Linux-based documentation/specification gate independent from the Windows binary CI.

- [ ] **Step 1: Add the CI workflow**

Create `.github/workflows/openspec.yml` with:

```yaml
name: OpenSpec

on:
  pull_request:
  push:
    branches:
      - main
      - 'release/**'
      - 'chore/openspec-*'

permissions:
  contents: read

env:
  OPENSPEC_TELEMETRY: '0'

jobs:
  validate:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20.19.0'
          cache: 'npm'
          cache-dependency-path: /dev/null

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Verify baseline structure
        run: python scripts/verify_openspec_baseline.py

      - name: Validate OpenSpec strictly
        shell: pwsh
        run: ./scripts/openspec-validate.ps1
```

If `setup-node` rejects `/dev/null` as a cache dependency path, remove the `cache` and `cache-dependency-path` keys entirely; this repository has no Node lockfile and OpenSpec is intentionally a one-off pinned CI tool.

- [ ] **Step 2: Verify workflow YAML locally**

Use Python to parse the workflow with PyYAML if available, or inspect through GitHub after commit. Also verify that the existing `windows-ci.yml`, `release-2.0.1.yml`, and `secret-scan.yml` are not modified.

- [ ] **Step 3: Commit Task 4**

```bash
git add .github/workflows/openspec.yml
git commit -m "ci: validate OpenSpec baseline"
```

- [ ] **Step 4: Verify GitHub Actions result on the branch**

After push/commit, inspect the workflow run for the branch commit. Expected OpenSpec job status: `success`.

Do not merge solely because OpenSpec is green; existing Windows/security/manual release gates remain separate requirements.

---

### Task 5: Final repository verification and adoption PR

**Files:**
- Modify only if verification finds documentation defects: files created in Tasks 1-4.
- Do not modify: `src/**`, `tests/**`, `Cargo.toml`, `Cargo.lock`, `build.rs`, runtime assets.

**Interfaces:**
- Consumes: completed adoption branch.
- Produces: reviewable PR that introduces process/specification infrastructure only.

- [ ] **Step 1: Run the complete OpenSpec verification set**

```powershell
python scripts/verify_openspec_baseline.py
pwsh -File scripts/openspec-validate.ps1
$env:OPENSPEC_TELEMETRY='0'
npx --yes @fission-ai/openspec@1.13.0 list --specs
```

Expected: baseline guard passes, strict validation passes, and nine capability specs are listed.

- [ ] **Step 2: Confirm runtime source identity against the 2.0.1 baseline**

Run:

```bash
git diff --exit-code 6aaa3146cf9b077f708c65d7cefe70d064badff5 -- src tests Cargo.toml Cargo.lock build.rs assets
```

Expected: exit code 0 and no diff.

- [ ] **Step 3: Review branch diff for scope**

Allowed top-level additions/modifications:

```text
.agents/
.github/workflows/openspec.yml
docs/OPENSPEC_TRACEABILITY.md
docs/superpowers/
openspec/
scripts/openspec-validate.ps1
scripts/openspec-refresh-skills.ps1
scripts/verify_openspec_baseline.py
```

Any unrelated file change blocks completion.

- [ ] **Step 4: Inspect existing CI status**

OpenSpec adoption must not disable or edit the existing Windows Rust CI, release workflow, or secret scan. Record any workflow failures separately; do not reinterpret them as OpenSpec failures.

- [ ] **Step 5: Open a draft PR to `main`**

Title:

```text
Adopt OpenSpec spec-driven development workflow
```

PR body MUST state:

```text
- Process/specification change only; no G-switcher runtime behavior is intentionally changed.
- Baseline derived from release/2.0.1 commit 6aaa3146cf9b077f708c65d7cefe70d064badff5.
- Adds nine living capability specs, G-switcher-specific OpenSpec rules, Codex workflows including verify, traceability guard, and independent strict CI validation.
- Existing Windows/security/provenance/Defender/manual compatibility gates remain intact and are not replaced by OpenSpec.
- Do not merge into the frozen 2.0.1 release candidate. Reconcile with main after PR #28 is resolved.
```

- [ ] **Step 6: Final completion evidence**

Before claiming completion, record:

```text
OpenSpec CLI version: 1.13.0
Baseline guard: PASS
openspec validate --all --strict: PASS
Runtime diff vs 6aaa3146...: empty
OpenSpec GitHub Actions: PASS
Existing release candidate PR #28: unchanged
```

If any line cannot be supported by actual command/tool output, report it as incomplete rather than claiming success.
