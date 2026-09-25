---
schema: development-work-status/v4
repository: bajoicheg/g-switcher
branch: release/2.0.1
policy_revision: "2026-09-25-cdc-2.7.3-g-switcher-visibility-ts"
policy_digest: 327dd55cda2223519ce50c0412957bd31f8ed4dc9d9358cc2d36d324b413fff2
observed_at_utc: "2026-09-25T19:12:23Z"
orchestration_origin: chat
active_executor: d77ea447-5e63-4f25-91e8-4a36a2c94a91
lease_state: active
executor_heartbeat_at_utc: "2026-09-25T19:12:23Z"
execution_lease_until_utc: "2026-09-25T19:32:23Z"
waiting_external_kind: null
waiting_external_id: null
waiting_external_sha: null
operation_intent_ref: null
operation_key: null
control:
  execution_lease_ref: refs/heads/cdc/coordination
  execution_lease_revision: null
  executor_id: d77ea447-5e63-4f25-91e8-4a36a2c94a91
  lease_generation: 3
  budget_ref: https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/budget-ledger.json
  recovery_snapshot_ref: null
  external_wait_ref: null
active_change: ""
current_task: "G-switcher 2.0.1 release line; canonical CDC 2.7.3 convergence validation"
phase: validation
implementation_sha: 9469a2e3593c6a5141f00d2a0ebaa25e0bee766d
candidate_sha: 9469a2e3593c6a5141f00d2a0ebaa25e0bee766d
last_green_sha: c492f0d208e08e8e0d84244147dbf82bb4ae8499
last_green_evidence: https://github.com/bajoicheg/g-switcher/actions/runs/36167861242
active_compute: ""
active_ci_run_id: ""
last_ci_run_id: "36178146059"
last_ci_status: "in_progress"
release_version: "2.0.1"
release_candidate_sha: 36424c5109f1e94ff392068c0a58b0acb7bfc10d
release_state: "candidate"
blocker: "CDC 2.7.3 exact-head validation in progress; product manual COMPATIBILITY_2.0.1.md matrix and explicit final release review remain required"
next_action: "Complete exact-head CDC 2.7.3 policy/Windows validation, finalize/release generation 3, then resume the manual compatibility matrix and explicit final release review."
resume_capsule_ref: "https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/resume.json"
execution_continuity:
  invocation_id: chat-2026-09-25T190947Z-cdc273-convergence
  runnable_next_action: true
  meaningful_progress: true
  primitive_steps_since_progress: 0
  completion_gate: continue
  last_progress_ref: "git:9469a2e3593c6a5141f00d2a0ebaa25e0bee766d"
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
