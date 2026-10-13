# Task budgets and repeated-failure suppression (v2.3)

Use `scripts/budget.py` with the `budget-ledger/v1` template for a small durable per-task ledger. This is local admission accounting, not a provider telemetry platform, scheduler, billing estimate or launch authorization. Never invent platform token/tool quotas. The orchestration caller must record actual starts, polls and calls consistently; the helper cannot intercept tools or authenticate provider observations.

## Admission order and durability

1. Recover the task, current wake, adapter policy, lease and exact operation intent. Verify the adapter's current Actions budget; `policy.actions_budget` must match it. Unknown/lost-response external requests retain the iteration-1 external guard until reconciled. A new candidate, wake or reservation cannot bypass that guard.
2. Call `decide` using the exact prospective reservation. It returns `allow_reservation`, **always `allow_launch: false`**, `already_recorded`, reasons, and the known/unknown provider view. Budget approval is only one gate. Intent, lease, authorization, final-platform and Actions gates still apply independently.
3. Before the side effect, append the reservation, persist it in the task's existing durable store, and read back the complete matching ledger. Publish/read back the exact operation intent as required by `external-operations.md`. If either persistence/readback fails, do not launch. The local CLI's write/readback alone does not prove remote durable publication.
4. Only after all independent gates pass may the orchestrator perform the effect once. Record its outcome and observed usage. Lost responses, setup failures, cancellations, timeouts and crashes remain charged; there is no automatic refund. An exact duplicate reservation is an idempotent accounting replay, **never permission to repeat the external effect**.
5. Preserve the ledger and compact summary in the checkpoint/handoff. A wake appends a new unique wake ID to the same task ledger; it never resets task costs, active agents, failure circuits or consumed evidence.

Read-only observation and checkpointing can continue while expensive starts are blocked, subject to their own local/provider capacity. `actions_budget: exhausted` blocks every `ci_start` regardless of numerical counters, explicit kicks or apparent remaining provider quota. Do not trigger Actions indirectly through pushes/dispatches as an alternative route. `conserve` still requires the repository's candidate-GREEN/final-CI policy; this helper does not validate that evidence.

Ledger writes require the existing single-writer lease or the durable store's real CAS discipline. `write_ledger` checks the expected complete previous record, permits append-only changes, fsyncs, replaces locally and reads back. Its check-and-replace is **not atomic distributed CAS**; do not run competing writers. The policy digest detects accidental mismatch; it is not an authentication mechanism. Compare the ledger policy to the current adapter at recovery. Policy changes require an explicit reviewed migration preserving all task usage and circuits; do not create an empty replacement ledger to reset caps. This version intentionally does not automate policy migrations.

## Policy and units

`validate_policy(policy)` is public for adapter validation. Policy has exactly:

| Field | Meaning |
| --- | --- |
| `task_limits` | Caps over the entire task, including all wakes |
| `wake_limits` | Caps for the current wake only |
| `max_parallel_agents` | Adjustable nonnegative integer; zero prohibits agent starts |
| `checkpoint_reserve` | Nonnegative integer `tokens` and `tool_calls` kept before new compute/CI/agent starts |
| `provider_max_age_seconds` | Maximum age of a provider observation before its remaining value becomes unknown |
| `actions_budget` | `normal`, `conserve`, or `exhausted`; must equal the current adapter Actions policy |

Limit maps accept `compute_starts`, `ci_starts`, `agent_starts`, `status_polls`, `tool_calls`, `tokens`, `elapsed_seconds`. Omitted/null limits mean no configured local cap, never unlimited provider capacity. All configured limits are nonnegative integers except elapsed seconds, which may be fractional. Tokens are aggregate observed/reserved token units; do not pretend to distinguish input/output tokens without actual evidence. Elapsed seconds are accounted per reservation and summed; this is consumption accounting, not wall-clock phase deadlines.

Set task and wake agent-start caps separately from maximum parallelism. Prefer the minimum sufficient reasoning effort for each useful independent agent; a large cap is not a target, and maximum reasoning is not the default. Record actual available usage; if the platform does not expose it, retain null.

For each capped metric, admission compares existing charged usage + proposed reservation + checkpoint reserve (for expensive starts only) with both task and wake limits and fresh known provider remaining. Start/poll counts are one per reservation. Tool calls are explicitly supplied; `tool_call` and `status_poll` require at least one. Charge the invocation exactly once: a compute reservation with `tool_calls: 1` already covers that submission call, so do not separately charge it again. Count other calls (including reconciliation and quota lookups) with their own reservations. Use a new deterministic attempt ID per genuine poll/call when their operation key is shared.

`cost.tokens` and `cost.elapsed_seconds` may be conservative estimates or null. Outcome usage is observed cumulative consumption for that reservation, never an estimate. Charged usage is the maximum of the known reservation and observation, so a smaller actual result does not refund the reservation. If neither is known, totals stay null, with a known subtotal and unknown-entry count separately reported. Under a configured token/time cap, unknown usage cannot prove room and blocks admission against that cap; use real measurements or an explicitly reviewed policy adjustment. A missing provider observation is explicitly unknown, while local caps still apply.

Provider observations include a metric, `remaining` (number or null), `source` and UTC observation time. Record actual observations only. The helper conservatively subtracts subsequent local reservations/observed overages. Stale positive observations become unknown; they do not prove capacity. Known exhaustion stays blocked even after the observation expires or a later observation is null, until a newer, still-fresh positive provider observation establishes restoration. A positive observation that has since expired cannot clear prior known exhaustion. Replaying the same metric timestamp cannot replenish capacity. This ledger cannot account for other consumers of a shared provider quota: refresh real provider state before admission where sharing matters.

## Event contract

Every event has `type`, globally unique task-local `event_id`, exact `task_id`, current `wake_id`, and `at_utc` (`...Z`). Event order and timestamps must not regress. Exact duplicate IDs/payloads are idempotent; a changed payload conflicts. The ledger stores each event once. Identifiers and evidence references are caller supplied and must be stable across retries.

A reservation adds these exact fields:

```json
{
  "type": "reserve",
  "event_id": "reservation-1",
  "task_id": "task-1",
  "wake_id": "wake-1",
  "at_utc": "2026-09-22T10:00:00Z",
  "operation_key": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "attempt_id": "attempt-1",
  "kind": "compute_start",
  "scope": "codex/environment-1/setup",
  "recovery_ref": null,
  "cost": {"tool_calls": 1, "tokens": null, "elapsed_seconds": null}
}
```

Kinds: `compute_start`, `ci_start`, `agent_start`, `status_poll`, `tool_call`, `checkpoint`. Bind external starts to the exact operation-intent key and attempt. The tuple `(operation_key, attempt_id, kind)` may be reserved only once, even under another event ID. Nonexternal work also needs a stable SHA-256 operation identity. `scope` identifies the stable failure domain (provider/environment/configuration or code suite); **do not include the candidate SHA in an infrastructure scope**.

Other event-specific fields (in addition to the five common fields):

| Type | Required fields |
| --- | --- |
| `outcome` | `reservation_id`, `status`, `usage: {tokens, elapsed_seconds}`, `failure` |
| `provider` | `metric`, `remaining`, `source` |
| `remedy` | `scope`, `signature`, `reference`, `kind`, `detail` |

Outcome status is `unknown`, `succeeded`, `failed`, `setup_failed`, `cancelled`, or `timed_out`. Unknown preserves active-agent accounting. Only a terminal outcome releases an agent slot; all starts remain charged. Failure/setup-failure/timeout requires `failure: {signature, category}`, where category is `code`, `configuration`, or `infrastructure`; other statuses require null. The outcome's reservation ID binds it to the original operation/attempt. Terminal outcomes cannot be replaced; unknown may progress, but already observed cumulative usage cannot decrease or become unknown.

## Failure circuits

A failure opens the circuit for the reservation's stable scope. A new candidate SHA alone does not reopen it. Before another expensive reservation in that scope:

- Record a remedy referencing the exact current failure signature, with concrete detail and an independently checkable evidence reference.
- Use kind `code_correction`, `configuration_correction`, or `service_recovery`. Infrastructure failures require configuration correction or observed service recovery; a code-only candidate change is insufficient.
- Pass that evidence reference as the new reservation's `recovery_ref`. The helper consumes the reference once at reservation, even if submission later fails. Reusing it, including under a new event ID or wake, cannot grant unlimited retries.

A successful remedied retry closes only the exact failure event that its reservation addressed. It never clears a newer/intervening failure, even if the scope and signature are identical. Consumed recovery evidence remains consumed after closure.

Changing text labels or minting aliases for old evidence is not recovery. The caller must verify concrete corrected code/configuration or real service recovery; the helper checks structure, binding, ordering and one-use consumption, not evidence truth. A different observed failure gets its own recorded signature; an unresolved scope remains conservatively guarded until qualifying fresh evidence is supplied. Use fallback paths with independent scopes only when independently valid under project policy.

## Pure API and CLI

Pure functions: `validate_policy`, `new_ledger(task_id, wake_id, policy)`, `validate_ledger`, `begin_wake(ledger, wake_id)`, `decide(ledger, reservation)`, `apply_event(ledger, event)`, `summarize(ledger)`. They never call providers or mutate their inputs. `write_ledger(path, ledger, expected=old)` is the optional local persistence helper.

```bash
python scripts/budget.py init --ledger /tmp/task-budget.json --task-id task-1 --wake-id wake-1 --policy /tmp/budget-policy.json
python scripts/budget.py decide --ledger /tmp/task-budget.json --event /tmp/reservation.json
python scripts/budget.py apply --ledger /tmp/task-budget.json --event /tmp/reservation.json
python scripts/budget.py summary --ledger /tmp/task-budget.json
python scripts/budget.py wake --ledger /tmp/task-budget.json --wake-id wake-2
python scripts/budget.py validate --ledger /tmp/task-budget.json
```

`decide` emits JSON with reasons; a denied admission is a valid decision, not a parser error. Check `allow_reservation` and `already_recorded`, not process exit alone. `apply` exits 2 on rejection/conflict. Summary includes task and wake counters, known subtotals, unknown counts, observed token/time totals, and active agents. Store it compactly beside the full durable ledger; neither proves final validation or task completion.

Default `status_polls` limits are null at task and wake scope. Count and charge polls, but control their frequency with wait backoff/Retry-After and their duration with phase diagnostic deadlines. Do not ask the user to renew permission merely to observe an already-authorized task. Real provider/runtime/resource limits and separately explicit user caps remain effective; preserve automatic continuation state at a genuine handoff.


Default Codex Compute allowance is `wake_limits.compute_starts: 4`: at most four
charged starts in one orchestration wake/cycle, not four concurrent jobs and not
a provider quota. Apply an authorized global change to installed defaults, project
adapters and live ledgers together; preserve every event, wake, charge, active
operation and failure circuit. Recompute policy/checkpoint digests. Do not reset
the current wake: one charged start leaves at most three further reservations.
Keep GitHub Actions mode, CI-start caps and final platform gates unchanged.
Additional compute starts still need actual authorization, ownership and a
concrete remedy after a failure. A higher cap alone is not a retry instruction.

A **higher compute budget** buys room for more verified exploration, not lower standards. Prefer starts that can produce **distinct information**: a planned RED versus GREEN, a materially corrected candidate, an independent platform check, or a retry after observed service recovery. After any failed expensive start, require a **concrete correction** or recovery evidence for the affected scope before another reservation. Identical reruns with unchanged failure conditions are waste even when the numerical cap still has room.
