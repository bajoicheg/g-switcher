# External operation intents

Use an `operation-intent/v1` record before submitting external compute or CI. A lost submit response is an **unknown outcome**, not proof that no task exists. Recover the original operation before considering another attempt.

The intent helper provides a Python standard-library record contract and a read-only recovery decision. It never calls a provider, launches or cancels work, grants retry authorization or verifies build evidence. Skill 2.3 composes it with ownership, waiting and budget controls through `references/orchestration-controls.md`; intent readback alone is not launch permission.

Contents: [Identity and record](#identity-and-record) · [Persist before the external action](#persist-before-the-external-action) · [CLI](#cli) · [Provider observations and recovery](#provider-observations-and-recovery).

## Identity and record

`templates/operation-intent.json` is a valid fictional prepared record. Regenerate it from actual repository facts; do not use its example SHA, identifiers or fingerprints for a real submission.

The immutable binding contains:

| Field | Meaning |
| --- | --- |
| `repository` | Canonical provider repository identity obtained from live facts; do not guess aliases. |
| `candidate_sha` | Exact full lowercase Git SHA, 40 or 64 hex characters. |
| `backend`, `mode` | Provider and execution contract, such as `codex` and `COMPUTE_ONLY`. |
| `check_suite_fingerprint` | SHA-256 of the reviewed check definitions and acceptance criteria. |
| `environment_fingerprint` | SHA-256 of the actual non-secret image/toolchain/setup/network/configuration contract. |
| `check_plan_digest` | SHA-256 of the exact ordered commands, arguments, required platforms and expected outputs. |
| `environment_id` | Actual provider environment association, independently verified. |

Digest values use `sha256:` followed by 64 lowercase hex characters. Persist the underlying suite, environment configuration and check plan beside the checkpoint/runbook so a later executor can recompute them. Set `environment_fingerprint` to `"sha256:" + evidence.environment.configuration_sha256`, whose evidence field is bare lowercase hex. Cover SDK/toolchain, dependency locks and setup configuration; an OS/host hash or environment name/ID alone is not a configuration fingerprint. The evidence's separate `environment.fingerprint` describes the observed host/runtime and is not this stable operation identity. Exclude secrets, volatile display state and timestamps from contract fingerprints.

The operation key is SHA-256 of UTF-8 canonical JSON `{"schema":"operation-intent/v1","binding":BINDING}`: sorted object keys, compact separators, unescaped Unicode, no NaN. Object ordering does not affect identity; list/command ordering does. The helper validates supplied fingerprints but cannot establish that they describe the actual provider configuration.

`attempt_id` identifies one explicit attempt and must be included with `operation_key` in provider metadata or the request text. It does not change the operation key. `source_ref` is the exact branch/ref whose stability must be maintained; it is recorded separately from the content identity. Creating another filename or attempt ID does not authorize a duplicate submission. Locate all durable records and provider requests by operation key before a new attempt.

All records have `created_at_utc` and `updated_at_utc` in UTC ISO 8601 ending in `Z`. The helper rejects missing/extra/duplicate JSON fields, invalid types, shortened SHAs, key mismatches and backward timestamps. Supported record states are:

| State | Meaning and next states |
| --- | --- |
| `prepared` | Local intent created; next `submitting` requires matching durable readback evidence. |
| `submitting` | Submission boundary entered; next `accepted`, `unknown` or `terminal`. |
| `unknown` | Submission may have happened; next `accepted` or `terminal` after reconciliation. |
| `accepted` | Exact provider task known, queued or running; next `terminal`. |
| `terminal` | Provider outcome recorded; no backward transition or replacement task binding. |

Repeating the same state and data is idempotent. Record acceptance once; intermediate provider observations remain read-only. Never reset `unknown` to `prepared` or `submitting`. A fresh attempt is a separate policy decision after reconciliation, with a new attempt ID and the old record preserved; this helper never makes that decision.

## Persist before the external action

1. Apply existing repository authorization, budget, exact-SHA and single-writer lease rules. Refetch source HEAD and inspect existing compute/CI and operation records. Keep the source ref fixed once the candidate is selected.
2. Prepare the local intent. Persist the complete record in the repository or an authorized durable coordination store, then retrieve it independently and compare the readback. A local file, staged change, local commit, or failed remote save is not durable recovery state.
3. Use that readback receipt to record `submitting`. Persist and read back this updated record **before invoking the external submit tool**. Include the operation key and attempt ID in the request, and a native idempotency token if the provider supports one. Metadata is a lookup aid, not proof of provider-side idempotency.
4. Complete `references/orchestration-controls.md`: durably reserve budget, arm the exact guard and recheck ownership/source HEAD. Git mode requires a fresh one-use CAS submission grant; designated single-writer mode uses only its initial in-memory transition as specified in `references/execution-ownership.md`. Then submit once through the authorized provider route. Persist returned request/comment and actual task IDs with verified binding. A sent comment is not acceptance or execution evidence.
5. If the response is lost, record and persist `unknown` when possible. If this write also fails, the durable `submitting` record still requires reconciliation. Preserve `waiting_external`, the exact SHA, intent reference and one recovery action on handoff.

Keep candidate branch HEAD stable throughout these writes. Use the existing authorized coordination store or authoritative PR coordination record if a checkpoint commit would move the requested source HEAD. Do not create a new external message channel without authorization. Reconcile repository checkpoint files after the external operation is terminal.

The helper compares caller-supplied readback content and records its reference; it cannot authenticate where that content came from or perform remote persistence. Never fabricate a receipt or copy the local file and call it remote readback. A matching readback from the actual durable store is required at both boundaries. If durable persistence or readback fails, stop before submission and preserve recovery state.

## CLI

Run via Python, with paths appropriate to the installed skill. Commands print JSON; invalid input or failed local persistence exits 2 with a diagnostic. `decide` exits 0 for a valid decision, including `blocked`: inspect its `action`, not merely the process exit code.

```bash
python3 scripts/operation_intent.py prepare --binding binding.json \
  --source-ref refs/heads/candidate --attempt-id attempt-001 \
  --at 2026-09-22T10:00:00Z --output intent.json

# After successful durable publication and independent retrieval:
python3 scripts/operation_intent.py readback --intent intent.json \
  --readback durable-readback.json --reference coordination-record-reference \
  --at 2026-09-22T10:01:00Z > prepared-receipt.json
python3 scripts/operation_intent.py transition --intent intent.json \
  --state submitting --receipt prepared-receipt.json --at 2026-09-22T10:02:00Z

# Publish/read back submitting, reserve budget and pass the ownership protocol
# before the single external submission; this intent CLI grants no launch permit.
# If submission response is lost:
python3 scripts/operation_intent.py transition --intent intent.json \
  --state unknown --at 2026-09-22T10:03:00Z

python3 scripts/operation_intent.py decide --intent intent.json \
  --observation provider-observation.json
python3 scripts/operation_intent.py validate --intent intent.json
```

For acceptance or terminal outcomes, pass `transition --state accepted|terminal --task task.json --at UTC`. The task object follows the contract below. Publish and read back meaningful state changes through the same durable route.

Local create uses an atomic create-if-absent operation; updates use atomic replacement, verify the expected previous content and reject unrelated identities or backward transitions. These checks prevent accidental local overwrites. **They are not a distributed lock or compare-and-swap.** Acquire and retain the existing single-writer lease separately; two executors must not race these commands.

## Provider observations and recovery

The provider adapter supplies an object with exactly `schema: "operation-observation/v1"`, the original `operation_key`, `observed_at_utc`, boolean `lookup_complete`, and `tasks` (a list). Observations must be at least as recent as the recorded update. `lookup_complete` is true only after all relevant pages, active/terminal task views and known request/task IDs have been checked for the operation; an error, unavailable lookup, partial page, delayed index or uncertain visibility is false. Include every plausible candidate; do not filter away inconvenient duplicate or mismatched results. Search by operation key across attempts, then check the explicit attempt ID.

Each task has exactly these fields:

| Field | Required value |
| --- | --- |
| `task_id`, `task_url` | Nonempty actual provider task identity and reference. |
| `operation_key`, `attempt_id` | The request's operation and attempt identifiers. |
| `binding` | All binding fields above, independently observed from actual task association and execution configuration. |
| `state` | `accepted`, `queued`, `running`, `terminal` or `unknown`. |
| `conclusion` | Null until terminal; then `succeeded`, `failed`, `cancelled`, `timed_out` or `setup_failed`. |
| `evidence_refs` | List of nonempty log/artifact references; required for terminal reuse. |

An echoed request SHA, requested environment, operation key or prompt is not independently verified actual task binding. If the provider cannot establish the binding or completeness, retain the external guard and reconcile; do not invent observed values. Normalize provider-specific statuses to this vocabulary without treating setup completion as validation success or a client-side polling timeout as a terminal task timeout.

| Observation | Decision |
| --- | --- |
| One exact accepted/queued/running task and complete lookup | `observe` the existing task; external guard remains. |
| One exact terminal task with evidence and complete lookup | `reuse_terminal` outcome/evidence; normal evidence verification still applies. |
| No task, unavailable/incomplete lookup, unknown task state or missing evidence | `reconcile`; external guard remains even after a complete empty lookup. |
| Multiple candidates, wrong binding/attempt/task ID, stale scope/time or contradictory terminal state | `blocked`; external guard remains until reconciled. |

Every decision has `allow_submission: false` and `completion_claim_allowed: false`. Repeated wakes only observe/reconcile; they do not create replacements. `reuse_terminal` clears only this operation's in-flight guard, not repository ownership, other external guards or required release gates. Reuse the recorded terminal evidence through `validation-compute-and-ci.md`; a terminal timeout, cancellation, setup failure or nonzero result never completes validation. Even `succeeded` still requires exact-SHA, clean-state, command, exit, platform and artifact checks.

Unknown submission outcomes remain guarded when the writer lease expires. No local timeout, stale heartbeat, missing lookup result or unavailable provider API proves remote work is absent. Release writer ownership on handoff while keeping this external guard. This bounded helper intentionally provides neither automatic resubmission nor a distributed retry/lease protocol.
