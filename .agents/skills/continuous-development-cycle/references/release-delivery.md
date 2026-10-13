# Exact release delivery and forward rollback

Use this phase after a separately qualified immutable source release. Delivery,
consumer publication, personal installation and executor closure are distinct.
Fleet rollout and scheduler writes still need their own existing authorization;
this API does not launch a fleet or schedule anything.

## Read-only proposal

Run `python3 -B scripts/cdc.py delivery templates/release-delivery.json` or
`python3 -B scripts/release_delivery.py templates/release-delivery.json`.
The example uses fictional exact identities, so its result lists required live
checks and never reports a verified release or publication permission. Strict
JSON rejects duplicate/unknown fields, malformed locks and an unbound downgrade.
All authority flags stay false. Replace configuration with independently trusted
repository, endpoint, source and release/evidence identities before native use.

## Verify the source release

`live_target.verify_release_binding` verifies the configured GitSource endpoint,
stable release version/ref/commit, exact package tree and VERSION, released
canonical evidence and candidate ancestry with an identical package. A v2
binding requires its separately configured evidence endpoint/ref/commit/path,
release ancestry and identical package. Colocated v1 evidence remains supported.
Fresh observations and final live-ref rechecks are mandatory; a moved,
stale/future, duplicate or mismatched object raises ValueError. The Fleet
resolver uses this same verification. It returns no write permission.

## Native managed delivery

An already authorized managed writer constructs `GitReleaseDelivery` with the
consumer Git object cache, configured consumer remote/ref/endpoint identity,
canonical GitSource in that same cache, canonical repository name, authentic
GitLeaseStore, exact current owner/revision/generation/invocation binding and
dedicated GitDocumentStore attempt/assembly refs. Coordination refs must be
isolated from product and lease refs. This API never acquires or releases a
lease. A display label, boolean callback or fabricated observer record cannot
replace stored ownership.

Call `prepare(binding, expected_head=..., transaction_id=...,
operation_budget=...)`. It checks the original authoritative attempt journal
before building any replacement: prepared/submitted/UNKNOWN requires reconciling
that original delivery. It verifies live release and consumer HEAD, current
package/lock agreement and current adapter/checkpoint compatibility with both
installed and target versions. The checkpoint must be v4, released and without
an existing external operation. A policy change requires a separate reviewed
migration; controls, guards, history and budgets are never silently rewritten.

The operation budget must fit the complete five-object detached assembly and
finalization reserve under the existing migration planner. A temporary index
imports the exact released package tree and prepares its lock and append-only
audit while carrying the current adapter/checkpoint objects and modes unchanged.
Every other product path, actual index, worktree and HEAD stay unchanged.
The candidate has exactly one direct parent, the pinned consumer source.
The existing migration assembly record is durably CAS-saved and read back.
Interruption leaves detached objects/history, not a partially updated product.

Call `publish(prepared)` only through that same current managed owner. It verifies
the source release again, actual full candidate, direct parent, required path
objects, unchanged controls, bounded diff and append-only audit. Every real
coordination/product push rechecks authentic invocation-bound ownership; product
publication also rechecks the release. The existing GitConsumerAdoptionPublisher
remains the sole expected-head, non-force publisher with durable prepared →
submitted → confirmed/UNKNOWN/rejected history and exact readback.

A lost response is reconciled against the original candidate. It never creates a
replacement attempt or automatically retries UNKNOWN. Observing the exact
already-published candidate terminal-reconciles its original submitted/UNKNOWN
journal without another product push. An unsubmitted prepared attempt is
aborted if that candidate is independently already present. Keep rejected,
aborted and uncertain history and charges; they are not refundable counters.

## Restore a previous acceptance

Call the same `prepare` with `rollback_from` naming an actual historical consumer
commit. It must be an ancestor of the current live source, distinct from it,
with the exact target lock/package and regular acceptance audit. Independently
verify that target's immutable canonical release/evidence. The new candidate
descends directly from the current consumer source and restores only package and
lock, preserving current validated controls and appending to the older audit.
Incompatible current policy fails for a separately reviewed migration. Ref
reset, force push, old checkpoint replay and an unverified downgrade are forbidden.

The prepared result is data with all authority flags false. A successful
publication proves its exact Git effect, not Fleet deployment, quality-gate
waiver, physical executor closure or parent-task completion.

