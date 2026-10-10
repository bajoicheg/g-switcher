---
schema: development-work-status/v4
repository: owner/repository
branch: ""
policy_revision: "1"
policy_digest: null
observed_at_utc: ""
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
  execution_lease_ref: null
  execution_lease_revision: null
  executor_id: null
  lease_generation: null
  budget_ref: null
  recovery_snapshot_ref: null
  external_wait_ref: null
active_change: ""
current_task: "reconcile live state"
phase: recovery
implementation_sha: ""
candidate_sha: ""
last_green_sha: ""
last_green_evidence: ""
active_compute: ""
active_ci_run_id: ""
last_ci_run_id: ""
last_ci_status: ""
release_version: ""
release_candidate_sha: ""
release_state: "not-started"
blocker: "initial recovery"
next_action: "Reconcile live repository and coordination state."
resume_capsule_ref: "coordination:resume.json"
execution_continuity:
  invocation_id: null
  runnable_next_action: false
  meaningful_progress: false
  primitive_steps_since_progress: 0
  completion_gate: resumable_blocker
  last_progress_ref: null
---

# Current work status

CDC 2.4 durable operational handoff. Reconcile live repository, coordination, external operations and validation before acting.
