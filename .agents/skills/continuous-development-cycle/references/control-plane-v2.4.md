# CDC 2.4 durable control plane

CDC 2.4 makes individual chats, watchdog wakes, models and compute backends disposable while keeping authorization and project state durable.

## Invariants

1. **Invocation-bound lease.** New writers use `execution-lease/v2`: repository/source ref + executor UUID + generation + exact invocation ID. The invocation is part of every mutation/start/release check.
2. **No unsafe migration.** Lease v1 remains readable. An owned v1 record is not converted in place; migrate only after explicit release or verified quiescence with no pending writes and classified external effects.
3. **Transactional finalization.** Finalization progresses `active → draining → checkpointed → reconciled → ready → release`. No product write or new external start is legal after draining begins. A final response while the invocation still owns a lease is a defect.
4. **Hard execution continuity.** `execution-continuity/v1` rejects primitive-only completion while runnable work exists. Primitive status/health/lease/poll/report/heartbeat actions are observable activity, not progress.
5. **Durable resume capsule.** `resume-capsule/v1` carries the minimum handoff needed to recover without a previous chat. Exact fresh agreement is required for fast resume; any repository, HEAD, policy, checkpoint or lease-revision drift forces full reconciliation.
6. **Checkpoint v4.** New 2.4 policy writes use `development-work-status/v4`, including the resume-capsule reference and execution-continuity fields. v3 stays read-compatible during migration.

## Execution FSM

`BOOTSTRAP → RECONCILE → OWNERSHIP → EXECUTE → VALIDATE → CHECKPOINT → CONTINUE`

Terminal/paused branches are explicit: `WAIT_EXTERNAL`, `BLOCKED`, `COMPLETE`. A diagnostic read is never an implicit terminal state.

## Safe adoption

- Install the complete 2.4 package and validate it.
- Raise `policy.skill_min_version` to 2.4.0 and checkpoint schema to v4 at a safe policy checkpoint.
- Preserve existing budget, operation intent, external guard and validation history.
- If coordination is lease v1 and released, migrate it with the v2 migration command. If it is owned, leave it v1 until release/quiescence; do not manufacture invocation identity.
- Write a resume capsule after the next safe checkpoint and bind subsequent v2 ownership to real invocation IDs.

These controls serialize cooperative orchestration; they do not bypass repository protection, provider authorization, CI gates or higher-level instructions.


## Hard finalization coupling

The `ready` lease transition consumes an allowed execution-continuity decision bound to the exact invocation and records its completion reason in the release evidence. A failed finalization can restart from `draining` and repeat checkpoint/reconciliation; failure is recoverable but never silently bypassed. Resume-capsule fast paths bind skill version, policy revision and policy digest in addition to repository/ref/HEAD/checkpoint/lease revision.


## Historical v1 migration anomalies

Released v1 coordination may contain historical records created before strict UUID enforcement. CDC 2.5 migration records an auditable `legacy_migration` marker with the source digest, migration generation and exact digests of any noncanonical historical claims/legacy takeover evidence. Those anomalies remain readable only as pre-migration history; new claims and takeover evidence stay strict v2. An owned v1 record still cannot migrate.
