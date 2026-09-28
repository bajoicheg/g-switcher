# Managed executor pool

CDC 2.11.0 adds a managed executor pool above the CDC 2.10.2 worktree and single-integrator controls. It is intentionally analogous to Work-style subagents without pretending that every runtime can launch independent workers.

## Parent authority and bounded delegation

The parent invocation remains the CDC orchestrator for the authorized change. It owns task decomposition, backend selection within existing policy, attempt/retry decisions, result acceptance, integration routing and terminal-state evaluation.

A child executor receives only the task contract already authorized for it. It never inherits shared-branch write, merge, release, scope-expansion, scheduler-mutation or user-approval authority. Worker output is evidence for the parent/integrator; it is not an integration decision.

The pool is bounded by an explicit maximum parallelism and by runtime/cost budgets. Do not fan out work merely because concurrency is available. Prefer independent tasks whose expected wall-clock benefit exceeds delegation and integration overhead.

## Capability-gated execution and truthful fallback

Actual parallel worker launch is capability-gated. Work, Codex or another orchestration backend may execute multiple pool tasks concurrently only when the current runtime actually exposes that capability and higher-priority policy permits it.

When worker launch is unavailable, execute the **same managed pool plan** through deterministic sequential fallback. Preserve task identity, dependencies, write sets, expected outputs/evidence and attempt lineage. Serialization may change timing and dispatch order only; it must not silently drop requirements or replace the planned evidence.

Never fabricate subagents, worker heartbeats, parallel start times or worker results. A runtime that cannot launch workers reports sequential fallback explicitly.

Already-authorized pool tasks do not require a fresh user approval for every child launch when runtime and project policy allow delegation. This removes conversational approval loops; it does not create new scope or authority.

## Isolation and one integration point

Every writer is pinned to an exact base SHA and an isolated branch/worktree. Writer contracts carry portable, case-folded Unicode-normalized write claims. Read-only and review executors carry no write claim.

Independent non-overlapping writer tasks may run together. Overlapping portable write sets are serialized or replanned before dispatch. Workers never write the shared product/integration branch.

One integrator remains the only shared-branch writer. It independently checks result identity, exact base/ancestry, changed-path containment, required evidence and fresh shared HEAD before accepting an unintegrated worker result.

## Durable pool state and launch CAS

The pool state is shared coordination state, not an in-memory convenience object. Production execution uses `scripts/managed_executor_store.py` (or an equivalent durable compare-and-swap store with the same fail-closed contract) on a dedicated coordination ref that is portable-isolated from product, integration and worker branches.

Dispatch identifies eligible work but **does not authorize a launch**. Before a worker starts, the parent must atomically persist the exact task ID, attempt ID and unique reservation token against the current durable store revision. Only the successful compare-and-swap winner receives `launch_allowed=true`. A stale sibling dispatcher, replayed reservation or failed CAS has no worker-launch authority.

Calling the pure in-memory `queue_task()` transition without subsequently winning durable CAS is test/planning state only and must never start a real executor. This invariant applies equally to foreground chat, watchdog, Work/Codex workers and retries.

## Durable attempts and results

Each task attempt is durable and observable with explicit identity and lifecycle:

`planned -> queued -> running -> succeeded | failed | cancelled | stale`.

A heartbeat requires a new observable activity reference. Polling the same provider state or merely advancing time is not activity.

A retry creates a new attempt identity and points to its predecessor. Failure, cancellation or staleness never overwrites the old attempt evidence. Two active attempts for the same pool task are a duplicate-launch fault and must be reconciled before another start.

A successful writer result remains `integrated=false` until the single integrator accepts it. It binds the exact pool/task/attempt/base, result commit, changed paths and evidence refs. Changed paths outside the declared portable write set fail closed.

Failure of one worker does not cancel unrelated independent work. Other safe tasks continue while the failed required task is retried, replanned or explicitly dispositioned.

## Portable result handoff

Direct worker push is a transport capability, not a correctness requirement. If an isolated worker finishes valid work but cannot push its assigned branch, preserve the completed attempt and return a **content-addressed result handoff** bound to the exact base SHA, task/attempt/parent/executor identity, assigned branch, changed-path manifest and validation evidence.

Prefer a Git bundle when exact result-commit identity can be preserved; a content-addressed unified diff may be used when the parent must reconstruct a new commit. The parent/integrator authenticates the artifact before publication and independently verifies the published branch head, base-to-result ancestry and changed paths afterward.

Missing worker push capability must never cause silent work loss, fabricated remote success or blind re-execution. The publication fallback sets `requires_reexecution=false` and grants no product-write, force-push, merge, release, scope or scheduler authority by itself.

## Terminal-state relationship

Pool progress is not terminal progress. The parent cannot return COMPLETE while any required task is runnable, queued or running, while a required failed/stale task still needs recovery, or while a successful required result remains unintegrated.

Optional work may be omitted only through an explicit pool decision; already-running optional work must be drained or cancelled before the pool itself can close.

A worker completing one task, a parent reporting a milestone, or a validation subset becoming GREEN does not end the CDC invocation. The parent immediately continues observe -> reconcile -> choose-next -> act until the project-level terminal gate accepts a real boundary.

## Release evidence

CDC 2.11.0 release evidence must prove at minimum:

- two independent tasks can be active concurrently on a capable backend;
- the same pool plan falls back deterministically to sequential execution when capability is absent;
- duplicate task attempts are rejected or reconciled;
- worker failure does not stop unrelated independent tasks;
- required runnable/running or unintegrated-success state prevents parent terminal completion;
- isolated writer results cannot escape their declared portable write sets;
- all managed-pool outputs keep shared-branch, merge, release, scope, scheduler and user-approval authority false.


## Durable publication and retry disposition

A worker result is not durably published merely because the assigned local branch points at its commit. Final publication proof queries the configured authoritative **remote** exact branch ref and requires it to equal the published commit. Remote-tracking cache, local branch state and intended push are not publication evidence.

Content-addressed Git bundles are verified from an immutable private snapshot of the bytes already authenticated by digest. Never reopen the mutable source artifact pathname after authentication.

Optional tasks also require explicit lifecycle disposition. A planned or recoverable optional task blocks pool terminal state until it is either executed or explicitly omitted. An active optional task must drain/cancel, and a successful optional result must integrate or be explicitly discarded.

Retries reserve only **remaining** task runtime/cost budget after prior attempts' consumption. Historical consumption remains charged once; dispatch reserves only unresolved liability.


### Remote publication and retry-budget hardening

A result is not durably published merely because a matching local `refs/heads/*` exists. Publication proof must bind an exact configured authoritative remote and verify the remote branch ref equals the accepted commit. For content artifacts, authenticated bytes are immutable verification input: bundle verification uses a private snapshot of the bytes already covered by the digest, never a mutable pathname reopened later.

Optional work also requires explicit disposition. A planned or recoverable optional task blocks pool terminal state until it is either executed or explicitly marked omitted; a successful optional result blocks terminal state until integration or explicit discard.

Retry reservation uses remaining per-task budget, not the original maximum. Prior attempt consumption stays in the aggregate ledger while the next retry reserves only `max - consumed` for runtime and cost.

## Final trust-boundary closure

The production pool/state contract binds one authoritative coordination ref. A pure in-memory queue transition is planning only; durable queue reservation is still not physical start authority. Start authority is one-shot and exists only after an atomic durable queued-to-running CAS wins for the exact task, attempt and reservation token.

Writer scope validation is historical: inspect every commit introduced after the exact base (or require a separately validated sanitized single commit). The union of all touched paths, including paths later restored, is the manifest checked against the portable write claim.

Required task dependency closure must contain only required tasks. Optional omission/discard cannot be a prerequisite escape hatch.

Publication remote identity comes from trusted parent policy and is cryptographically bound. Validate one identical fetch/push endpoint and compare its fingerprint to the expected identity before accepting the authoritative remote ref; never expose the underlying URL in diagnostics.
