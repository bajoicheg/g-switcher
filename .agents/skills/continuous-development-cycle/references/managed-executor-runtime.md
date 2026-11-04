# Managed executor runtime

`scripts/managed_executor_runtime.py` connects the managed pool to actual effects.
It is a Python adapter, with a real `local_command` backend and a host-backend
interface. It embeds no ChatGPT Work, Codex, scheduler, or provider API. The caller
still owns policy, execution lease, external operation guards, budget admission,
and the sole integrator's authority. Nothing here re-enables an owner-paused
scheduler or grants shared-branch, merge, release, or scope authority.

## Start, observe, and continue

Instantiate `ManagedExecutorRuntime(plan, store, repo_root, backend)` with the
validated plan, a `GitManagedExecutorStore`, and
`LocalCommandBackend(durable_journal_directory)`. Keep the journal outside the
publishable product tree. Local writer worktree paths from the plan resolve
relative to the repository root's parent; non-writers receive detached worktrees
inside their attempt journal. The exact base commit must be available locally.
Task backend preferences must contain `local_command`.

```python
from managed_executor_runtime import ManagedExecutorRuntime, LocalCommandBackend
from managed_executor_store import GitManagedExecutorStore
import managed_executor_pool as pool

store = GitManagedExecutorStore(
    repo_root, "origin", plan["coordination_ref"], plan,
    protected_refs=["refs/heads/integration"],
)
revision, state = store.read()
if state is None:
    store.compare_and_swap(None, pool.initial_state(plan, parallel_capable=True))
runtime = ManagedExecutorRuntime(
    plan, store, repo_root, LocalCommandBackend(journal_directory),
)
revision, state = store.read()
# The caller picks a real authorized task from pool.dispatch(plan, state).
receipt = runtime.start(
    revision, task_id, attempt_id, reservation_token=unique_reservation,
    argv=[python_executable, "worker.py", "--task", task_id],
)
observation = runtime.observe(task_id, attempt_id)
```

Use absolute paths for executables/scripts not present at the worker's exact
Git base. Commands are argument arrays passed without `shell=True`. Workers must
commit their scoped changes and leave the worktree clean. This is cooperative
isolation, not a hostile-code sandbox: Git worktrees share repository metadata,
and commands retain the invoking user's privileges.

The initialized durable pool state pins a canonical digest of the entire plan, including write scope, backend and budgets. Reads and every queue/launch transition reject plan drift, including after controller reconstruction. Existing pool plans are immutable: authorized replanning must preserve the old attempt history and establish a separately identified plan/store; never rewrite the digest of live state. Legacy candidate state without the digest fails closed and needs explicit quiescent migration.

`start` first reserves the queued task with CAS, then consumes its launch claim
with a second CAS. Only the successful launch-claim caller invokes the backend.
The pool enforces configured parallel capacity, sequential fallback, dependencies,
write-set exclusion, and remaining budget. Start every eligible independent task
using a fresh store revision; observation and acceptance of one failed worker
must not stop the caller from dispatching unrelated eligible work.

`start_queued(revision, task_id, attempt_id, reservation_token=..., argv=[...])`
resumes an existing **queued** reservation through the same one-shot claim CAS.
It is useful after a controller stopped between queue and claim. It cannot resume
an already claimed/running task as a new effect. Duplicate/stale CAS calls fail
before invoking the backend; a local exclusive launch marker also rejects direct
backend replay.

A stale CAS requires a fresh read and reconciliation. Any exception or lost reply
after claiming launch is uncertain, even if no receipt exists. Call `observe` for
that exact attempt; never call `start` or the backend again as a blind retry.

## Process observations and durable receipts

The local backend requires Linux `/proc` and `PR_SET_CHILD_SUBREAPER`. A detached
supervisor creates the worktree, spawns the command, observes real process state,
and owns timeout/cancellation independently of the foreground controller. Its
receipt binds pool/change/parent/task/attempt/executor, exact base/branch/worktree,
coordination endpoint/ref, launch claim revision/token, a digest of the full plan
(including write scope, evidence requirements and budgets), and a digest of the exact
request. It records both namespace and `/proc` PIDs, process birth time and boot
identity so stale PIDs are not treated as the original supervisor.

The supervisor reaps adopted descendants, including descendants that create a
new session. Root process exit is insufficient. `quiescent=true` is emitted only
after no children remain; cancellation/timeout sends TERM then KILL while
continuing observation. `cancel(task_id, attempt_id)` requests cancellation and
returns an observation. Continue observing until quiescence; a cancellation
request or timeout alone does not release the pool slot or write claim.

Each attempt directory preserves the exact `request.json`, one-shot
`launch.lock`, initial `backend-receipt.json`, live/final `receipt.json`, and
stdout/stderr/supervisor logs. Successful validated results add `attempt.json`
and `result.json`; verified integration adds `integration.json`. Failed,
cancelled, and timed-out receipts and the pool's attempt history remain intact.
The pool changes to failed/cancelled only after a matching quiescent observation.
A successful process remains running in the pool until result acceptance.

Timeout covers the local supervised preparation/execution interval. Deadline and cancellation are checked again after worktree preparation, before creating the worker process; any preparation descendants still pass the quiescence loop. The receipt
retains full observed `elapsed_seconds`, including termination overhead.
`runtime_seconds` is capped at the admitted remaining task budget for the pool's
bounded ledger; a timed-out attempt therefore consumes its entire remaining
runtime allowance and is not eligible for another run. Exhausted runtime or cost rejects retry, dispatch and even an older queued launch before any backend effect; unrelated tasks retain eligibility. Local execution
has no inferred provider charge; callers must supply actual cost accounting for
metered host execution.

A missing receipt, missing/reused supervisor PID, changed boot, killed supervisor,
or unreadable process evidence is **unknown**, never successful or quiescent.
Unknown attempts remain running and keep claims reserved. An independently
verified external recovery may reconcile the old process tree and use the
existing pool recovery APIs; this adapter does not guess quiescence or reset
unknown attempts. Preserve the same journal across controller restart. Moving to
another host without the journal/process evidence is not a fresh launch grant.
A host that tears down all processes at invocation exit cannot promise persistent
local execution; use its real external execution service instead.

## Accept and integrate results

Call `accept(task_id, attempt_id, result_commit=..., output_refs=[...],
evidence_refs=[...], cost_units=...)` after a quiescent successful observation and
after obtaining real required validation evidence. References are evidence
bindings, not a substitute for actually running validation. Acceptance checks
exact assignment, exact base and assigned branch head, a clean worktree, expected
outputs/evidence, real Git ancestry, and every touched path across the full
history. A transient out-of-scope change later reverted is still rejected.
Non-writers cannot hide a committed change behind a null result commit.
Acceptance persists the result and CAS-updates the pool to **unintegrated**
success. It never pushes, merges, or finalizes the parent.

The externally authorized integrator publishes the worker branch, validates and
integrates the result through the existing integration/review gates, then
publishes the integration branch. For commit-preserving writer integration call:

```python
runtime.record_integration(
    task_id, accepted["result_ref"], integrator_id=plan["integrator_id"],
    handoff=handoff, proof=publication_proof,
    integration_commit=exact_integration_sha,
    integration_ref="refs/heads/integration", remote="origin",
    trusted_repository=publication_repository,
    trusted_remote_id=expected_publication_remote_identity,
)
```

This verifies the existing handoff/publication proof contract against the live
remote, exact accepted result binding, result ancestry in the integration commit,
and exact local and published integration ref heads, then calls the pool's
`mark_integrated` through CAS. It performs no push or merge. Non-writer acceptance,
rebased/cherry-picked artifact integration, optional disposition, and explicit
retry/replanning continue through the external integrator's existing pool APIs;
this minimal method does not invent integration evidence for them. Do not clean
or reuse failed worktrees/branches until the old attempt is proven quiescent and
normal cleanup/retry authority permits it.

## Parent terminal gate

Call `runtime.evaluate_parent(continuity_state, now_utc=...)` immediately before
closure. It reads fresh pool state and invokes the real
`execution_continuity.evaluate`, including its terminal-state/blocker evidence
checks. The parent invocation must match the plan. Only
`final_response_allowed=true` permits the terminal path. Required planned,
queued, running, recoverable or successful unintegrated tasks block completion;
optional tasks require their normal explicit disposition. Pool completion alone
cannot replace checkpoint, lease-release or terminal evidence. This cooperative
gate cannot intercept ChatGPT's final-response channel. Runtime exhaustion or an
unknown worker requires durable continuation under the outer lifecycle; it must
not be described as project COMPLETE.

## Host backend interface

Supply a backend with `name`, plus exactly these effect/observation methods, and
pass an explicit durable `journal_root` to `ManagedExecutorRuntime`:

| Method | Contract |
| --- | --- |
| `start(request)` | Execute the authorized effect once, then return an observation. Never infer another launch from a saved claim. |
| `observe(request, receipt)` | Query the exact existing effect, using the durable initial receipt/handle or exact request identity. `receipt` may be null after a crash. Never launch during observation. |
| `cancel(request, receipt)` | Request cancellation of that exact effect. Return an observation; do not equate cancellation acknowledgement with quiescence. |

The controller owns durable request/receipt storage independently of the backend.
The request contains exact identity, claim, argument array, repository/cwd,
journal directory and timeout. The backend may include its opaque provider handle
in the returned receipt; the initial receipt is persisted and supplied on later
observe/cancel calls. When the initial receipt was lost, recover only by a real
provider query bound to the exact request; otherwise return unknown.

Observations use `managed-executor-observation/v1` with matching `identity`,
`claim`, `request_ref` and `launch_id` (both digests of the canonical request).
Active states are `starting`/`running` with `quiescent=false`; terminal states are
`succeeded`/`failed`/`cancelled`/`timed_out` with independently proved
`quiescent=true`. Supply real UTC creation/start/finish timestamps, exit/failure
facts and measured runtime; successful acceptance uses those timestamps.
`unknown` needs the matching identity, `quiescent=false`, and a reason. Real host
capability, cost, external guards and launch authority remain the host's concern.
No native Work or Codex tool availability is implied by implementing this Python
interface.

## Verification

Run `python -B -m unittest discover -s tests -p test_managed_executor_runtime.py -v`
from the package. The tests create real Git repositories/remotes and subprocesses;
coverage includes actual overlap, sequential capacity, independent failure,
queued/stale/duplicate starts, missing receipts, controller exit, killed
supervisors, detached TERM-ignoring descendants, dirty/transient-scope results,
and publication/integration plus the parent terminal gate. Run the whole package
suite and package validator before integration.
