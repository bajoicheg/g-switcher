# Repository adapter v3

Repository-specific policy belongs in `docs/development-cycle.yaml`, not in the reusable skill.

Recommended top-level sections:

- `schema`
- `policy`
- `repository`
- `planning`
- `checkpoint`
- `validation`
- `compute`
- `operations`
- `ci`
- `execution`
- `progress`
- `watchdog`
- `release`
- `migration`
- `safety`
- `orchestration` (additive in skill 2.3)

The adapter should define real commands and constraints. Missing commands are unavailable capabilities, never implicit success.

Use `scripts/validate_adapter.py` for strict parsing/types, version compatibility and cross-field checks. Its base `SCHEMA` and `validate_orchestration` define the executable contract. Use `references/policy-compatibility.md` for migration, exception provenance and checkpoint binding. The current v3 template requires skill 2.3.0 or later below 3.0.0; a v3 adapter without orchestration retains the 2.2.0 floor. Legacy v1/v2 require reconciliation. Repository restrictions on Work/Codex subagents are valid.

## Runtime policy

The reusable default is:

- ordinary chat: subagents disabled;
- Work: explicitly enabled by default, no additional per-launch approval;
- Codex orchestrator: explicitly enabled by default, no additional per-launch approval;
- unknown: disabled;
- enabled subagents: adaptive effort, never blanket maximum.

A repository may further restrict subagents for sensitive tasks but should not silently broaden ordinary-chat delegation.

For a new project without a stricter applicable restriction, set `additional_subagent_approval_required: false` for Work and Codex orchestration and `delegate_when_useful: true`. These fields govern delegation inside authorized work; they do not override higher-priority restrictions or authorize unrelated external actions.

## Compute policy

For a new project, default to `compute.preference: codex_first`; preserve a sourced approved repository exception as described in `references/policy-compatibility.md`. Keep `codex_backend.enabled: false` while unconfigured; this is an availability flag, not a preference for local execution. With existing authorization, establish the environment using `references/codex-compute.md` and enable it after repository/settings readback.

Record `configuration_status`, `environment_id`, `environment_url`, `linked_github_user`, `channel` and the project `runbook`. Put real commands, expected checks, platform constraints and setup/maintenance details in that runbook. Credentials never belong in the adapter.

Configured Codex is the first choice for eligible candidate checks. `fallback_order` lists correct local runtime, other approved compute and hosted/platform CI; record the reason for fallback and retain Actions/platform gates. `enabled` or a created environment alone is not execution evidence.

On an existing repository, reconcile old generic local-first defaults with the current user instruction at the next safe policy checkpoint. Preserve explicit project exceptions, active external jobs and their source SHA; do not silently modify unrelated repositories.


## Lease policy

Recommended `execution.lease` fields:

- `default_ttl_minutes: 20`;
- `heartbeat_fresh_minutes: 10`;
- `renew_requires_observable_owner_activity: true`;
- `external_wait_state: waiting_external`;
- `external_inflight_is_concurrency_guard: true`;
- `terminal_external_event_renews_owner: false`;
- `terminal_external_takeover_without_fresh_heartbeat: false`;
- `explicit_release_on_handoff: true`.

Long fixed leases are an anti-pattern. A remote job can outlive the lease because the job itself, not an artificially long TTL, guards concurrency while it is actually queued/in-progress.

Expiry and stale heartbeat never authorize takeover without explicit release or verified quiescence. The old true flag remains readable only for v2.2 migration, without new orchestration controls; it is not a current ownership grant.

## Orchestration controls

`orchestration.execution_lease` chooses a named Git remote plus a separate full coordination branch ref, or a verified single-writer UUID and assignment reference. Null single-writer fields mean observer-only. Actual backend validation also rejects source-ref collisions and mismatched fetch/push destinations.

`orchestration.wait` sets separate phase deadlines, observation freshness and initial/capped polling intervals. `recovery.max_snapshot_age_seconds` limits compact reuse. `budget` sets task/wake caps, concurrent-agent cap, checkpoint reserve and provider observation age; its Actions state must equal `ci.actions_budget`. Defaults are local limits, not service quota claims. See `references/orchestration-controls.md` for the required runtime sequence and helper contracts.

## Destructive actions

Destructive actions include force-push, history rewrite, branch deletion with unmerged work, release deletion/replacement, destructive migrations, secret rotation, production data mutation, and security-control disabling. Require explicit confirmation unless repository/user policy has already authorized the specific operation.
