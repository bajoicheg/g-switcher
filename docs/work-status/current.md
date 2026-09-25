---
schema: development-work-status/v4
repository: bajoicheg/g-switcher
branch: release/2.0.1
policy_revision: "2026-09-25-cdc-2.7.2-g-switcher-adoption"
policy_digest: a9014b236af2c9222a7920c61cec0fd5d191dfdd31277c98280fa217f9b23a40
observed_at_utc: "2026-09-25T17:32:30Z"
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
  lease_generation: 1
  budget_ref: https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/budget-ledger.json
  recovery_snapshot_ref: null
  external_wait_ref: null
active_change: ""
current_task: "G-switcher 2.0.1 release line; canonical CDC 2.7.2 adopted"
phase: blocked
implementation_sha: 36424c5109f1e94ff392068c0a58b0acb7bfc10d
candidate_sha: 36424c5109f1e94ff392068c0a58b0acb7bfc10d
last_green_sha: 36424c5109f1e94ff392068c0a58b0acb7bfc10d
last_green_evidence: https://github.com/bajoicheg/g-switcher/actions/runs/36167254969
active_compute: ""
active_ci_run_id: ""
last_ci_run_id: "36167254969"
last_ci_status: "completed/success"
release_version: "2.0.1"
release_candidate_sha: 36424c5109f1e94ff392068c0a58b0acb7bfc10d
release_state: "candidate"
blocker: "Manual COMPATIBILITY_2.0.1.md real-application matrix and explicit final release review remain required"
next_action: "Complete the manual compatibility matrix on the intended applications, then perform the explicit final release review. CDC itself is converged and has no blocker."
resume_capsule_ref: "https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/resume.json"
execution_continuity:
  invocation_id: null
  runnable_next_action: false
  meaningful_progress: true
  primitive_steps_since_progress: 0
  completion_gate: resumable_blocker
  last_progress_ref: "actions:36167254969:success"
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
