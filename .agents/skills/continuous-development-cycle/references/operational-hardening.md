# CDC 2.8.1 operational hardening

CDC 2.8.1 turns recovery hygiene and decision boundaries into explicit machine-readable controls.

## Watchdog self-repair

Use `scripts/watchdog_self_repair.py` when watchdog delivery is disabled, missing, overdue, bound to an archived/missing chat, or its execution backend is unavailable. The planner prefers recovery within existing authorization: rebind a dead chat dependency, restore/read back the scheduler, or use an already configured fallback. It never grants scheduler/chat mutation or external-start authority. Bounded repair exhaustion becomes a proven blocker.

## Ref and coordination hygiene

Use `scripts/ref_hygiene.py` to identify terminal, unreferenced, expired temporary refs. Main/release/protected refs, open PRs, unreconciled guards, active or durably referenced refs are retained. The output is a deletion plan only.

Use `scripts/coordination_retention.py` to archive/delete stale terminal coordination records under policy. Audit and ledger records may be never-delete classes. Active references, guards and nonterminal records are always protected. Archive/delete candidates never grant mutation authority.

## Blocker proof

Use `scripts/blocker_proof.py` before treating BLOCKED as a terminal boundary. A blocker requires a concrete dependency ID, category, fresh observation, evidence, exact next action, recheck trigger and proof that same-invocation useful work is exhausted. Stale or evidence-free blockers are not terminal state.

## Decision authority

Use `scripts/decision_authority.py` before escalating routine engineering decisions. Reversible/compensatable low-or-medium-risk actions already inside scope and explicitly pre-authorized may be executed without asking the owner again. Scope expansion, destructive or irreversible actions, protected gates, missing secrets, high-risk choices, or absent prior authority require human involvement or remain blocked. The classifier recognizes authority; it never creates it.

## Evidence compaction

Use `scripts/evidence_compactor.py` to project verbose execution events into a deterministic canonical record: result counts, terminal count, unique durable refs and a source digest. Raw diagnostics can remain in the private evidence store while product-facing state carries only the compact projection. Compaction must not erase the source digest or evidence refs.

## Progress enforcement

Use `scripts/progress_enforcer.py` after progress-SLO classification. Runnable work means continue now. STALLED becomes watchdog kick/repair, RECOVERY_REQUIRED becomes recovery, and DEGRADED becomes inspect-and-continue. A proven blocker or durable external wait is the only P1 path here that permits a terminal response.
