# Taskless submission recovery

The original taskless claim remains an audit/idempotency record. This recovery only resolves a released generation whose exact original operation was positively rejected before acceptance, or cancelled before any dispatch. It never submits or rearms an old attempt.

## Evidence and trust

The parent/integrator authenticates all observations through its authorized provider/runtime interfaces, persists the raw responses and cancellation/dispatch journal, reads them back from the trusted immutable coordination store, then assembles taskless-submission-proof/v1. This is a trusted orchestration API, not an untrusted JSON-to-CAS service. Pure validators cannot authenticate a URL, a Git ref, a Boolean, or their caller; references and caller assertions alone are not evidence. A missing historical dispatch barrier is an unresolved blocker, not permission to reconstruct one.

The proof binds the exact current lease revision and canonical digest, repository/source, original grant/attempt/owner/generation/intent, explicit original release invocation, a fresh complete provider lookup with no task, independently stopped/quiescent worker and parent dispatcher, and immutable positive dispatch outcome. Every fresh observation is at most 300 seconds old, no later than recovery time, and after the original release. Dispatch outcome follows the claim and precedes release. The 403 path is restricted to the supported GitHub create-PR/merge endpoint and exact candidate; network errors, missing replies, 5xx, or an accepted/taskful/unknown intent stay guarded. The not-submitted path requires a committed cancel-before-send barrier and no in-flight dispatcher.

## Transition

Use resolve_released_guard(record, proof, evidence_reference, at) to validate a preview. For actual mutation use reconcile_submission_cas(store, expected_revision, proof, evidence_reference, at), where store is the authorized GitLeaseStore. The store independently reconstructs the canonical three-field transition and binds the proof to its actual expected revision. Only external_guard, last_terminal and submission_resolutions change. Claims, generation, ownership, release identity, budgets and all unrelated state remain unchanged. Ordinary released-v2 rewrites are rejected.

Persist/read back the authenticated proof before CAS, and retain it after recovery. A lost CAS reply is observed from the authoritative ref and original resolution; never issue another provider call or rebuild the grant. A new operation requires fresh managed ownership and a distinct one-shot attempt. Existing operation_intent.decide(tasks=[]) deliberately continues to return reconcile.

## Validation

The behavioral suite tests positive rejection/cancellation, missing barrier, incomplete/stale/future lookup, unknown/lost/accepted results, wrong target/claim/runtime identity, Boolean generations, immutable release identity, replaced guard, unrelated mutation, real Git two-contender CAS, and lost successful CAS reply. It is separate from independent bootstrap, full package and archived-consumer compatibility evidence. Archived snapshots do not deploy a consumer.
