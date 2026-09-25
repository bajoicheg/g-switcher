---
schema: development-work-status/v3
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
current_task: ""
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
blocker: none
next_action: "Reconcile repository identity, remote HEAD, active work and validation state."
---

# Current work status

Durable operational handoff only. On every resume, independently refetch repository identity, HEAD, PR, CI/compute, active tasks, and release state before trusting this checkpoint.
