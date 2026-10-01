# Connect ownership, recovery and budget controls

Use this runbook at resume, before a shared mutation, or before an external launch. Individual successful CLI exit codes do not authorize the next side effect. Obtain authentic remote observations/readbacks through authorized tools; the local helpers validate supplied data and cannot authenticate a provider response.

## One sequence, independent gates

1. **Policy and identity.** Validate current adapter/checkpoint; verify canonical repository, source ref/HEAD and applicable user/repository instructions. Read `VERSION` fresh. Configure `orchestration` within the existing authorized task, preserving old restrictions and in-flight bindings.
2. **Compact recovery.** Retrieve the checkpoint's recovery snapshot and a complete fresh probe. `recovery.py recover` selects a read set; it grants no write permission. Unchanged source HEAD is insufficient if owner/generation, policy, tasks, external operations, PR/CI/release state or skill version changed. Read actual current instructions even on the fast path.
3. **Ownership.** For Git mode, read the configured independent coordination ref and conditionally acquire/renew ownership. Verify canonical repository/source-ref binding, unique executor UUID, generation and expected store revision. For single-writer mode, verify the authenticated assignment applies to exactly this invocation; missing/stale assignment is observer-only. Match checkpoint `control` pointers to actual records, not the reverse.
4. **External guard.** Inspect every pending intent and actual provider task. Unknown/active work blocks competing writes or starts even after lease expiry. Use wait supervision to decide observe/diagnose/reconcile. An exceeded queue/setup/run threshold never clears the guard. Do not fabricate original keys for legacy requests; preserve their actual metadata and reconcile them to terminal before migration.
5. **Budget.** Retrieve the durable task ledger. Begin a new wake without resetting task usage or active agents. Check and reserve the exact operation key/attempt/kind and costs before launching. `allow_reservation: true` is only a budget decision; `already_recorded` is not a second launch permit. Persist/read back the ledger through the same single-writer discipline before taking the side effect. Remaining quota observations must be fresh and sourced; unknown values remain unknown.
6. **Final boundary.** Refetch ownership/revision and source HEAD immediately before mutation. For external starts, persist/read back the submitting intent and arm its exact guard. In Git mode, consume the one-use CAS submission claim and submit once with its fresh returned grant. In single-writer mode, only the initial in-memory submitting transition in this verified designated invocation may cross the boundary once after durable readback. A restored submitting/unknown record or lost claim/submit reply only permits reconciliation; never reconstruct a permit. Backend-native idempotency/fencing adds protection where supported. Record the actual result and preserve the guard until verified terminal evidence.

Budget reserves, lease changes, guards and intent writes must all be durable before the effect. They need not be a distributed multi-store transaction: partial failure leaves conservative reservations/guards, stops the launch and is reconciled on resume. Never remove one guard just to complete another step. The orchestrator remains responsible for authorization and immediate rechecks; these helpers do not promise distributed exactly-once execution.

## Choose the next action

| Current facts | Next action |
|---|---|
| Policy/version/identity drift or incomplete fresh probe | Reconcile before implementation; observe known work |
| Fresh matching snapshot | Read current instructions and phase-relevant references; retain all other gates |
| Different live owner, stale lease revision or unproven old-executor quiescence | Observe/handoff; no competing mutation |
| Unknown submission, task lookup incomplete | Recover existing intent/task; no replacement |
| External phase deadline exceeded | Diagnose provider/task/logs; retain external guard |
| Next poll not due | Wait until the backoff/Retry-After deadline; preserve supervision and do not busy-poll |
| More than four polls, existing task still active | Continue observing at the configured interval; count alone is not a stop or permission boundary |
| Budget reserve would be consumed | Checkpoint/handoff, or use a valid policy-authorized cheaper path |
| Same failure without new concrete correction/recovery | Diagnose/checkpoint; do not retry |
| All applicable gates satisfied | Resume the configured development phase; recheck at the side effect |
| Terminal task reports success | Validate exact command evidence and required platform/release gates |

## Durable locations and migration

Checkpoint v3 optionally adds `control`: `execution_lease_ref`, `execution_lease_revision`, `executor_id`, `lease_generation`, `budget_ref`, `recovery_snapshot_ref`, `external_wait_ref`. Null means unresolved, not passed. A ref is an exact independently retrievable durable location; local/staged files do not satisfy it. Archive normal files after the external task terminates if saving them would otherwise move its source HEAD.

Keep the coordination ref separate from the product ref. `git_lease_store.py` rejects collisions at execution; adapter syntax validation alone cannot know the active product ref. Do not delete/recreate/reset the coordination ref to clear contention or reset generations. Protect it with repository access policy. Require authentic quiescence evidence before takeover when the previous owner has not explicitly released, including pending provider requests and writes.

Existing adapter/checkpoint v3 and operation-intent/v1 records remain readable. Add `orchestration` only with `policy.skill_min_version: "2.3.0"` and the legacy timer-only takeover flag set to false; increment project policy revision and reconcile the checkpoint digest. A v2.2 adapter without controls is a migration/recovery input, not authority to continue timestamp-based multi-writer election. Preserve old authorization, budgets and active jobs. Unknown historical usage cannot become zero when a ledger is initialized: reconcile known attempts or use explicit conservative limits and record the unknown portion.

Default template caps are starting values, not discovered service quotas. Adjust them through the project's authorized policy process; never silently raise them after denial. `orchestration.budget.actions_budget` must equal `ci.actions_budget`. New ledger/task/wake IDs do not restore an exhausted provider quota, erase failures or release active agents.
