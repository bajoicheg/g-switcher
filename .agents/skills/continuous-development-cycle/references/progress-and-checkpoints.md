# Progress and checkpoints

## Interactive progress contract

Long-running work must remain visibly alive to the user without turning the chat into a terminal log.

Send a concise progress update when any of these occurs:

- orchestration starts and the immediate plan is known;
- phase changes materially (recovery → implementation → validation → release);
- a durable commit/SHA becomes the new candidate;
- important compute/CI evidence arrives;
- an unexpected defect or blocker is discovered;
- a fallback/backend/executor switch happens;
- several minutes of otherwise silent work would reasonably look stalled;
- work reaches a terminal state.

A good update states: **what changed, current evidence/state, and next action**.

Do not spam every shell command, tool call, polling request, or trivial file edit.

## Durable checkpoint

The checkpoint is for machine/repository recovery, not chat presentation. A v3 checkpoint should record at minimum:

- repository identity and branch;
- reconciled policy revision/digest and durable operation intent/key when external work exists;
- observation timestamp;
- orchestration origin;
- active specification/change and task;
- phase;
- implementation/candidate SHA;
- last trustworthy GREEN SHA and evidence reference;
- active/last CI or compute reference, including environment ID, request/comment ID and actual task ID/URL for Codex;
- release candidate/version when relevant;
- blocker, if any;
- one concrete next action.

Remote repository facts override a stale checkpoint.

Update the checkpoint after meaningful RED/GREEN transitions, failed-CI diagnosis, task closure, release transitions, executor/backend switches, migration reconciliation, and before forced runtime exit.

Never leave only "waiting for CI". Record exact SHA and run/job reference; while the session remains alive, poll the actual provider to terminal state.

Bound polling by `references/bounded-recovery.md` and the task/wake ledger. Save phase start, last successful observation and retry timing; do not reset a deadline on each wake. Preserve enough budget for checkpoint/handoff before starting another poll or agent.

For an in-flight exact-SHA task, keep the source branch stable. If committing the status file would move its HEAD, put the same checkpoint fields and explicit lease/handoff state in a durable PR coordination comment and reconcile the file after terminal state. An environment save, request submission or setup spinner must never be reported as test execution or success.

Validate state with `scripts/validate_checkpoint.py` against the current validated adapter. A template/null digest permits recovery only. Unknown submissions retain their operation reference even when no actual task ID was received; follow `references/external-operations.md`.

Skill 2.3 optionally adds `control` pointers to the independently retrievable ownership record/revision, executor UUID/generation, budget ledger, recovery snapshot and external wait state. Null is unresolved. Structural validation proves neither liveness nor permission; retrieve actual records and match every binding using `references/orchestration-controls.md`. Keep actual current instructions in each recovery read set, even when a fresh matching probe allows unchanged long specifications or logs to be skipped.

## Commitment closure and visible continuity

An invocation that has accepted or announced a concrete runnable next action has
a **continuation commitment**. It must not finish on tool discovery, backend
selection, a status lookup, lease acquisition, or an unchanged observation.
Before final response it must produce one of: meaningful durable progress,
durably bound external work, or a durable explicit blocker/handoff. When a
preferred tool/backend is absent, try the next authorized fallback immediately;
if none exists, checkpoint that exact absence as the blocker and release.

For interactive foreground sessions, `progress.anti_silence_minutes` is a
presentation deadline: substantial ongoing work should produce a concise
user-visible update before that interval elapses. This is independent of the
meaningful-progress clock used by watchdog health. User-visible narration never
substitutes for commits, evidence, external task identity, or a blocker.

## Release-consistent handoff

Do not publish a final source checkpoint that claims `active_executor` or
`lease_state: active` when the same invocation is about to release ownership
before its final response. After shared writes are drained and no unresolved
guard requires ownership, write the final handoff checkpoint in the intended
post-release shape: `active_executor: none`, `lease_state: released`, null
heartbeat/expiry/wait fields, and a precise next action. The actual CAS release
must be the next ownership side effect.

If that release fails or live control state changes, do not return: repair the
checkpoint/control record to the observed state or reconcile ownership first.
When an in-flight guarded source HEAD cannot move, place the equivalent final
handoff state on the coordination ref and explicitly mark the source checkpoint
stale until it can be reconciled. Live coordination remains authoritative.

