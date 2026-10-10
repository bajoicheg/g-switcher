# CDC 2.9.1 — Transactional Migration & Provider Reconciliation

## Fresh-HEAD idempotent policy migration
Policy migration is section-aware and idempotent. Immediately before mutation, compare the expected source HEAD with the freshly observed source HEAD. A mismatch returns REPLAN_ON_FRESH_HEAD and no rendered candidate. Strict YAML rejects duplicate top-level keys; managed sections are replaced by key rather than appended, unmanaged sections are preserved semantically, and replaying the same desired sections converges to NOOP.

## Schema-typed checkpoints
Checkpoint migration is schema-typed by construction. Human-readable next-action text never supplies Boolean or enumerated control fields. The builder accepts explicitly typed execution-continuity fields and runs the real checkpoint v4 validator as a pre-commit gate before returning a candidate checkpoint. Invalid type or state combinations are rejected rather than weakened.

## Bounded Git-object transactions
Large migrations are planned against an explicit operation budget. Each batch reserves finalization operations, writes only a detached tree checkpoint, and can resume from completed paths. Product/adoption refs cannot move while a batch is partial. Even after all objects are copied, the planner requires exact subtree identity and fresh policy reconciliation before declaring ref-move prerequisites satisfied; it never grants ref-move authority itself.

## Terminal-provider reconciliation
A guarded provider operation that becomes terminal triggers immediate reconciliation/re-entry for the exact operation key. The durable guard must be reconciled instead of staying indefinitely running. Provider terminal state or TTL alone never grants takeover. Recovery can become a takeover candidate only after explicit executor-stopped evidence, no pending shared writes, and reconciled/absent external effects; normal ownership authority is still required.
