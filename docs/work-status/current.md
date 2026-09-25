---
schema: development-work-status/v4
repository: bajoicheg/g-switcher
branch: release/2.0.1
policy_revision: "2026-09-25-cdc-2.7.2-g-switcher-adoption"
policy_digest: null
observed_at_utc: "2026-09-25T17:14:00Z"
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
  lease_generation: null
  budget_ref: https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/budget-ledger.json
  recovery_snapshot_ref: null
  external_wait_ref: null
active_change: ""
current_task: "Adopt canonical CDC 2.7.2 on active 2.0.1 release line"
phase: recovery
implementation_sha: "b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576"
candidate_sha: "b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576"
last_green_sha: "b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576"
last_green_evidence: ""
active_compute: ""
active_ci_run_id: ""
last_ci_run_id: ""
last_ci_status: ""
release_version: "2.0.1"
release_candidate_sha: "b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576"
release_state: "candidate"
blocker: "CDC policy digest and package validation pending"
next_action: "Validate exact CDC subtree, adapter, consumer lock and checkpoint; then bind policy digest and release adoption lease."
resume_capsule_ref: "https://github.com/bajoicheg/g-switcher/blob/cdc/coordination/resume.json"
execution_continuity:
  invocation_id: null
  runnable_next_action: false
  meaningful_progress: true
  primitive_steps_since_progress: 0
  completion_gate: resumable_blocker
  last_progress_ref: "git:b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576"
---

# Current work status

G-switcher 2.0.1 remains the active product/release line. CDC 2.7.2 adoption is process-only and must not alter product behavior or existing release/compatibility gates.
