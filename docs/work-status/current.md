---
schema: development-work-status/v4
repository: bajoicheg/g-switcher
branch: release/2.0.1
policy_revision: "2026-09-26-cdc-2.8.2-fleet-adoption"
policy_digest: 8d859aa6a920496a01921aa009eacf49f822df72dcd082248bd135973f9e9527
observed_at_utc: "2026-09-26T10:10:39Z"
orchestration_origin: chat
active_executor: none
lease_state: released
executor_heartbeat_at_utc: null
execution_lease_until_utc: null
waiting_external_kind: manual_compatibility
waiting_external_id: "COMPATIBILITY_2.0.1.md"
waiting_external_sha: cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b
operation_intent_ref: null
operation_key: null
control:
  execution_lease_ref: refs/heads/cdc/coordination
  execution_lease_revision: null
  executor_id: null
  lease_generation: 4
  budget_ref: https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/budget-ledger.json
  recovery_snapshot_ref: null
  external_wait_ref: null
active_change: "2.0.1 release acceptance"
current_task: "Automated Chrome startup blocker resolved; manual real-application acceptance remains"
phase: blocked
implementation_sha: cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b
candidate_sha: cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b
last_green_sha: cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b
last_green_evidence: https://github.com/bajoicheg/g-switcher/actions/runs/36186903615
active_compute: ""
active_ci_run_id: ""
last_ci_run_id: "36186903615"
last_ci_status: "completed/success: Windows Rust CI #408 exact-head GREEN including Edge and Chrome UIA E2E"
release_version: "2.0.1"
release_candidate_sha: cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b
release_state: "candidate"
blocker: "Automated release-gate blocker is resolved. Public promotion remains blocked by completion of the manual COMPATIBILITY_2.0.1.md real-application matrix and explicit final release review; after subsequent release-evidence/checkpoint changes, obtain the required fresh exact-head Windows GREEN before publication."
next_action: "Run the manual compatibility matrix using Windows CI #408 manual kit artifact 10887351168, persist exact application/version results, perform explicit final review, then obtain the required fresh exact-head Windows Rust CI GREEN before merge/public release."
resume_capsule_ref: "https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/resume.json"
execution_continuity:
  invocation_id: "chat-2026-09-25T203600Z-g-switcher-product-continuation"
  runnable_next_action: false
  meaningful_progress: true
  primitive_steps_since_progress: 0
  completion_gate: resumable_blocker
  last_progress_ref: "git:cbe09e4eec2547d24826d1b7ecb0e2e9800f7d3b;actions:36186903615:green;pr28-comment:5839327813"
---


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
