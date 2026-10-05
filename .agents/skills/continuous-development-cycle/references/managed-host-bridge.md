# Managed host bridge

CDC 2.11.4 adds a transport-neutral host surface around the existing package-owned managed executor and managed terminal hold.

The safety rule from 2.11.3 does not change: ordinary ChatGPT/Work/Codex/watchdog/API callers do not receive a persistent execution lease or a serializable managed-terminal capability. A host invokes `scripts/managed_host_bridge.py`; the package starts a real `ManagedExecutorRuntime` supervisor, acquires the exact project lease through its non-serializable capability, and returns only a durable opaque handle.

## Host contract

The initial local transport exposes four JSON actions:

- `start` — validate exact repo/remote/source HEAD and pool plan; create a gated isolated worker; acquire the managed project lease; only then release the worker gate and return `managed-host-handle/v1`. An exact repeated request returns the same durable handle, including after publication; conflicting immutable request context is rejected. An unconsumed queued reservation resumes through the runtime without creating a new attempt.
- `observe` — observe the exact task/attempt/launch and live lease without launching anything.
- `cancel` — request cancellation of that exact worker. Cancellation acknowledgement is not release; call `finish` once the exact worker reaches the managed terminal hold.
- `finish` — validate the checkpoint and required output/evidence references before recovery, lease mutation or publication. For a successful writer in `awaiting_release`, verify exact branch/result ancestry and portable write scope, conditionally publish the result to the exact observed source HEAD using a durable publication journal, transactionally finalize/release the managed lease, wait for supervisor quiescence, accept/integrate the pool result, and run the exact release-receipt final-response gate. Failed, cancelled and timed-out workers use the same transactional release without publishing or accepting a successful result; their response reports `scope_complete=false` and a resumable BLOCKED boundary.

A ChatGPT plugin, Work adapter, scheduler adapter or other host service can wrap these same actions. The package contains no claim that such a host transport is installed merely because the script exists.

## Worker gate

`start` does not race a fast worker against lease acquisition. The runtime first launches a package-owned worker-gate process. That process remains live while `ManagedExecutorRuntime.acquire_execution_lease()` issues and revalidates the managed-terminal capability. The real task argv is released only after durable ownership has been persisted. If acquisition fails, the gate aborts without executing the task.

An initially unknown launch, or a controller crash after launch before its reply is saved, is observed through its exact consumed attempt; when that same gated supervisor becomes live, recovery rechecks the source HEAD and resumes managed lease acquisition without launching another process.

The gate state and runtime journals are outside the product tree. A controller restart uses the durable handle plus the runtime's terminal-hold markers to recover exact ownership; it never creates a replacement launch.

## Publication

`remote` identifies the source publication endpoint. To keep operational state in a private repository, supply both `coordination_remote` (a separately configured Git remote) and `source_remote_id` (the pinned source endpoint identity). The pool plan's `coordination_store_id` pins the private endpoint. Lease, pool and publication-attempt refs use only that coordination remote; source HEAD checks and exact-head publication use only `remote`. Both identities are immutable handle context and are checked before start, recovery and publication. Supplying only one of the new fields is rejected. Existing single-remote requests and durable sessions retain their previous binding.

The host must verify actual Git write authorization for both repositories before execution. Account-level repository permission metadata does not prove that a Codespace credential has the required scope. Additional repository access must be explicitly granted by the owner; the bridge neither widens permissions nor creates credentials.

The v1 bridge is intentionally a single-writer fast-forward path. The worker changes only its isolated assigned branch/worktree. `finish` derives the result from that exact branch, reuses the managed-pool full-history write-set verifier, checks a fresh managed lease, and invokes `GitLaneIntegrationPublisher` with a dedicated GitDocumentStore publication-attempt journal. Only `conditional_update=true` evidence is accepted. A same-byte readback without the original durable publication attempt is not enough.

The bridge then runs `active -> draining -> checkpointed -> reconciled -> ready -> release` and records the immutable `execution-release-receipt/v1`. The worker supervisor does not become quiescent before the release marker exists. If the controller dies after the authoritative release CAS, recovery repairs the supervisor marker from exact lease history and completes pool acceptance before reporting completion.

## Host authorization

`LocalCommandBackend` remains cooperative execution, not a sandbox. The bridge does not turn model text into privileged shell authority by itself. A production host must apply its normal user authorization, repository scope, command policy, secret policy and plugin/tool permission checks before it supplies argv to `start`.

The bridge grants no Fleet leadership, scheduler authority, scope expansion, destructive permission or release permission beyond the task and repository authorities already provided by the caller's CDC plan/policy.
