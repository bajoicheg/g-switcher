# Watchdog, recovery, and repository migration

## Watchdog model

A watchdog is a best-effort wake-up mechanism. It executes this same development cycle from durable state.

Every wake:

1. reads current repository instructions, adapter and compact checkpoint; verifies a fresh recovery probe before skipping unchanged long spec/task bodies;
2. discovers actual repository identity, branch, HEAD, PR, CI, and release state;
3. validates policy compatibility and checkpoint binding, then reconciles stale data;
4. applies concurrency and budget guards;
5. resumes the next safe action;
6. continues until COMPLETE, BLOCKED, or a runtime limit.

An explicit kick bypasses only an idle threshold. It never bypasses concurrency, destructive-action, validation, release, or budget safeguards.

Watchdog subagent policy is inherited from the runtime that executes the wake: ordinary chat means no subagents; Work/Codex orchestration explicitly enables useful delegation by default with adaptive effort and no per-launch approval, subject to higher-priority restrictions. Prefer configured Codex Compute for eligible candidate checks and follow `codex-compute.md` for setup, task binding and fallback.

## Six-signal watchdog health vector

Do not reduce watchdog health to one timestamp, spinner or `enabled` flag. Build
a fresh `watchdog-health-probe/v1` with exactly six independent signals and
classify it with `scripts/watchdog_health.py`:

| Signal | States | Meaning |
|---|---|---|
| scheduler | `ok / drift / overdue / unknown` | desired vs observed canonical recurring task and expected delivery cadence |
| chat | `active / archived / missing / unknown` | exact bound control/delivery conversation availability |
| invocation | `idle / running / completed / unknown` | actual execution state of the exact watchdog invocation, not an inferred spinner |
| lease | `released / fresh / stale / expired / unknown` | live coordination owner/generation and heartbeat/TTL state |
| external | `none / queued / running / unknown / terminal_unreconciled / terminal_reconciled` | durable guard plus provider task state |
| progress | `fresh / stale / none / unknown` | meaningful repository/provider/checkpoint progress, excluding polling and heartbeat-only writes |

Projects define their scheduler-overdue and meaningful-progress windows in the
project runbook. Never invent freshness from missing timestamps. A heartbeat,
poll, accepted request, scheduler readback or unchanged checkpoint is not
meaningful product progress.

The classifier returns `HEALTHY`, `DEGRADED`, `STALLED`, `BLOCKED`, or
`RECOVERY_REQUIRED`, a reason list, a primary recovery action and a stable
fingerprint. The summary is **diagnostic only**. All side-effect booleans remain
false: health never grants takeover, product writes, external starts, scheduler
mutation, budget restoration, merge or release authority. Apply the normal
ownership/external/budget gates after health diagnosis.

Important contradictions are first-class incidents. Examples:
- completed/idle invocation plus an owned lease => orphan-lease recovery candidate;
- desired-enabled scheduler plus observed-disabled => scheduler drift;
- archived/missing bound chat => chat-dependency recovery;
- active external work => `BLOCKED`/observe rather than a competing start;
- no meaningful progress while no legitimate external wait exists => `STALLED`;
- incomplete observations => `DEGRADED`, never fabricated health.

Persist the probe/assessment on an authorized coordination path when it improves
handoff or diagnosis, without moving a guarded product HEAD. Compare the
assessment fingerprint to the previous snapshot: unchanged health may stay quiet;
a changed overall state, signal, blocker, recovery action, scheduler/chat drift or
progress freshness is meaningful. `HEALTHY` means the watchdog control path is
coherent, not that product validation/release gates are complete.

## Silent-dead-end recovery

A completed watchdog invocation with a runnable next action, no legitimate
external wait/guard and no real blocker must not be treated as healthy merely
because the scheduler ran and the lease was released. Tool discovery, reading
status, or deciding which backend to use is not meaningful progress. The wake
must either execute the runnable action, switch to an authorized fallback in the
same invocation, or persist an explicit blocker/handoff.

When diagnosing “I see no work”, distinguish:
- **execution visibility** — which chat/destination receives watchdog reports;
- **scheduler delivery** — whether the canonical recurring invocation actually ran;
- **meaningful development progress** — commits/evidence/task transitions;
- **ownership state** — live coordination, not stale checkpoint liveness fields.

A quiet notification policy may hide a successful wake from the foreground chat;
it must never be used as evidence that development is active. Conversely, a
fresh scheduler timestamp with no meaningful progress and a runnable next action
eventually becomes stale under the project progress threshold.

## Scheduler lifecycle and drift

Keep three independent states: desired scheduler state authorized by the user,
observed scheduler state, and execution eligibility for the current wake.
BLOCKED, an active writer, an external guard, an exhausted budget, a runtime
limit, unchanged work, quiet notifications, or completion of one task ends or
limits this wake; none authorizes pausing/deleting the recurring automation.
Use the lease to prevent competing writers; never pause the scheduler for manual
work. Disabling requires explicit current user authorization for that automation
or an explicit previously authorized stop condition that is actually satisfied.

Resolve the canonical automation ID before an update; never resume historical
duplicates or completed one-shot kicks. Honor a later verified user pause,
including a verified UI action, over older repository enabled:true. Conversely,
observed enabled:false with unknown actor does not prove a user pause. Old
checkpoint flags do not revoke newer user authorization.

Normal wakes do not mutate scheduler state or reschedule themselves. During an
explicitly authorized repair, inspect the latest user decision and actual task,
update only requested fields, preserve cadence/timezone/triggers, then read back.
A scheduler tool's unavailable audit remains unavailable: record actor/cause as
unknown, do not manufacture attribution or assume platform auto-disable. Do not
fight a known user pause or repeatedly toggle against an unexplained concurrent
writer. Report recurrent drift for diagnosis.

Keep a small scheduler observation/audit record on an authorized durable path:
canonical ID, desired state and authorization reference, observed_at, enabled,
schedule/timezone, last_run_time, update time, before/after for a change,
reason and actor (unknown if not exposed), result/readback, next action. Do not
move an in-flight source HEAD or take over a writer merely to record it.
A new scheduler-state drift is a changed blocker even when the product blocker
is unchanged; do not suppress it as a duplicate notification.

Report enabled, requested run, observed execution and product progress separately.
An enabled flag or accepted run request is not execution evidence. A null
next_run_time alone is not proof of a broken schedule. A disabled watchdog cannot
repair itself; repair during an authorized foreground/status session. Do not
promise self-healing or add a second watchdog without user authorization.

## Chat dependencies: archive prevention and recovery

Treat a chat-bound watchdog's conversation as an operational dependency. Track
four separate states: desired scheduler state, observed scheduler state,
conversation availability, and execution eligibility. An archived chat is a
recovery suspect; it is not proof of a platform-wide cause or a user stop order.
If the owner accepts it as the incident's working cause, record that decision
separately from observed facts and unavailable provider audit.

### Prevent accidental archiving

Maintain a project watchdog binding record outside disposable chat history:
canonical automation ID; conversation ID/observed URL from live task metadata;
other verified control/delivery chat dependencies and their roles; desired state
and authorization; last verification time; archive state (`active`, `archived`,
`missing`, or `unknown`); evidence reference; latest completed-run/report reference;
recovery state and one next action. Use a separate project runbook/JSON record,
not unsupported fields in the strict adapter. An unknown value stays unknown.

Before archiving, deleting, moving, or bulk-cleaning chats, inventory live
automations and compare exact conversation IDs. Exclude operational dependencies
and chats with unresolved executor/provider work. Age, a completed product slice,
quiet notifications, or a paused flag with unknown actor does not remove protection.
Mark protected chats clearly in the project runbook; a pin or title is only a
visual aid, not a technical lock. Do not claim the platform prevents user archiving.
Retire/migrate a protected chat only after an explicit user decision and verified
replacement delivery; preserve the old-to-new mapping and avoid two active tasks.

During each foreground project status/resume, cheaply reconcile the task's live
conversation binding. Inspect actual chat availability after binding changes,
chat cleanup, or failed/missing/stale runs; prioritize this before another run
request or a compute retry. Ordinary wakes read/report drift and do not repair
the scheduler themselves. A disabled or inaccessible watchdog needs foreground
recovery; it cannot guarantee its own recovery.

### Recover the same watchdog

1. Resolve the canonical task and its actual conversation ID, latest user stop
   decision, current run/owner/guard and freshest result. Preserve schedule,
   timezone, triggers, prompt, desired state and before/after evidence. A spinner
   or stale `last_run_time` alone is inconclusive; compare Scheduled results and
   concrete repository/provider activity. Diagnose an overdue run using existing
   phase deadlines, retaining all guards.
2. Open the exact linked chat via supported tools/UI. If archived and recovery is
   authorized, unarchive only that dependency; read back its active/access state.
   If missing, inaccessible, or archive state cannot be inspected, report
   `chat_dependency_blocked` with the exact ID and required action. Do not invent
   a chat, rebind a task, change account, or create a replacement silently.
3. If no later explicit stop overrides recovery authorization, resume the same
   canonical task when needed; patch only required fields and read back. If a
   watchdog run is already active or uncertain, observe/reconcile it first.
   Otherwise use the next scheduled run; request at most one Run now only when
   the user has authorized an immediate run for this repair. This does not authorize another Compute/Actions start,
   clear an external guard, or transfer branch ownership.
4. Mark recovery `pending_verification` until a post-repair run completes, its
   fresh result is visible at the intended destination, the chat is accessible,
   and the recurring task remains enabled on the preserved schedule. A completed
   observer/BLOCKED wake can verify delivery; product GREEN is a separate gate.
   Enabled, an accepted request, or an old report is insufficient.
5. If the next run fails or the task pauses again, record the new error/timestamps
   and revisit the working cause; stop repeated toggling or re-submission. Keep
   one resumable next action, not another watchdog. Preserve raw facts when the
   provider exposes no actor/reason. Unarchive success alone is not scheduler
   recovery success.

Persist observations through an authorized coordination path without moving a
guarded product HEAD. During long waits, show separately: chat access, task
enabled, actual run state, fresh delivery, and product progress. Preserve polling
backoff and phase deadlines; do not replace them with a fixed poll-count ceiling.

## Execution lease and heartbeat

Use the conditional ownership or designated single-writer protocol in `references/execution-ownership.md`. Checkpoint timestamps alone do not prevent concurrent writers or prove background activity. Apply the complete sequence in `references/orchestration-controls.md`.

Default reusable policy:

- `default_ttl_minutes: 20`;
- `heartbeat_fresh_minutes: 10`;
- renew only after a new observable owner activity reference such as a commit/checkpoint, compute request, or newly observed provider event; repeated polling of the same state is not activity;
- never renew merely because time passed, a chat is open, or an executor was previously active;
- before remote compute/CI waits, persist `waiting_external`, exact candidate SHA, and the external task/comment/run identifier;
- while that exact external work is actually queued/in-progress, it remains a concurrency guard even if the lease TTL expires;
- a terminal external result does not renew owner activity; stale heartbeat or expired TTL requests diagnosis, never takeover by itself. Require explicit release or verified previous-executor quiescence, including pending writes and provider calls;
- before a normal invocation returns its final response while it still owns the lease, drain shared writes, retain any unresolved external guard, explicitly release ownership, and persist one exact next action; a completed invocation must not leave a lease that merely waits for TTL;
- on foreground recovery or an explicit kick, actively resolve the live owner's invocation state. Independently verified completion of the exact owning invocation plus drained pending effects qualifies as `executor_stopped` quiescence even if its last heartbeat is still fresh or TTL has not expired. If the owner invocation cannot be bound and proven finished, remain observer-only;
- explicit kicks bypass the idle guard only; they never bypass a genuinely running/unverified owner, unknown/submitting external work, budget, or validation gates;
- silence, elapsed TTL, stale heartbeat, or scheduler `last_run_time` alone never proves executor completion;
- legacy long leases should be normalized at the next safe checkpoint rather than honored as unconditional locks.

A repository may override the numeric windows, but the semantic distinction between **ownership heartbeat** and **external work state** must remain.

Use `references/bounded-recovery.md` for separate phase deadlines and retry-aware polling. Queue/setup/run timeouts never clear a guard or authorize a replacement. Reserve each attempted poll against the per-wake budget and hand off with exact state when resources run low. A fresh matching recovery snapshot may reduce long-document reads; current instructions, ownership, external state and budget checks are always required.

If a checkpoint commit would move an in-flight request's source HEAD, preserve the exact external binding and lease/handoff fields in a durable PR coordination comment, identifying it as authoritative. Reconcile the checkpoint file after terminal state; retain the SHA actually tested. Read both the checkpoint and current PR coordination on recovery.

## Recovery after interruption

On a fresh session, never assume the previous session, Work run, Codex run, subagent, or scheduler is still alive.

Fetch remote facts. If the repository is ahead of the checkpoint, determine whether movement belongs to the same development lineage. Reconcile known same-cycle commits; stop only when unexplained external movement makes a write unsafe.

## Repository identity and migration

Repository migrations are first-class state changes. Before and after migration verify:

- canonical owner/repository identity;
- visibility/access required by the workflow;
- default branch and working branch;
- actual HEAD lineage;
- active PR destination/source refs;
- workflow/runner availability;
- release/tag state;
- checkpoint adapter remote identity;
- watchdog/scheduler prompts that may contain repository identifiers.

Never continue pushing to an old mirror simply because the local checkout or stale checkpoint still points there.

If source and destination repositories diverged during migration, establish the canonical history and record the reconciliation before further implementation.

## Interrupted submission

A durable `submitting` or `unknown` operation intent is an external guard even when the task ID is missing and lease has expired. Follow `references/external-operations.md`: complete provider lookup, match operation/attempt and actual task binding, and reuse the existing task/outcome. Empty or incomplete lookup never authorizes resubmission. A client timeout is not a terminal provider outcome.
