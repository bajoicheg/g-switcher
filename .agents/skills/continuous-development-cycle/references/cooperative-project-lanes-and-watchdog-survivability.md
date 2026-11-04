# Cooperative project lanes and watchdog survivability

CDC 2.11.2 extends the released managed executor pool and watchdog liveness controls without granting new product-write or scheduler authority.

## Cooperative lane invariants

- Lane mode cannot begin merely because the new registry exists. Call `ProjectLaneCoordinator.establish_migration_gate()` first with independently verified evidence that the legacy project-wide lease is absent/released/quiescent, external guards are none/reconciled, and legacy acquisition is disabled. The proof is immutable and revalidated on every registry read; without it all lane admission fails closed.

Each lane binds executor + invocation + generation + exact source HEAD + surface/role + portable read/write claims + isolated branch/worktree.
- Non-overlapping writers may coexist. Portable case/Unicode/ancestor overlap serializes before effects.
- Read-only/review lanes may coexist with writers on pinned snapshots.
- Exactly one integrator may own the shared-branch integration lane.
- Real worker launch uses `scripts/project_lane_executor.py`: first commit a one-shot start claim in the durable lane registry, re-read the lane, then invoke an explicit backend. Unknown starts retain the pending-effect claim and are observed, never replayed. The caller supplies an authorized worktree root isolated from both the product worktree and durable journal; every claimed worktree must resolve beneath that root. A compatible local backend prepares the isolated Git worktree after admission, not before it.
- Foreground work does not pause the watchdog. A blocked watchdog chooses non-conflicting runnable or observational work.
- Claims are not stolen for urgency. Handoff/recovery requires checkpointed independently verified quiescence; TTL/silence is insufficient.
- Heartbeat requires a new activity reference plus independent observable-activity evidence; caller-generated labels alone are not heartbeat proof.
- Writer acceptance validates base ancestry and every touched path in every introduced commit, including touched-and-restored paths.
- Normal release is executor/invocation/generation-bound, drains pending effects and persists an exact checkpoint reference.
- Computed/accepted work remains nonterminal until required integration is complete.
- Before any shared-ref publication, the integrator persists a one-shot durable integration intent binding the observed shared HEAD and the intended integrated HEAD. Unknown publication outcomes retain that intent for readback/reconciliation rather than creating a new effect grant.
- Release-grade Git publication uses `GitLaneIntegrationPublisher`: the intended head must contain both the observed shared head and the accepted result, the authoritative remote must still equal the observed head, and the update is performed with an exact-head lease plus authoritative readback. The lease is only a CAS primitive; ancestry is checked first so no non-fast-forward rewrite is authorized.
- `GitLaneIntegrationVerifier` is read-only ancestry/readback evidence and explicitly reports `conditional_update=false`; it cannot close the integration queue by itself. Queue removal requires evidence with `conditional_update=true`, exact intended head, the original operation ID and no force rewrite.

## Watchdog survivability invariants

The durable desired-state record, not a scheduler object ID, defines whether a watchdog must exist. The runtime inventory may classify the materialization as HEALTHY, OVERDUE, DISABLED_DRIFT, MISSING, CONFIG_DRIFT, DUPLICATE, FLAPPING or EXECUTION_BROKEN. Intentional owner pause and exact terminal proof are separate non-recovery states.

A recovery effect is legal only when desired state requires an enabled watchdog, no fresh owner pause supersedes it, project state is freshly runnable, owner/guard are released, external work is absent or reconciled, scheduler pause state permits recovery, and the durable recovery policy contains explicit owner authorization.

Missing/configuration-drift/flapping recreation advances desired generation before scheduler I/O only after the current materialization is non-running. An active materialization is never destructively replaced for configuration drift or flapping; it is observed until quiescent. A disabled schedule may be enabled while its invocation is running because that does not create a second run. Any old generation is fenced by `execution_is_current` once replacement is legal. Lost/unknown provider outcomes retain their durable operation claim and require inventory reconciliation rather than replay.

Duplicate materializations are disabled only after the canonical object is known, and at most one duplicate scheduler effect is consumed per project reconciliation step. A post-claim owner stop is re-read before I/O and blocks the effect. A currently running watchdog is never kicked a second time merely because its last-run timestamp is old. Unknown run replies reconcile only from a run timestamp observed at or after the durable operation claim.

Fleet recovery may compose `WatchdogSurvivabilityRuntime` with `FleetRuntime`. Every registered desired watchdog is assessed, while scheduler mutations share a bounded fleet effect budget; exhausted repairs remain continuation work. An unresolved scheduler effect prevents desired-generation replacement, so missing/lost replies cannot be erased by configuration churn.

A scheduler backend must be genuinely available and authorized; CDC cannot manufacture one.

## Fleet Supervisor sentinel

The Fleet Supervisor is itself replaceable. An independent host scheduler may run `scripts/watchdog_sentinel.py` against a desired-state entry whose role is exactly `fleet-supervisor`. The sentinel is intentionally not a second Fleet controller: it reconciles only the Fleet Supervisor materialization through the same generation-fenced survivability runtime, requests continuation after recreate/adopt/enable until a real wake is requested, and carries no product-write authority. Run it from an execution plane independent of the Fleet Supervisor when the platform provides one. Multi-backend HA for the sentinel itself is outside 2.11.2.

## Terminal aggregation

Project completion is project-wide. Runnable or active lanes, unknown/pending effects, queued runnable work and unintegrated required results all keep the project nonterminal. Watchdog survivability state contributes evidence but never replaces execution-continuity/finalizer evidence.

## Current rollout constraint

Owner-paused schedulers remain paused. Implementing survivability does not itself authorize enabling, recreating or running them.
