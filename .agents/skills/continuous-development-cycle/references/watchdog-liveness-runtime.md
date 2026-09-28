# Watchdog liveness and executable Fleet recovery

Use `watchdog_liveness.py` for current liveness decisions and
`fleet_watchdog_runtime.py` when an authorized caller supplies actual scheduler
capabilities. `watchdog_health.assess` also dispatches an explicit
`watchdog-liveness-probe/v1` to the new contract. The older
`watchdog-health-probe/v1` remains readable as a diagnostic; its six signals cannot
be upgraded into fresh pause, policy, terminal, or exact-invocation evidence.
Neither assessment grants mutation authority. `watchdog_self_repair.py` remains a
compatible planner; executable recovery is the Fleet runtime described here.

## Fresh independent facts

The probe binds exactly `project_id`, canonical `source_ref`, `watchdog_id`, and
stable `incident_id`. Each signal has its own `observed_at_utc`; the default maximum
age is 120 seconds, and future timestamps fail closed. Adapters must obtain fresh
authoritative facts, rather than put a new timestamp on cached facts.

| Signal | Required meaning |
| --- | --- |
| scheduler | `enabled`, `disabled`, `overdue`, or `unknown`; exact recurring `schedule` and `prompt` |
| invocation | `idle`, `running`, `completed`, or `unknown`; running/completed require an exact `invocation_id`; idle requires null |
| work | `runnable`, `terminal`, or `unknown`; current `source_revision` and `terminal_proof` |
| owner | `released`, `active`, or `unknown`, proven independently of lease TTL |
| guard | `released`, `active`, or `unknown`, including external submission guards |
| external | `none`, `submitting`, `queued`, `running`, `unknown`, `terminal_unreconciled`, or `terminal_reconciled` |
| progress | `fresh`, `stale`, or `unknown`; quietness never proves terminal work |
| pause | `running`, `paused`, or `unknown`; a pause requires current `owner_evidence` |
| policy | Explicit `recovery_allowed`, current `revision`, durable `owner_authorization`, and integer `effects_remaining` |

A terminal proof is an object containing `project_id`, `source_ref`,
`source_revision`, and `evidence_ref`. It must agree with the probe's project/ref
and the work signal's current exact Git revision. The adapter independently
verifies the referenced project-terminal proof; task completion, successful CI,
lease expiry, a silent chat, and a completed invocation cannot replace it.

Current explicit owner pause yields `PAUSED` even when delivery is broken.
Verified terminal work yields `COMPLETE`. Disabled/overdue delivery, or a completed
invocation with runnable work, yields `CRITICAL`. Unknown or stale facts never
grant recovery. `recovery_eligible` requires runnable work, independently released
owner and guard, no in-flight/unreconciled external work, an idle/completed exact
invocation, current unpaused policy authorization, and available provider budget.
Stale progress is a diagnostic; unknown progress blocks recovery.

## Supplied backend capabilities

There is no bundled ChatGPT, Automations, Work, or Codex host API. A caller may
provide a backend object implementing these Python methods:

```python
observe(project) -> watchdog_liveness_probe
enable(project, *, binding, operation_id, expected_schedule, expected_prompt)
run(project, *, binding, operation_id)
```

`project` contains project/ref/watchdog without the incident. `observe` performs
read-only collection. `enable` changes only enabled state, preserving the exact
recurring schedule and prompt. Its reply must contain `status: "accepted"` and
the exact `binding`. `run` requests one invocation and returns the same fields
plus its new exact `invocation_id`. A supplied adapter must have the actual
authorized capability before exposing either method, enforce its own bounded IO
timeouts, debit its authoritative provider budget, and use provider conditional
updates/idempotency where available. No `disable` capability is called or needed.

The runtime reads back enabled state, schedule, prompt, and the exact new invocation
from fresh observations. Unexpected replies, exceptions, stale readback, or
disagreement become `unknown`, even if the provider may have completed the effect.
Returned IDs alone are not readback evidence.

## Durable state and ordering

Construct `GitDocumentStore(repo, remote, coordination_ref, coordination_store_id,
protected_refs=...)` with one configured fetch/push endpoint. Obtain its opaque
identity using the existing `git_remote_identity` module. The coordination ref
must be a dedicated `refs/heads/cdc/...` branch. Include every product/shared/worker
ref in `protected_refs`; Fleet also rejects a registered source-ref collision.

This store accepts **only** a tree containing `document.json`. Existing other root
files cause rejection rather than silent replacement. It is unsuitable for a
shared multi-file coordination ref. Every read pins and rechecks the remote ref;
every proposal has a random nonce, and every CAS uses a normal non-force push.
Fetch/push endpoint identity is rechecked before mutation. Competing identical
proposals therefore cannot both receive authority. Bounded read/CAS retries permit
progress through ordinary contention without replaying a claim.

The document, managed-executor, and lease stores isolate transport from configured
local fetch/tracking mappings. They copy raw configured URL/pushURL values into a
unique command-scoped remote with no ref mappings; fetch additionally disables
implicit mappings with `--refmap=`. Git applies URL rewrite rules once. No local
product refs or persistent remote configuration are updated by these transports.
The lease store also pins its endpoint identity at construction and gives every
proposal a nonce, including otherwise identical proposals under the same clock.

Git identity/proof/control subprocesses use genuine object contents and ancestry:
their environment disables local replacement refs and legacy graft files. These
checkout-local overlays cannot substitute registry/journal bytes beneath a genuine
remote SHA or manufacture release/worker ancestry. The same Git-only protection
covers live target, package, handoff, and integration proofs. Independent bootstrap
uses an equivalent stdlib-only environment; arbitrary user validation commands and
worker command environments retain their existing semantics.

`FleetRuntime(store, backend).run_batch(projects, max_effects=...,
invocation_id=..., deadline_utc=...)` assesses every registered project (maximum
1000), durably checkpoints all assessments and remaining work, then attempts each
eligible recovery within the budget. `deadline_utc` is optional; supply the host's
actual wake deadline when available. Expiration stops effects and retains the
continuation; collection/checkpointing still completes using bounded adapter IO.

The first checkpoint fixes that invocation's effect limit and deadline. Each
per-effect claim consumes a durable reservation, including a claim whose reply
was lost or whose final gate denies the effect. Restarting the same invocation
cannot reset/increase its budget or extend its deadline. A new authorized wake
has a new invocation ID and a newly authorized budget. Local attempted-effect
accounting advances before IO, so failure to persist a completion cannot grant
extra calls later in the same batch.

Every enable and run requires a separate unique claim keyed by
project/ref/watchdog/incident/effect. After the claim, the runtime re-observes
policy, pause, owner, guard, external state, budget, and the exact expected previous
invocation immediately before IO. The check runs again between enable and run.
Pause before enable produces no effect; pause after enable prevents the run.
The recurring schedule is preserved in both cases.

Claims, outcomes, recovery steps, wake budgets, assessments, and `pending` survive
controller termination in `fleet-watchdog-state/v1`. `pending` and
`continuation_required` remain visible with zero effect budget and after premature
invocation completion. The runtime persists the continuation; a caller must arrange
the next authorized wake through the preserved schedule or a separately authorized
delivery adapter. Returning from this Python call does not declare project complete.
Unfinished durable recovery steps also keep continuation visible when enable has
already made a previously idle scheduler look healthy. A zero-budget wake retains
the unclaimed run; a later authorized wake executes it after fresh gates. Current
explicit pause or verified terminal work suppresses that unclaimed continuation.

## Unknown outcomes and cooperative limits

A claimed/unknown operation blocks the whole watchdog, even if a later probe
renames its incident, project, or source ref. It cannot be cleared by TTL, a new
controller invocation, a quiet scheduler, or a healthy-looking observation.
Successful scheduler IO also retains its exact `provider_invocation_id` with
`invocation_terminal: false` while the accepted run is active. An accepted request
is not a terminal invocation. Fresh `completed` evidence for that exact returned
ID, bound to the original project/ref/watchdog, can durably mark it terminal.
Idle visibility, another completed ID, and a renamed incident cannot clear this
gate. `pending` includes these accepted invocations for safe monitoring, so a
successful start does not by itself clear `continuation_required`.
Incidents must come from a durable authoritative incident lifecycle, not random
IDs generated per wake. After a confirmed run completes with runnable work, the
adapter may report a separately established next incident; it must not use this to
bypass an unresolved operation. Claims are never automatically deleted or retried.
There is deliberately no generic reconciliation authority: resolving ambiguity
requires independently verified provider evidence and an authorized coordination
transition. The narrow exact-ID completed-observation path above only reconciles
known successful receipts; it grants no authority to resolve unknown submissions.
Until then the runtime preserves the blocker and continuation.

This is a cooperative orchestrator, not a sandbox or platform final-channel
interceptor. With separate Git and scheduler services, a pause can race the
interval after the last observation and before the remote effect. The runtime
minimizes that interval and checks each effect, but cannot invent atomic host
preconditions. Stronger atomicity requires a real backend supporting conditional
mutation. The backend is a trusted capability boundary, not untrusted plugin code.

Ledger growth is bounded by the store's 4 MiB document limit. Exhaustion fails
closed; retention/reconciliation requires separate authorized maintenance and must
preserve unresolved claims. Existing active project owners and external submissions
remain blockers, regardless of scheduler health.

## Executable entrypoint and validation

```sh
python -B scripts/watchdog_liveness.py templates/watchdog-liveness-probe.json
python -B scripts/fleet_watchdog_runtime.py fleet-config.json --backend installed_adapter:build
```

The Fleet config contains `store` constructor arguments, `projects`, `max_effects`,
`invocation_id`, optional `deadline_utc`, and optional `backend_config`. The explicit
Python factory receives `backend_config` and returns the capability object.
Do not supply a real scheduler adapter without current owner authorization.

Tests use real local bare Git remotes and separate controller repositories, plus
an instrumented local scheduler that changes state and writes effect receipts.
They exercise simultaneous proposals under a fixed commit clock, process exit
after a durable claim and a fresh process restart, response loss, exact readback,
all-project recovery, durable budget/deadline exhaustion, owner/pause/guard gates,
and an executable CLI. They establish local adapter execution and CAS behavior;
they do not claim host scheduler integration. Owner-paused live automations were
never enabled or run while implementing this contract.
