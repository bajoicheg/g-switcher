# Cooperative execution ownership

Iteration 2 provides a real conditional Git store and a cooperative ownership protocol. It does **not** fence arbitrary product-ref pushes or provider calls. All writers must obey the protocol; branch permissions and provider authorization remain separate.

Contents: [Configuration](#configuration) · [Lease and handoff](#lease-and-handoff) · [External guard](#external-guard) · [CLI and API](#cli-and-api) · [Boundaries](#boundaries).

## Configuration

Adapter v3 retains its version. Optional `orchestration.execution_lease` requires skill 2.3+:

```json
{"backend":"git","remote":"origin","coordination_ref":"refs/heads/cdc-coordination","designated_executor_id":null,"assignment_ref":null}
```

Use an already authorized coordination ref distinct from the product source ref. The caller must independently verify that the configured remote corresponds to the exact canonical repository identity, the actual source ref, and the authorized write scope. A matching display name is insufficient. The helper validates exact recorded bindings, not remote identity attestation. The remote must have one identical fetch and push URL. Do not configure secrets in references or evidence fields.

`GitLeaseStore` reads the remote ref, fetches its objects, decodes `lease.json`, and rechecks that the remote revision stayed stable during reading. It creates one new commit with exactly the previously observed revision as parent and pushes that commit using a normal, non-force fast-forward push. Racing proposals are siblings; the Git server accepts at most one. Stale expected revisions fail. Initial creation uses a root commit. No force or force-with-lease option is used. It never checks out a branch, resets a worktree, stages files, or edits the index. The coordination ref must not be deleted, rewound, or rewritten; protect it accordingly. Persistent generation continuity depends on retained coordination history.

When a conditional backend is unavailable, use explicit single-writer policy:

```json
{"backend":"single_writer","remote":null,"coordination_ref":null,"designated_executor_id":"00000000-0000-4000-8000-000000000001","assignment_ref":"policy:verified-owner-assignment"}
```

The designated UUID and the assignment reference must identify the current authorized executor invocation; verify the assignment source. Every other executor is read-only. Null designation/assignment means observer-only. `check_designated_executor` checks those fields but neither acquires a lock nor proves exclusivity. Do not substitute local files, atomic rename, timestamps, or a fabricated lock. If a prior writer's status is uncertain, remain observer-only. Preserve external operation intents and unknown guards through the existing durable recovery route even in single-writer mode. This fallback cannot use the Git CAS submission-claim API: only the initial in-memory transition to `submitting` in the current designated execution may be used once after actual durable publication and readback. Any restored `submitting` or `unknown` intent only permits reconciliation; never reconstruct a launch permit from it. Fallback safety depends on the independently enforced single-writer assignment and absence of competing invocations, not an atomic guarantee from this helper.

## Lease and handoff

`templates/execution-lease.json` shows an unowned fictional record. `execution-lease/v1` binds exact `repository` and `source_ref`, and keeps a persistent integer `generation`. Every acquisition increments it; release never resets it. Each new executor invocation generates a fresh UUID. CLI acquisition generates this UUID itself; subsequent commands use the returned UUID and generation. Never reuse an executor identity for a new invocation.

The default lease TTL is 1,200 seconds; owner heartbeat freshness is 600 seconds. Renew only after a unique observable activity reference, such as an actual command result, persisted checkpoint, or newly observed provider event. Repeated references are rejected within the generation. Polling the same state, scheduler wakes, and elapsed time are not activity. The helper validates uniqueness and timestamps; the caller verifies the referenced activity actually occurred.

Every renew, release, guard update and side-effect check requires the current owner UUID and generation. Every durable mutation also requires the exact expected store revision. Refetch immediately before each shared write or external start and call `check`; do not cache its successful result across waits, phase changes, retries, or other actions. Check actual product HEAD separately before a normal non-force product push. The `observe` action permits coordination recovery without asserting fresh write permission; any executor may read without a lease.

**Expiry alone never authorizes takeover.** An expired owner can still perform a previously prepared write. Acquisition needs either an explicit prior release or independently verified evidence that the prior executor stopped and cannot perform outstanding writes. Quiescence must cover launched child writers and in-flight product mutations; merely terminating a UI session is insufficient. The evidence object is:

```json
{"owner_id":"00000000-0000-4000-8000-000000000001","generation":1,"repository":"example/project","source_ref":"refs/heads/main","kind":"executor_stopped","reference":"runtime:verified-shutdown/1"}
```

The helper requires an exact match to the recorded prior owner, generation and binding. The caller must retrieve and verify the actual evidence. A supplied string is not remote attestation. Missing or unverifiable quiescence leaves other executors observer-only, even after TTL or heartbeat expiry. Release only after stopping shared writes and draining any outstanding writer; once released, the old executor must never resume writing. Before it can act again, it needs a new invocation and UUID.

## External guard

The durable CAS claim sequence below applies to the Git backend. The single-writer fallback follows the stricter restoration rule above under its independent assignment.

The lease's `external_guard` persists independently of heartbeat, expiry, release and takeover. It contains the exact validated operation intent, its operation key, durable reference, SHA-256 digest of canonical intent content, and `submission_claim` (null until consumed). Persistent `submission_claims` retains every consumed operation/attempt even after terminal guard clearance; renewals, guard updates and handoffs cannot reset consumption. Integrate with [external operations](external-operations.md):

1. Prepare, durably publish, and read back the operation intent. Transition it to `submitting`, durably publish it and read it back again.
2. Under current ownership, persist `set_guard` with that exact `submitting` intent and its actual durable reference. Read the coordination record back and compare its returned revision and full content. Stop if publication or readback is uncertain.
3. Immediately before the single authorized submit, call `claim_submission` with the exact guard digest and current revision. It rechecks current ownership, generation, binding, freshness and unconsumed intent, then uses CAS to persist consumption **before** returning a fresh launch grant. Submit exactly once using only that freshly returned grant. `check(action="external_start")` checks eligibility only; it never authorizes a submit. All intent recovery, source-HEAD, budget and authorization checks still apply.
4. If the claim response is lost, reread and reconcile: a stored claim is recovery evidence, never permission to reconstruct a launch grant. Do not resubmit the claim to recover permission. If the external submit response is lost, retain the already durable `submitting` guard; when possible update it to the matching `unknown` intent. Never replace it with another attempt or reset it to `submitting`. Reconcile rather than submit again.
5. `clear_guard` requires a matching operation observation that `operation_intent.decide` classifies as `reuse_terminal`, plus an actual provider/evidence reference. Empty, incomplete, mismatched, active or unknown observations cannot clear it. The terminal observation/reference remains in `last_terminal` and in Git history.

An unresolved guard blocks product writes and new external submissions. The one initial submission claim accepts only its exact unconsumed guarded `submitting` digest. A successful CAS returns `{revision, grant}`; the stored grant binds a fresh `grant_id`, owner UUID, generation, operation key, attempt ID, intent digest and claim time. Repeated claims fail, including the same owner using a fresh store revision. `set_guard` and `renew` cannot rearm that attempt, and clearing the terminal guard does not erase consumed history. A crash after consumption but before submit can conservatively leave an unsubmitted attempt guarded; reconcile it under explicit policy. This grants at most one launch boundary through cooperating callers; it does not fence a provider or promise transport exactly-once execution. Coordinate-only observation remains allowed; a new owner can reconcile the old external operation without changing the source ref. Clearing a terminal failed/cancelled/timed-out task permits recovery decisions, not a completion claim.

## CLI and API

All commands print JSON. Errors exit 2; successful output includes `revision` and `record`, except `check`, which returns the checked binding and revision, and `claim-submission`, which returns `{revision, grant}` only after successful CAS. No command submits provider work or writes a product branch.

```bash
python3 scripts/execution_lease.py read --repo /path/to/repo \
  --remote origin --coordination-ref refs/heads/cdc-coordination
python3 scripts/execution_lease.py acquire --repo /path/to/repo \
  --remote origin --coordination-ref refs/heads/cdc-coordination --request acquire.json
```

Every request except `read` includes `expected_revision` (null only for `init`), `repository`, and `source_ref`. Additional request fields are:

| Command | Fields |
| --- | --- |
| `init` | None; requires absent coordination record. |
| `acquire` | `at`, optional `ttl`, optional `quiescence`; UUID generated by CLI. |
| `renew` | `owner_id`, `generation`, `at`, unique `activity_ref`, optional `ttl`. |
| `release` | `owner_id`, `generation`, `at`. |
| `guard` set/update | `owner_id`, `generation`, `at`, full `intent`, `intent_reference`. |
| `guard` clear | `owner_id`, `generation`, `at`, full `observation`, `evidence_reference`. |
| `claim-submission` | `owner_id`, `generation`, `at`, exact `intent_digest`, optional `heartbeat_freshness`. |
| `check` | `owner_id`, `generation`, `at`, `action` (`product_write`, `external_start`, `observe`), optional `intent_digest`, optional `heartbeat_freshness`. |

Example `acquire.json` after independently reading the actual store revision:

```json
{"expected_revision":"REPLACE_WITH_ACTUAL_FULL_COORDINATION_COMMIT","repository":"example/project","source_ref":"refs/heads/main","at":"2026-09-22T10:00:00Z"}
```

Python API: `GitLeaseStore(repo, remote, coordination_ref).read()` returns `(revision, record)`. Pure functions `initialize`, `acquire`, `renew`, `release`, `set_guard`, and `clear_guard` return proposed records; persist them with `store.compare_and_swap(expected_revision, record)`. `check(store, expected_revision, repository, source_ref, owner_id, generation, at, **options)` refetches and checks the authoritative record. `claim_submission(store, expected_revision, repository, source_ref, owner_id, generation, at, *, intent_digest, heartbeat_freshness=600)` atomically consumes the guarded attempt and returns the fresh grant. Use `check_record` only to inspect already obtained state; it does not revalidate remote ownership.

## Boundaries

The Git CAS serializes the coordination record only. There is a check-to-action interval before product pushes/provider calls, and those targets do not enforce the lease generation. The no-timeout-takeover rule, verified quiescence, explicit release discipline, immediate rechecks, and existing product-ref concurrency guard are therefore mandatory. No remote attestation, hostile-writer resistance, clock attestation, provider-side idempotency, or arbitrary-write fencing is claimed. A storage network error or lost push response is an unknown outcome: reread and reconcile the owner/guard before proceeding, never blindly retry acquisition or external submission.
