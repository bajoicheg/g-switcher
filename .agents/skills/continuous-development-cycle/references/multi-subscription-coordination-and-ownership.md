# Multi-subscription coordination and ownership integrity

CDC 2.11.3 allows multiple independent ChatGPT subscriptions/executors to cooperate without making the Fleet control plane active-active.

## Fleet Supervisor leader

Use a dedicated `fleet-supervisor-state/v1` document on an isolated Git CAS ref such as `refs/heads/cdc/fleet-supervisor`. The embedded `execution-lease/v2` is bound to the authoritative Fleet repository and `refs/heads/cdc/fleet`.

Exactly one owner/generation/invocation may be the Fleet side-effect leader. **Only a package-managed execution surface may acquire a new persistent execution-lease/v2 generation.** Chat/Work/Codex/watchdog/API host surfaces that do not expose a package-owned mechanically enforced terminal boundary are observer/orchestrator-only. This prevents an ordinary ChatGPT final channel from ever owning a lease that it could silently abandon. Other subscriptions remain observers/standby Fleet supervisors or dispatch work into managed execution. A Fleet leader never receives project product-write, project takeover, merge, release, scope-expansion, or implicit scheduler authority.

Every Fleet-wide effect is a one-shot durable claim identified by a **deterministic canonical SHA-256 effect ID** derived from kind + target + intent + observed Fleet HEAD, plus exact leader generation/invocation. Callers cannot choose alternate IDs for the same semantic effect. Supported effect classes include Fleet-ref publication, project wake, scheduler repair, and continuation enqueue. Reusing the same effect ID with the same intent observes/reconciles the original claim; reusing it with different intent is a collision. A moved Fleet HEAD requires replanning before a claim. Unknown/submitted effects block leader replacement until reconciled. A standby may perform only evidence-only provider reconciliation against the original effect ID + intent digest: complete terminal/not-found lookup may close the effect, running/unknown observation keeps it pending, and reconciliation never grants submit/replay authority.

Leader replacement never follows TTL alone. Use exact `executor_stopped` evidence plus no unresolved leader effects. The ordinary execution-lease transactional finalization/release contract remains authoritative.

## Truthful liveness

Use `scripts/execution_liveness.py` with independent **fresh** runtime evidence. A historical running observation that exceeds the runtime-observation freshness bound degrades to `unknown` even if the lease was renewed. Lease presence, owner ID, heartbeat age, scheduler timestamps, or TTL do not by themselves prove an executor is active or stopped.

The normalized states are:
- `active`: exact invocation is independently observed running and the lease is fresh;
- `orphaned_recoverable`: exact invocation is independently observed stopped with no pending shared writes, guard, or **unresolved** current-generation submissions; append-only terminal resolutions remove reconciled claims from the pending set without erasing claim history;
- `blocked_unknown_effects`: exact invocation stopped but pending effects require reconciliation;
- `unknown`: runtime identity/liveness is not independently proven;
- `released`: lease has no owner.

Liveness classification is evidence only and never authorizes takeover.

## Final-response boundary

Use `scripts/final_response_gate.py` immediately before a CDC terminal/final response. An invocation that acquired a lease must retain an immutable `execution-release-receipt/v1` from the exact release revision, binding owner/generation/invocation and checkpoint. The current lease's mutable `last_release` is insufficient because a successor generation may overwrite it before the prior chat emits its final response. `execution_lease_v2.release_cas()` performs the authoritative release CAS and returns `execution-release-receipt/v1` bound to the resulting coordination revision; the CLI `release` command emits the same receipt. Before final response, `GitLeaseStore.read_revision(receipt.lease_revision)` must prove that revision is in the authoritative coordination ancestry and that its released `lease.json` exactly matches the receipt. Execution continuity must be in post-release terminal state. Pre-release `ready` evidence is insufficient.

This gate remains the terminal proof for package-managed owners. Host runtimes that cannot expose a mechanically enforceable terminal boundary are **not admitted as lease owners at all**; they may observe/orchestrate only. Thus ordinary ChatGPT cannot bypass the gate by simply skipping it, because it cannot enter the owned path. Managed execution may crash before release, but such a crash is liveness/recovery state, not a successful conversational final response.

## Atomic consumer adoption

Use `scripts/consumer_adoption.py` together with the existing detached migration transaction. Package bytes, consumer lock, adapter, checkpoint, adoption/provenance record, and other required paths are prepared away from the shared source ref. The publication state carries an immutable assembly manifest covering every required path as `{path, object_type, object_sha1}`; its digest is bound into the publication claim and durable attempt journal. Before any publication attempt the publisher verifies every candidate object identity, candidate root tree, exact package subtree, and semantic consumer-lock `version/package_tree/release_ref/release_commit` target binding.

The shared source ref has exactly one publication boundary: an exact expected-head conditional fast-forward to the fully assembled candidate, followed by exact readback. A moved source HEAD replans; an uncertain publication reconciles; package-tree mismatch fails closed. VERSION-only or metadata-only exposure on the shared source ref is never a valid adoption state.

## Multi-subscription pressure invariants

Release evidence must cover two supervisor identities racing from one initial coordination revision, duplicate effect claims, stopped leaders with both clean and unknown-effect states, final-response attempts while a lease remains owned, and interrupted consumer adoption before publication. At most one leader/effect CAS may win, no force update is allowed, and no partial target version may appear on a shared consumer ref.


## Real Fleet scheduler path

The real `fleet_watchdog_runtime.FleetRuntime` is fenced too, not just the standalone leader contract. Any positive effect budget requires a fresh Fleet leader guard. Each new scheduler operation persists the exact leader owner/generation/invocation and observed live Fleet HEAD, and the binding is rechecked immediately before provider I/O. One batch is pinned to one observed Fleet HEAD; if the leader or HEAD changes, remaining effects stop and replan. Read-only `max_effects=0` assessment remains available to standby supervisors. The existing per-runtime operation journal keeps its legacy incident-scoped lineage for compatibility and future legitimate wakes. Cross-subscription deduplication happens in the outer Fleet-leader effect journal, whose canonical intent excludes diagnostic incident labels while binding project/ref/watchdog trigger state, leader generation and live Fleet HEAD; renaming an incident therefore cannot create a second provider effect.


## Fleet leader finalization

Fleet leadership is not a permanent role. The embedded execution lease follows the same transactional boundary as project ownership. Use `begin_finalization_cas` → `record_checkpoint_cas` → `reconcile_finalization_cas` → `mark_ready_cas` → `release_leader_cas`. Reconciliation and release fail closed while any effect from that leader generation is nonterminal. Successful release returns the same `execution-release-receipt/v1` schema, bound to the Fleet Supervisor document revision. `GitDocumentStore.read_revision(receipt.lease_revision)` can later recover the historical state and its embedded released lease even after successor generations advance the current document.

Watchdog desired-state survivability is subject to the same fence. `watchdog_survivability_runtime` may reconcile prior unknown operations from readback without replay authority, but any new `create/enable/run/disable` scheduler effect requires a Fleet leader guard. The exact leader binding is persisted with the operation and re-read immediately before provider I/O; a changed leader or Fleet HEAD closes the claim as blocked/not-submitted rather than fabricating an unknown provider outcome.
