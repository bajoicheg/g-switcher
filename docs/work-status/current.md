---
schema: development-work-status/v4
repository: bajoicheg/g-switcher
branch: release/2.0.1
policy_revision: 2026-10-06-cdc-2.11.6-switcher
policy_digest: beace8a697dc3649f76f760cbf1e5ffba3358a8ae70e009471a3092c9c29c3e2
observed_at_utc: '2026-10-06T14:12:14.840106Z'
orchestration_origin: chat
active_executor: none
lease_state: released
executor_heartbeat_at_utc: null
execution_lease_until_utc: null
waiting_external_kind: null
waiting_external_id: null
waiting_external_sha: null
operation_intent_ref: null
operation_key: null
control:
  execution_lease_ref: refs/heads/cdc/coordination
  execution_lease_revision: null
  executor_id: null
  lease_generation: 12
  budget_ref: https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/budget-ledger.json
  recovery_snapshot_ref: null
  external_wait_ref: null
active_change: G-switcher 2.0.1 compatibility acceptance
current_task: Complete real Windows acceptance after CDC 2.11.6 adoption
phase: blocked
implementation_sha: 0b6f7e3cff9762f9508c8e42d1fd23298a496306
candidate_sha: ''
last_green_sha: 0b6f7e3cff9762f9508c8e42d1fd23298a496306
last_green_evidence: https://github.com/bajoicheg/g-switcher/actions/runs/36259598328
active_compute: ''
active_ci_run_id: ''
last_ci_run_id: '36259598328'
last_ci_status: 'completed/success: Windows Rust CI #410; historical runtime-equivalent
  evidence'
release_version: 2.0.1
release_candidate_sha: ''
release_state: blocked
blocker: 'Real Windows compatibility acceptance remains incomplete: ordinary Edge/Chrome
  Auto/Manual/Undo/Focus/Pause, desktop Word and remaining protected-input checks.'
next_action: Complete fresh exact-candidate Windows CI, then Run the exact candidate
  g-switcher-compatibility.exe kit on real Windows following MANUAL_TESTING_2.0.1.md
  and BROWSER_QUICK_TEST_2.0.1_RU.md; complete COMPATIBILITY_2.0.1.md, then obtain
  final review and explicit public-promotion approval.
resume_capsule_ref: https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/resume.json
execution_continuity:
  invocation_id: null
  runnable_next_action: true
  meaningful_progress: true
  primitive_steps_since_progress: 0
  completion_gate: continue
  last_progress_ref: docs/cdc-adoption-2.11.6.md
---

## CDC 2.11.6 process-only adoption

Canonical release b3b517fb70e2deea4006e265f708f29881377885, exact package tree 79257a06c40de6f514f9b059be05d610885a50e7. Final receipt and exact published HEAD are recorded on coordination. Product acceptance remains blocked as recorded below.

## CDC 2.11.5 process-only adoption — managed atomic publication

        This branch now binds canonical CDC **2.11.5** at `refs/heads/release/v2.11.5`, release commit `bbe5d8c8e4249ad27735245033b6dd6549539809`, package tree `6e9fb338a83c532076a30e8feb0b6ce2ebbe4063`. The migration was assembled detached and is published only after exact package/policy/checkpoint/provenance validation. Product gates and scheduler state are unchanged.

        
        ## Current product boundary — 2026-10-05

        The active change is G-switcher 2.0.1 acceptance, not a historical CDC migration.
        Current main security and storage-hygiene changes have been merged; the two add/add
        security conflicts use the exact current-main versions. Product runtime, tests,
        Cargo dependencies, assets and the Windows gate remain byte-identical to candidate
        0b6f7e3cff9762f9508c8e42d1fd23298a496306 (Windows CI #410, run 36259598328).
        This is historical runtime-equivalent evidence, not GREEN for this new root commit.

        The authoritative exact candidate SHA and fresh CI result are stored in the
        resume capsule on cdc/coordination. Candidate SHA fields here are intentionally
        empty because this document is part of the candidate commit itself.

        Fresh Windows CI follows atomic publication in the same managed-maintenance
        workflow; final coordination recording replaces the pending result only after
        that exact job is terminal. No public release or compatibility PASS is implied.

        Remaining manual checks: ordinary Edge and Chrome Auto/Manual/Undo/Focus/Pause;
        desktop Word; protected-input cases and valid application versions in the existing
        matrix. Automated forced-accessibility browser adapter tests do not complete them.
        PR #28 stays Draft. Final review and explicit public-promotion approval remain required.

        Earlier CDC adoption sections below are historical evidence only.
        ## CDC 2.11.3 process-only adoption — managed atomic publication

This branch now binds canonical CDC **2.11.3** at `refs/heads/release/v2.11.3`, release commit `ed8256d1b80cc3f5424890e5488d5fbbcb57a304`, package tree `39f733127ac130de4f647cf9e5ec55afcca0769c`. The migration was assembled detached and is published only after exact package/policy/checkpoint/provenance validation. Product gates and scheduler state are unchanged.


## CDC 2.11.1 adoption

CDC 2.11.1 process-only adoption under owner-attested recovery. The previous owner is quiescent by current user confirmation and fresh provider reconciliation. This checkpoint records the adoption invocation at integration; final adoption evidence and actual ownership release are authoritative on cdc/coordination. Product source, prior platform evidence, release gates, budget history and scheduler pause are preserved.

# Current work status

## CDC 2.7.2 adoption — 2026-09-25

The active draft release line now vendors immutable canonical CDC 2.7.2 from
`bajoicheg/g-cdc`, release ref `refs/heads/release/v2.7.2`, release commit
`9f68f150a46dcd2de6933d0469ab12a07dc1fd74`, exact package tree
`6e22d252374634662c95488ba9e7245febf6771a`.

CDC Policy Validation run `36167255217` is GREEN: exact package identity, package
validator, adapter, consumer lock, checkpoint schema and cost-router regression 10/10.
The semantic project policy digest is
`a9014b236af2c9222a7920c61cec0fd5d191dfdd31277c98280fa217f9b23a40`.

Because `bajoicheg/g-switcher` is public, project cost policy does not apply the
private-repository GitHub Actions cost penalty. Windows Rust CI is a normal/free
platform backend; Codex remains optional compatible compute rather than a cost-driven
replacement.

Windows Rust CI run `36167254969` is GREEN on the same adoption head, including
format, locked dependency graph, Clippy, unit tests, same/cross-process Windows E2E,
browser UIA E2E, hung/closing-target failure paths, release build, branding checks,
Defender scan, exact clean-source verification, packaging and artifact upload.
Repository Security pull-request and push checks also passed.

CDC adoption changes process/control files only; no runtime product behavior is changed.
The pre-existing manual real-application compatibility matrix and explicit final release
review remain authoritative release blockers.


## CDC 2.7.3 convergence — 2026-09-25

The active draft release line now vendors immutable canonical CDC 2.7.3 from
`bajoicheg/g-cdc`, release ref `refs/heads/release/v2.7.3`, release commit
`88ee8a209caf562c02fe2ad53e047d7feee0e007`, exact package tree
`806a66cd973954b3d5348ac36d39631717d9fe7b`.

CDC 2.7.3 adds two project-relevant contracts:
- a bare continuation command such as «продолжай»/«продолжи»/“continue” means continue
  the already-authorized current scope until terminal state, without expanding authority;
- repository visibility participates in compute cost routing. This repository is public,
  so standard GitHub-hosted Actions are treated as unmetered/normal by project policy,
  while private/internal repositories may retain the Codex-first cost preference.

The semantic adapter digest from CDC Policy Validation run `36178146073` is
`327dd55cda2223519ce50c0412957bd31f8ed4dc9d9358cc2d36d324b413fff2`.
That run proved exact 2.7.3 package identity, package validation, adapter validity and
consumer-lock validity; its only RED was the deliberately stale checkpoint revision that
this commit reconciles.

Product runtime behavior is unchanged. The manual real-application compatibility matrix
and explicit final release review remain the authoritative release gates.


## CDC 2.7.3 convergence terminal state

CDC convergence is COMPLETE for this repository:
- canonical release: `refs/heads/release/v2.7.3`;
- release commit: `88ee8a209caf562c02fe2ad53e047d7feee0e007`;
- exact vendored package tree: `806a66cd973954b3d5348ac36d39631717d9fe7b`;
- policy revision: `2026-09-25-cdc-2.7.3-g-switcher-visibility-ts`;
- semantic digest: `327dd55cda2223519ce50c0412957bd31f8ed4dc9d9358cc2d36d324b413fff2`;
- CDC Policy Validation `36178305436`: GREEN on exact checkpoint head
  `29765d01d8619f0d7af6ba2985ba614290b0b8b5`;
- execution-lease/v2 generation 3 finalized transactionally and released with null guard.

Public-repository compute economics are explicit: standard GitHub-hosted Actions are
unmetered/normal by project policy, so the private-repository Actions penalty does not
apply. CDC 2.7.3 also makes bare «продолжай»/«продолжи»/“continue” mean continue the
already-authorized current scope to terminal state.

The product release is deliberately NOT declared GREEN by CDC convergence. Windows Rust
CI run `36178305452` reached and passed provenance, privacy, fmt, locked graph, Clippy,
unit tests, compatibility tooling, same-process E2E and cross-process E2E. On both
bounded attempts Edge passed, while Chrome executable discovery succeeded but the
Chrome test window did not appear within 20 seconds. This repeated environment/browser
startup signature remains separate from CDC convergence. The manual compatibility
matrix and explicit final release review remain mandatory, and a fresh exact-head
Windows GREEN is still required before publication.

## G-switcher 2.0.1 Chrome launch hardening terminal handoff — 2026-09-25

The repeated hosted-Windows Chrome startup blocker is resolved.

Evidence and RCA:
- the unchanged browser adapter source previously passed Edge and Chrome on
  `c492f0d208e08e8e0d84244147dbf82bb4ae8499` in Windows Rust CI
  `36167861242`;
- after CDC/status-only changes, Windows Rust CI `36178305452` twice reached the
  browser gate, passed Edge, discovered Chrome, and then failed because the Chrome
  test window did not appear within the former 20-second startup allowance;
- no product/runtime change existed between those two signatures, isolating the
  failure to the hosted-CI Chromium launch harness.

Corrective commit `cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b` changes only
`tests/browser_uia_adapter.rs`: hosted CI now opens a normal isolated Chromium
`--new-window`, disables background mode, and uses a bounded 45-second top-level
window allowance inside the existing 240-second browser gate. Product runtime and
release behavior are unchanged.

Exact-head evidence on that commit:
- Windows Rust CI #408 / `36186903615`: GREEN end to end;
- Edge browser UIA adapter E2E: PASS;
- Chrome browser UIA adapter E2E: PASS, including input/textarea mutation,
  selection, Undo, RuntimeId separation and password guard;
- hung/closing-target E2E, release build, branding checks, Defender scan,
  clean-source verification, packaging and artifact uploads: PASS;
- callback stress: `100000` callbacks, `0` over 10 ms, `0` dropped,
  max `217400 ns`;
- CDC Policy Validation `36186903679`: GREEN;
- Repository Security `36186903573`: GREEN.

Artifacts:
- Windows x64: `10887246344`,
  `sha256:07e8f4da9274db6cbb56a6a71717c11ffdf8cb563967b0bb112c197fcf7cb44f`;
- manual compatibility kit: `10887351168`,
  `sha256:f49dc545ed9f17fafd87c9bc7fa6ba40a213a540c3cad8780b4dfbce665ee4db`;
- lockfile: `10887425946`,
  `sha256:82da81aa5f19921ed9f835b16e3c5ccdf278e5e82ff40d13e6e9a1e1b8c046f2`.

PR #28 remains Draft. This invocation cannot legitimately complete the remaining
real-application matrix without the required Windows/manual observations. The next
terminal dependency is therefore manual compatibility evidence, followed by explicit
final review and the policy-required fresh exact-head Windows GREEN before public
promotion.


## CDC 2.8.2 adoption — 2026-09-26

Process-only CDC convergence updated the active release line to canonical CDC 2.8.2.
Vendored package tree is `bdf18b8dedb2f0cf62728935d92e6260b4a64ef0`; adoption validation run
`36234988149` passed package validation (177 files/templates), adapter validation,
and consumer-lock validation. Product runtime code and the existing manual compatibility
release blocker are unchanged.


## CDC 2.9.2 adoption — 2026-09-26

Transactional process-only migration from canonical CDC 2.8.2 to released CDC 2.9.2.
Canonical identity: `refs/heads/release/v2.9.2`, release commit
`0dd30a888be852d2820f690be04dbd374d732c06`, exact package tree
`f9087eacbffee774c143eabf854c2cf08d610ec7`. The detached package transfer matched that exact tree before the
product ref move. G-switcher runtime behavior and the existing 2.0.1 manual
compatibility/final-review release gates remain unchanged. Exact-head validation follows.

