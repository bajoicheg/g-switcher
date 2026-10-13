# Execution efficiency

Use the actual execution path, not a planner's savings claim. This3.4.0 capability
extends existing quality, evidence, budget and finalization contracts.

## Check runner

New plans use `command-check-plan/v2`; v1 remains compatible for existing callers.
Checks retain the v1 id/kind/required/argv/timeout/optional expected_red shape.
An `economics` object contains:

- `check_inputs`: one entry per check ID with relative regular-file
  `dependency_fingerprints` (SHA256), JSON `parameters`, reviewed `coverage_refs`
  and boolean `exact_candidate_required`.
- `aggregate_check_ids`: declared expensive aggregate IDs, in execution order.
- `prior_evidence`: absolute regular receipt paths with exact SHA256. Their
  companion plan/log/JUnit artifacts must remain available and authentic.
- `repeat_exceptions`: check_id/reason/coverage_ref for distinct additional
  aggregate coverage or a repeat whose old proof is insufficient.

The runner computes argv/check-definition/environment fingerprints, reads current
dependency bytes, authenticates original receipt/plan/log/test artifacts, and
composes evidence-reuse/v1. A successful covered check becomes REUSED without
Popen. Its executed=false and exit_code=null describe this invocation; original
SHA and receipt provenance remain in reuse. It never claims a fresh exact-SHA run.
Corrupt prior evidence is an error, not permission for an expensive retry.
Changed covered dependencies require affected validation; exact-candidate checks
stay bound to their original SHA. Required release/platform checks remain required.

Run targeted regressions while editing, then one required hosted FULL on the
frozen candidate. Portable source/clean-consumer/installation repeats need a
distinct coverage or environment justification. Installation verifies package
identity, adapter/checkpoint compatibility and product preservation using accepted
release evidence; it does not rerun canonical logic by habit. Batch compatible
changes into that candidate; metadata alone does not require a runtime release.

## Bounded reading and current state

`cdc.py inspect FILE --pointer /status --pointer /current --max-bytes 8192`
returns selected RFC6901 fields, original whole-file SHA256/byte size, and explicit
omission markers. Larger values are digested rather than printed. Output includes
at most8192UTF8bytes including newline; an impossible metadata budget fails closed.
No root pointer or automatic full-history dump is supported.

Maintain one authoritative current checkpoint with immutable history links.
Load current source/policy/ownership/budget once on resume and refresh the relevant
facts when changed or before an effect. Historical AGENTS/roadmap bytes belong in
linked archives, not repeatedly loaded current instructions. Batch independent
reads, search explicit roots/types, and cap output before returning it to a model.

`cdc.py runtime REQUEST` hashes the actual installed inventory and loader against
the pinned commit/tree/version, reads actual Git HEAD and its tracked loader blob,
and rejects a different commit or uncommitted loader. The acceptance reference is
caller-supplied provenance, explicitly marked unverified by this local adapter.
A stale interface loader digest
is explicitly classified; it cannot replace authenticated saved bytes. This
cheap read needs no archive extraction, FULL or CI. It proves bytes, not behavior.
The initial acceptance/provenance must come from the actual saved version; this
read-only adapter does not authenticate a fabricated caller's assertion.

## Execution, recovery and finish

`cdc.py efficient REQUEST` selects single execution/self-review for FAST reversible
text work, combined review for ordinary changes and ordered independence for FULL.
Parallel recommendations need independent tasks and a concrete benefit reference.
New tests cover distinct risks, not incidental implementation or prose phrases.
An exhausted unchanged-probe budget recommends eligible independent work or a
wait for new information. UNKNOWN keeps its original operation/guard and permanent
no-replay; apply supported retirement only under its original strict contract.

`cdc.py closeout REQUEST --repo PATH --remote REMOTE --coordination-ref REF`
reads the actual existing Git lease store and immutable released revision, invokes
the original final gate, then checks terminal/quiescent runtime, accepted/integrated
pool and fresh absence for the exact declared owned process ID set. Physical/runtime
observations need authentic host provenance; no textual bundle creates facts or
authority. Persist one bundle plus product remaining queue for Root intake.

`cdc.py audit-tests tests` reports identical AST bodies and dynamic-dependency
uncertainty. Identical bodies with different setup may cover different risks;
no automatic removal is allowed. Preserve Git history and map retired tests to
retained independent requirements before pruning. Supported-version review may
retire active compatibility fixtures, never the rollback/audit records.

## Observations

operation-observation/v2 retains v1 fields and adds `overhead`: context_bytes,
agent_starts, unchanged_probes, repeat_checks, coordination_seconds, finish_seconds.
Each is value/unknown_reason; missing usage stays null, never zero. Compare matched
work/environment/window groups through operation_report.compare. A reused real
check proves one avoided execution, not fleet-wide speedup, dollar savings or
model obedience. Prefer completion signals to repeated polls; no watchdog wake
or new executor is granted by this economics contract.
