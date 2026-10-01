# Bounded waits and minimal-context recovery

Iteration 2 adds read-only recommendations in `scripts/recovery.py`. It uses explicit UTC times and caller-supplied records, with no clock reads, sleep, provider requests, launch, cancel, persistence, ownership acquisition or authorization. Its CLI prints deterministic JSON. Exit 0 means a valid recommendation, including reconciliation; exit 2 means malformed input. A recommendation does not prove that caller-supplied provider facts or durable hashes are authentic.

## Supervise one existing operation

`supervise_wait(state, observation, policy, now)` consumes one attempted poll and returns an updated **proposed** state, action, reasons, suggested next-poll delay, external guard, and false submission/completion permissions. Persist the proposed state through the existing authorized coordination store without moving the candidate branch. `validate_wait_state(state)` and `validate_wait_policy(policy)` raise `ValueError` for invalid contracts.

Use `templates/external-wait.json` as a fictional shape example, never as real provider evidence. Its schema is `external-wait/v1`. It contains:

| Fields | Meaning |
| --- | --- |
| `operation_key`, `attempt_id`, `candidate_sha` | Exact immutable operation/attempt/candidate association; reconcile with the operation intent first. |
| `task_id` | Actual provider task, or null while the submission outcome is unknown. A known task cannot be replaced. |
| `phase`, `phase_started_at_utc` | `unknown`, `queued`, `setup`, `running`, or `terminal`; first observed start of the phase, never reset by repeated observations. |
| `last_successful_observation` | Full last trusted, complete, timely provider observation; null until one exists. Failed polls never refresh it. |
| `last_poll_at_utc` | Time of the latest attempted poll, including errors; distinct from successful observation time. |
| `observation_valid`, `source_valid` | Separate latest task-observation validity and response-source validity; a rate-limit response may have a trusted source without a valid task observation. |
| `trusted_retry_after` | Optional persisted authenticated transport timing: null or `{source, observed_at_utc, retry_after_seconds}`. Retained independently of task success; omitted on older v1 records is treated as null. |
| `unchanged_polls`, `error_polls` | Consecutive unchanged successful polls and consecutive unsuccessful polls; the other streak resets. |

Known phases require an actual task ID in both restored state and successful fresh observations. Without that identity, use `phase: unknown`, retaining the original submission/uncertainty timestamp and guard. If an old record claimed queued/running without an ID, preserve that raw record as unresolved evidence outside the validated state; do not treat it as a successful task observation, invent an ID, or reset the deadline to the current wake. Reconcile the actual task first. Authenticated Retry-After still applies independently of task identity.

A `wait-observation/v1` has these exact fields: `schema`, `operation_key`, `attempt_id`, `task_id`, `candidate_sha`, `phase`, `observed_at_utc`, `source`, `source_valid`, `observation_valid`, `lookup_complete`, `conclusion`, `evidence_refs`, and `retry_after_seconds`. `source` identifies the actual provider read, and the three validity/completeness flags are real booleans. Validate actual task association and the full intent binding before setting them true. A request's echoed SHA, copied prompt, cached spinner, or assumed environment is insufficient. The operation key covers the full execution contract; this helper assumes that upstream intent reconciliation already verified it. Pass null/omit CLI observation for an unsuccessful or timed-out poll; never translate a client polling timeout into a provider terminal phase.

Use null `conclusion` outside terminal. Terminal conclusions are `succeeded`, `failed`, `cancelled`, `timed_out`, or `setup_failed`; only a trusted complete provider observation can establish one. Nonempty evidence references are required for terminal reuse. `retry_after_seconds` is a nonnegative integer or null. Lists are capped at 256 entries; counters and integer settings are capped at `2**53-1`.

The wait policy has exactly seven positive integer fields:

| Field | Example seconds |
| --- | ---: |
| `queued_seconds` | 300 |
| `setup_seconds` | 600 |
| `running_seconds` | 1800 |
| `unknown_seconds` | 300 |
| `observation_max_age_seconds` | 120 |
| `poll_initial_seconds` | 5 |
| `poll_cap_seconds` | 60 |

Thresholds are independent diagnostic deadlines. Reaching one recommends inspecting the existing task, setup logs, queue status or provider health. It **never** terminates the task, clears its guard, expires its intent, creates another attempt or authorizes relaunch. Unknown phase always requires reconciliation. A phase transition starts its own deadline at the successful observation time; providers may have entered that phase earlier, so the recorded timestamp is a conservative observed boundary. Backward phases, stale/future observations, timestamp regressions, changed operation/attempt/task/candidate, changed terminal outcome, and contradictory same-time observations are rejected while preserving the last trustworthy phase and its deadline.

Poll spacing grows exponentially with unchanged/error streaks, capped by `poll_cap_seconds`; provider Retry-After is a minimum that can exceed that cap. Its remaining duration survives unsuccessful polls and later successful observations without a Retry-After header. An authenticated fresh response for this operation can supply this timing even when rate-limited (HTTP 429), task observation validity is false, or lookup is incomplete; it does not update `last_successful_observation`, task identity, phase or phase deadline. Persist `trusted_retry_after` with the proposed state. Unknown/untrusted sources, wrong operation scope, and stale/future timestamps cannot supply retry timing. A longer authenticated retry deadline takes precedence over an existing shorter one. Long suggested delays are scheduling intervals, not permission to block for that duration. **Any actual blocking wait chunk must be at most 60 seconds**, with progress and stop/budget checks between chunks. Use a future wake instead of holding a session when appropriate. Record every attempted poll, including errors, without imposing a default task/wake count cap (`status_polls: null`). Continue observing the same authorized task until a trusted terminal result or a phase deadline requires diagnosis. A fifth poll is not a new compute start and needs no additional user permission. Genuine provider/runtime/resource limits still require a durable handoff: preserve the original task, phase start, next eligible observation time and unresolved guard; use an already-authorized continuation mechanism when available. Do not invent or reset deadlines, silently remove a separate explicit user cap, or start a replacement task. Migrate older default poll caps only through an authorized policy update.

`reuse_terminal` clears only this one operation's in-flight recommendation, never another guard or lease. It still returns `completion_claim_allowed:false` and `allow_submission:false`; even successful provider termination is not GREEN. Verify candidate-bound command, platform, artifact and release evidence separately. Lost lookup, lease expiry, poll error or elapsed threshold retains the external guard. Known terminal facts without current trustworthy observation also require reconciliation.

```bash
python3 scripts/recovery.py wait --state external-wait.json \
  --observation wait-observation.json --policy wait-policy.json \
  --now 2026-09-22T10:02:00Z
```

## Minimal-context recovery

`decide_recovery(snapshot, live_probe, now, max_age_seconds=300)` recommends a read set only. Every new runtime first loads the actual installed core skill and `VERSION`, repository adapter, **all current applicable instructions**, and compact checkpoint. This includes nested `AGENTS.md` and project-specific instruction files, regardless of unchanged hashes. The helper's conventional `AGENTS.md`, `docs/development-cycle.yaml`, and `docs/work-status/current.md` paths must be mapped to actual configured repository paths; they are not exhaustive instruction discovery.

A snapshot uses `recovery-snapshot/v1`, `observed_at_utc`, `phase`, and `bindings`. A live probe uses `recovery-probe/v1`, `observed_at_utc`, `phase`, identical `bindings`, plus `complete:true` and `source_valid:true`. The entire probe must come from a complete fresh independent read, not a copied snapshot with a refreshed timestamp. Validate the repository policy/checkpoint and actual installed skill version as part of the read. Missing, unknown, unavailable or partly verified state must set completeness false; null/omitted probe can never enable fast recovery.

| Binding | Required coverage |
| --- | --- |
| `repository`, `default_branch`, `working_branch`, `head_sha` | Canonical live repository and exact branch/candidate identity. |
| `policy_revision`, `policy_digest`, `skill_version` | Reconciled policy identity and actual installed exact skill version. A version upgrade invalidates the snapshot even with unchanged HEAD. |
| `instructions` | Complete ordered manifest of instruction/spec/task/log paths, SHA-256 digests, `kind`, and `durable_verified:true`. Kinds: `instruction`, `specification`, `task_list`, `log`. Classify all applicable instructions as `instruction`, even inside a specification. |
| `task_state_fingerprint` | All active task state, not just current task ID. |
| `checkpoint_version`, `checkpoint_digest` | Complete compact checkpoint contract and content. |
| `lease_owner`, `lease_generation`, `lease_store_revision` | Current owner (null allowed), fencing generation and authoritative store revision. |
| `external_operations` | Complete ordered operation set, including unknown submissions: each has exact `operation_key`, `attempt_id`, nullable `task_id`, `state`, and durable `revision`. An empty list means verified absence. |
| `pr_revision`, `ci_revision`, `release_revision` | Revisions/fingerprints of complete relevant live PR, CI and release state, or explicit verified `none`. |

Digest wire mapping is explicit: the adapter validator and checkpoint store `policy_digest` as bare 64-character lowercase hex. Snapshot/probe `bindings.policy_digest` **must** be `"sha256:" + raw_policy_digest`. Do not change the policy digest calculation or checkpoint contract. Other digest fields already represented as `sha256:…` (operation keys, instruction digests, checkpoint/task fingerprints) pass through unchanged; never double-prefix them. Apply the same mapping to the snapshot and independently collected live probe.

Use canonical stable ordering for manifests and operation sets. If a provider lacks a revision token, compute a durable canonical digest over all relevant state; do not use HEAD alone. Observation time, complete lookup scope, set membership and every record revision matter. Store revision/fingerprint sources durably so they can be independently reverified. Never invent a revision or claim `none` when lookup failed. An instruction digest permits skipping an unchanged lengthy spec/log body only after retrieving and verifying that durable digest against the actual current content. Assistant memory is never an instruction source.

Only fresh snapshot and probe with every binding and phase equal enable `fast_path:true`. Any changed identity, policy, skill version, instruction/task content, checkpoint, lease owner/generation/store revision, operation membership/state/revision, PR/CI/release revision, or phase requires expanded reconciliation. Stale/future/backward, incomplete, malformed or missing probes also require expanded reconciliation. Default max age is 300 seconds; the project may configure another explicit positive bound.

The returned `read_set` always includes core/runtime instructions and the compact checkpoint. With a verified match it adds only the phase-relevant references (external wait, RED, implementation, validation, final gate, review, release, blocked recovery or closure). Otherwise it includes known old/new manifest paths and expanded reconciliation references. It never blesses cached GREEN or grants write/submission permission; `allow_write`, `allow_submission`, and `completion_claim_allowed` remain false. Ownership/fencing, policy authorization, candidate evidence, operation reconciliation and resource budgets remain separate mandatory gates. Missing durable sources or unverified hashes means no fast path, even when the assistant remembers a previous success.

```bash
python3 scripts/recovery.py recover --snapshot recovery-snapshot.json \
  --live-probe recovery-probe.json --now 2026-09-22T10:01:00Z \
  --max-age-seconds 300
```

`templates/recovery-snapshot.json` is demonstrative fictional data; it does not establish current state or permission.
