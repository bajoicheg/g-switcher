---
name: continuous-development-cycle
description: Use when substantial software development must continue across long sessions, interruptions, CI runs, repository migrations, watchdog resumes, development chat cleanup, Work/Codex orchestration, Codex Compute setup or failures, or limited compute budgets.
---

# Continuous Development Cycle v2.9.2

Durable repository state is the project state. Sessions, agents and schedulers are disposable. Apply the instruction hierarchy, preserve the source/scope of existing user authorization, and reconcile repository policy. Live remote facts override stale checkpoint/chat claims. A spinner, lease or submitted request is not progress evidence.

Before scheduler status, recovery or changes, read `references/watchdog-recovery-and-migration.md`. Keep user-authorized scheduler state separate from current-wake execution eligibility. Blockers, budget/runtime limits and quiet notifications do not authorize disabling a recurring watchdog. Honor a later verified user pause; audit unexplained drift rather than invent its cause. Protect verified task-linked chat IDs from cleanup; diagnose archived/missing chat dependencies before retrying. Read the chat recovery procedure in that reference.

For watchdog/status/resume work, build the **six-signal health vector** from fresh evidence before deciding that development is healthy, blocked, stalled, or recoverable: scheduler state, chat dependency, invocation state, execution lease, external operation/guard, and last meaningful progress. Use `scripts/watchdog_health.py` and the contract in the watchdog reference. The aggregate assessment is diagnostic only: it never grants takeover, product writes, external starts, scheduler mutation, budget restoration, merge, or release authority. Persist a health snapshot on an authorized coordination path when useful; never move a guarded product HEAD merely to publish health. Use the assessment fingerprint to suppress unchanged noise while still reporting new drift or a changed recovery action.

## Route the executor

- **Ordinary ChatGPT chat:** no subagents; execute sequentially.
- **ChatGPT Work:** useful independent subagents explicitly allowed and requested within authorized work.
- **Codex used as the orchestration environment:** same delegation permission as Work.
- **Unknown origin:** no subagents. Watchdogs inherit their actual runtime.

Use adaptive **minimum sufficient effort**, one integrator and isolated/non-overlapping writers; honor configured agent budgets. Read `references/runtime-routing-and-subagents.md` when delegating. A delegated Codex `COMPUTE_ONLY` worker only verifies supplied exact-SHA commands; it cannot edit, commit, push, merge or close tasks. Unavailable delegation means sequential work.

## Recover with a compact probe

1. Read this core, current `AGENTS.md`/applicable instructions, adapter and compact checkpoint. Validate policy/checkpoint with `scripts/validate_adapter.py` and `scripts/validate_checkpoint_24.py`. Reconcile permission/version/digest drift using `references/policy-compatibility.md`; never silently discard a restriction or repeat an already-granted permission question.
2. Refresh canonical repository identity, branches/HEAD, coordination revision/owner/generation, external operations, and PR/CI/release revisions. An incomplete/stale lookup is uncertainty.
3. Use `scripts/recovery.py` and `references/bounded-recovery.md` to compare a durable snapshot with this fresh probe. On exact fresh agreement, load only phase-relevant references and changed material. Otherwise expand reconciliation. Always load actual current instructions; a matching HEAD alone cannot justify reuse of old task, lease or external state.
4. Before writes, apply the ownership, external-operation and budget gates in `references/orchestration-controls.md`.

Adapter v3 remains the policy envelope. Checkpoint v4 is the CDC 2.4 write format; checkpoint v3 remains read-compatible during explicit migration. The optional `orchestration` block requires skill 2.3+. Missing control configuration is not permission to elect a writer or fabricate available budget; establish an authorized backend/assignment and durable state first. Observe existing work while doing so.

## Own work before acting

Read `references/execution-ownership.md` and `references/control-plane-v2.4.md`. New ownership mutations use invocation-bound `execution-lease/v2`: a unique executor UUID plus the exact invocation ID, monotonically increasing generation and conditional updates to a separate coordination ref. Existing owned v1 leases are never rewritten in place; migrate only after explicit release or verified quiescence at a safe boundary. Refetch/check ownership and expected revision immediately before each shared write/external start. Renew only after a new observed owner action.

**Lease v2 writes are fail-closed.** The Git coordination store validates the record according to its actual schema before every read/CAS: v1 through the legacy validator, v2 through the invocation-bound v2 validator. Never hand-edit only `owner_id`, `generation` or ownership timestamps in a v2 record. An owned v2 record without valid `invocation` and `finalization` is a control-plane incident: reconcile provider/guard evidence and perform bounded recovery; do not renew it or start external work. Once migrated to v2, coordination cannot downgrade to v1.

A timestamp or local atomic file replacement is not a distributed lock. Git coordination uses ordinary conditional fast-forward pushes, never force-push. Where conditional storage is unavailable, only the explicitly designated executor may write; others observe. Expiry alone never authorizes takeover: require release or verified previous-executor quiescence, including pending effects. CAS ownership does not fence arbitrary downstream writes.

**Invocation finalization is an ownership boundary.** An ordinary ChatGPT/watchdog invocation cannot remain a live executor after its final response. CDC 2.4 makes this transactional: `active → draining → checkpointed → reconciled → ready → release`. Before returning a final response while it owns the lease, drain shared writes, persist/read back the checkpoint or resume capsule, reconcile or durably preserve any unresolved external guard, pass the hard execution-continuity gate, mark finalization ready, and explicitly release the exact invocation-bound lease. A final response that leaves an owned lease is an orphan-lease defect.

During foreground recovery or an explicit kick, independently verified completion of the **exact owning invocation** may establish `executor_stopped` quiescence even before TTL expiry, but only after confirming that no pending write remains, every submission is terminal/reconciled, the external guard is null (or terminal and cleared), and source HEAD movement is understood. A stale heartbeat, elapsed TTL, silence, or scheduler `last_run_time` by itself is never enough. A still-fresh heartbeat from an invocation that is independently proven finished is historical activity, not proof that the executor is still alive.

Persist/read back the exact operation intent and external guard before submission; consume the submission claim once through the ownership protocol. Lost replies, unknown outcomes and active tasks retain the guard across lease expiry/handoff. Reconcile using `references/external-operations.md`; never reconstruct a launch grant from a saved record. Keep an in-flight candidate's source ref stable.

## CDC 2.4 durable control plane

Use `scripts/resume_capsule.py` to validate the compact durable resume capsule. Fast resume is allowed only when the fresh live probe exactly matches repository/ref/HEAD, policy version, checkpoint digest and lease revision; any drift expands to normal reconciliation. The capsule is an optimization and handoff record, never authority.

Use `scripts/execution_continuity.py` as the hard pre-final-response gate. The execution FSM is `BOOTSTRAP → RECONCILE → OWNERSHIP → EXECUTE → VALIDATE → CHECKPOINT → CONTINUE` with explicit `WAIT_EXTERNAL`, `BLOCKED` and `COMPLETE` outcomes. A runnable invocation cannot terminate on status/health/lease/poll/report/heartbeat activity alone. Valid terminal boundaries are meaningful durable progress, a durable external binding, a resumable blocker with exact next action, or verified task/scope completion.

Lease v2 and checkpoint v4 are forward write formats. Legacy lease v1 and checkpoint v3 remain readable for migration; do not mutate an owned v1 lease merely to upgrade it. See `references/control-plane-v2.4.md`.

## Human interaction is not an execution backend

A missing connector/API method is a capability gap, **not** a manual approval requirement. Before asking the owner to click, dispatch, copy, upload or otherwise perform a mechanical execution step, first exhaust safe durable alternatives already within authorization: event-triggered workflows, branch/push/PR triggers, continuation events, an alternate compatible backend, or a policy-safe workflow/control-plane change. Prefer a path that preserves exact-SHA binding and evidence.

Escalate to the human only when the remaining step genuinely requires human judgment/authorization, a secret/credential not available to the authorized runtime, a protected approval/environment gate, or an external system with no authorized automation path. When escalation is unavoidable, persist the exact resumable checkpoint and request one minimal concrete action. Never translate `workflow_dispatch unavailable`, `connector method missing`, or equivalent transport gaps into owner approval.

## CDC 2.7.3 visibility-aware compute economics

Compute selection is both capability- and cost-aware. Use `scripts/cost_router.py` and `references/cost-aware-routing.md` after capability routing. Project policy expresses relative backend cost; it is not a currency calculator. Repository visibility is part of the cost context. For private/internal repositories, Codex Compute remains the default low-cost primary for eligible portable work and a transient/setup/network/provider/runtime Codex failure does **not** automatically justify metered GitHub Actions. For public repositories where standard GitHub-hosted Actions are configured as unmetered by project policy, Actions are not an expensive fallback and may be selected directly by cost routing when compatible.

Use bounded, information-gaining Codex recovery/probes, respect cooldown, and prefer another cheaper compatible backend. If bounded recovery is exhausted without independently confirmed provider outage, persist `waiting_compute` rather than spending expensive CI for a portable check. A product/test failure is fixed as product/test work; do not buy a second opinion from Actions.

An expensive backend requires an explicit reason such as a missing required capability on all cheaper backends, required final-platform evidence, required artifact production, release attestation, or independently confirmed primary-provider outage. The cost-router result is recommendation-only and never grants ownership, product writes, provider starts, CI budget, scheduler mutation, merge or release authority. Historical degraded/unavailable state is not permanent: re-probe after policy cooldown and restore `ready` only on fresh successful evidence.

## CDC 2.5 capability router, deterministic recovery and continuation queue

Before selecting a validation/compute backend, express the task as `capability-request/v1` and route it against fresh evidenced `backend-capability-registry/v1` using `scripts/capability_router.py`. Capabilities are explicit tokens; never infer Windows, JDK, Android SDK, emulator, network or other requirements from a backend name. Routing is recommendation-only and never grants ownership, budget, provider or launch authority. No compatible ready backend becomes a durable waiting/blocker state rather than a blind launch. Read `references/capability-routing.md`.

Known operational failures use deterministic recovery before open-ended reasoning. Normalize the observed failure to `recovery-diagnosis/v1`, select an allow-listed recipe from `recovery-recipe-catalog/v1` with `scripts/recovery_recipes.py`, and execute each step through its normal authority gate. No recipe grants takeover, writes, starts or scheduler mutation. If no exact recipe matches, preserve a blocker and escalate rather than inventing a destructive recovery. Read `references/deterministic-recovery.md`.

External terminal results, CI terminal results, backend recovery, scheduler recovery, policy changes and explicit kicks may enter the durable `continuation-queue/v1`. Use `scripts/continuation_queue.py` for exact binding, dedupe, invocation-bound delivery claims and acknowledgement. A new event should request an immediate continuation wake when the platform supports one; the recurring watchdog remains the mandatory scheduler fallback and drains the same queue. Queue claims coordinate delivery only and never replace the execution lease, external guard or budget gates. Read `references/event-driven-continuation.md`.

## CDC 2.6 Fleet Supervisor, version convergence, progress SLO and control-plane audit

Fleet supervision is read/control-plane orchestration, **never a super-writer**. Projects publish exact-bound `fleet-project-snapshot/v1` records and a fleet registry binds required repository/source refs, watchdog IDs, the target CDC version/package fingerprint and meaningful-progress SLO. Use `scripts/fleet_supervisor.py` for HEALTHY / DEGRADED / STALLED / BLOCKED / RECOVERY_REQUIRED assessments. Recommendations never grant product writes, takeover, external starts, merges, releases or scheduler mutation. Read `references/fleet-supervision.md`.

Use `scripts/version_convergence.py` to compare stable version **and exact package fingerprint/checkpoint schema**. Version equality with package drift is not convergence. An active owner or unresolved guard makes adoption wait for a safe boundary; convergence output is not merge/write authority. Read `references/version-convergence.md`.

Use `scripts/progress_slo.py` to measure age from the last meaningful durable progress, not heartbeat/status/poll/report activity. Default template thresholds are 20 minutes to DEGRADED and 60 minutes to STALLED. Durable blockers and waiting_external pause the stall clock and remain BLOCKED. SLO state is diagnostic only. Read `references/progress-slo.md`.

Record important control-plane transitions in an append-only hash-chained `control-plane-audit-log/v1` with `scripts/control_plane_audit.py`. The chain makes mutation/reordering/deletion visible but does not create authority. Read `references/control-plane-audit.md`.

## CDC 2.7 canonical source, independent release and consumer locks

Treat the CDC core as an immutable released dependency. Development of CDC N happens only in its canonical source repository under independently validated stable CDC N-1 policy. A candidate runtime is never its only release validator: bootstrap evidence must be produced without importing candidate runtime code, and package/compatibility/fault-injection/consumer evidence remain distinct release classes. Read `references/canonical-source-and-release.md`.

Consumer repositories pin a `cdc-consumer-lock/v1` binding: canonical repository, semantic version, immutable release ref, exact release commit and exact package Git tree. Validate it with `scripts/consumer_lock.py`. Version equality alone is not convergence. A vendored core whose Git tree differs from the lock is drift; do not normalize it by editing the consumer copy. Product-specific AGENTS, adapter/checkpoint and coordination state remain outside the immutable core.

Adoption never crosses an active owner or unresolved external guard. Require an explicit release or independently verified quiescent owner, a reconciled/empty guard, preserved budget/validation/audit history and the exact released package identity before advancing a consumer lock. Self-hosting advances only after the new CDC version has independently reached released state.

## Execute and verify

Follow the configured lifecycle, ordinarily:

`recover → test/spec RED → durable exact SHA → bounded implementation → targeted GREEN → independent review → required final gate → close task → next task`

Use Codex Compute first for eligible authorized, configured and platform-compatible candidate validation. Apply the cost-aware router before expensive fallback. A local runtime alone does not displace Codex when policy keeps Codex primary. Read `references/codex-compute.md` for actual access/environment/task binding; retain `references/validation-compute-and-ci.md` platform and Actions-budget gates. Small local preflight/RED/debugging loops are useful. On concrete ineligibility or required platform capability, use an authorized valid fallback. On transient/setup/provider unavailability, follow bounded low-cost recovery and cost policy before expensive CI; do not bypass Actions budget or spend Actions merely because one Codex attempt failed.

Use the versioned plan, `scripts/run_checks.py` and `scripts/validate_evidence.py` from `references/command-evidence.md`. Bind evidence to the independently expected plan, exact SHA and environment configuration. Each command reports its own exit and `PASS / EXPECTED_RED / FAIL / NOT_RUN`; a wrapper exit, absent/zero-test report or expected RED is not final GREEN.

## User continuation shorthand means terminal state

When the user sends a bare continuation instruction such as **«продолжай»**, **«продолжи»**, **“continue”** or an equivalent unqualified imperative, interpret it as authorization to continue the already-authorized current scope **until terminal state (TS)**. Do not stop after one primitive step, one commit, one status read, one compute result, or one intermediate checkpoint merely because the continuation request itself was short.

This shorthand does not expand scope, permissions, destructive authority, budget, merge/release authority, or bypass any guard. An explicit narrower qualifier from the user wins. TS means either verified completion of the current scope, or a real durable terminal blocker/handoff with exact evidence and one executable next action. A live external task is supervised to terminal state when the invocation can do so; `waiting_external` is a TS boundary only when no same-invocation useful work remains and the exact external binding/handoff is durably preserved.

## Close every accepted execution commitment

Once an invocation has told the user, checkpoint, watchdog, or itself that a
specific runnable `next_action` will be performed, that invocation may not
silently end after discovery, routing, or an empty tool lookup. Before returning
or becoming idle it must cross one observable continuation boundary:

1. **meaningful durable progress** — a source/policy/test/checkpoint mutation or
   newly verified evidence that materially advances the active task;
2. **bound external work** — a durable exact operation intent/guard plus an
   actual task/run/request identifier, or a correctly preserved unknown
   submission that is being reconciled; or
3. **explicit durable handoff/blocker** — the concrete unavailable capability,
   failed guard, permission/budget/runtime limit, or other real blocker is
   checkpointed with one executable next action and ownership is released.

Tool discovery, an empty plugin/tool search, acquiring or renewing a lease,
scheduler readback, polling unchanged state, a spinner, or a sentence such as
“next I will check …” is **not a continuation boundary**. If the preferred
backend is unavailable, immediately try the next policy-authorized fallback in
the same invocation. If no valid fallback exists, record the blocker/handoff in
that invocation; never leave the user with an implied active worker.

Interactive foreground work also follows the configured anti-silence interval:
if substantial work continues without a user-visible update, emit a concise
state/evidence/next-action update. A chat update improves observability but does
not count as meaningful repository progress by itself.

## Bound waits and spending

Use `scripts/recovery.py` for separate queue/setup/run/unknown deadlines, last successful observation and capped poll backoff. A missed deadline requests diagnosis; it never proves a task stopped or permits replacement. Respect provider retry timing. Do not stop supervising an authorized existing task merely because four (or any preset number of) polls have occurred. Default status-poll count caps are null; bound polling by backoff and phase deadlines, and diagnose at the deadline. Observing the same task requires no renewed launch permission. Keep blocking waits at most 60 seconds, preserving handoff state when runtime/budget ends.

Use `scripts/budget.py` and `references/budget-ledger.md`: reserve starts before effects, preserve uncertain charges, track per-task/per-wake use and leave checkpoint resources. Default Codex Compute admission is **4 starts per wake/cycle** (`wake_limits.compute_starts: 4`); keep GitHub Actions policy and CI-start limits unchanged. Unknown tokens/quotas stay unknown. Repeated failure requires concrete correction/service recovery; a new SHA alone does not repair infrastructure. Budget approval is one gate, not launch permission.

**Higher compute capacity** is capacity, **not a retry instruction**. Spend the additional starts where each attempt has expected **information gain**: a deliberately distinct RED or GREEN check, independent candidate/platform validation, or a retry only after concrete correction or observed service recovery. A larger allowance is not a target; do not spend it on identical probes, unchanged setup failures, or duplicated verification that cannot change the decision.

Give concise updates on phase, evidence, blockers and backend changes; follow the runtime's communication interval. Persist control references and one concrete next action on handoff, release ownership and retain unresolved external guards. See `references/progress-and-checkpoints.md` and `references/watchdog-recovery-and-migration.md`.

Continue until approved work and closure/release gates are complete, a real blocker remains, or a runtime/tool limit forces a durable handoff. A commit, result, review or single completed task is a continuation point.

Release from an exact **release-candidate SHA** with configured version, platform, artifact and smoke/security evidence; see `references/release-management.md`. Do not start a parallel release line unless policy allows it. Apply the concurrency guard and verify canonical identity before every push; stop on unreconciled external movement.

## Companion skills

Use available `superpowers:brainstorming` for new/scope-changing work, `superpowers:writing-plans` for multi-step implementation, `superpowers:test-driven-development` for features/fixes, `superpowers:systematic-debugging` for failures, `superpowers:requesting-code-review` for independent review, `superpowers:verification-before-completion` before success claims, and `superpowers:finishing-a-development-branch` for integration. Existing user authorization and higher-priority instructions govern their workflow gates.


## CDC 2.8.0 Autonomous Continuity & Isolation

CDC 2.8.0 promotes terminal-state semantics into an executable **Terminal-State v2** contract. The **No-Idle** invariant is strict: if a policy-authorized runnable action exists, an invocation may not end with a final response. Use `scripts/terminal_state_v2.py`; COMPLETE requires terminal evidence, WAIT_EXTERNAL requires one durable external binding plus an executable recheck action, and BLOCKED requires evidence, an exact next action and a recheck trigger. Terminal response also requires release of any invocation-bound lease.

Use the **execution-channel supervisor** in `scripts/execution_channel_supervisor.py` when a backend fails. In the same invocation, exclude the failed backend and route to the next compatible policy-authorized backend within bounded failover. Product/test failure is fixed as product work rather than sent to another backend for a paid second opinion.

Use **concurrent-writer reconciliation** in `scripts/concurrent_writer.py` whenever observed HEAD differs from expected HEAD. A non-overlapping fast-forward may be replayed on the fresh HEAD; overlap, divergence, unknown ancestry or an unresolved external guard requires reconciliation. Force-push remains forbidden.

Before any private-to-public transition, use the policy-driven sensitive-context scanner and publication guard. Public safety covers the current tree, every exposed ref, conversations and artifacts; secret scanning alone is insufficient. Operational CDC state such as leases, ledgers, authorizations, backend registries, operation intents and handoffs belongs outside the publishable product surface. Findings select a sanitized export/new public history rather than a direct visibility toggle. Read `references/autonomous-continuity-and-isolation.md` and `references/publication-safety.md`.


## CDC 2.8.1 Operational Hardening

Use **watchdog self-repair** rather than treating a disabled/missing/overdue scheduler, archived chat dependency, or unavailable backend as passive status. `scripts/watchdog_self_repair.py` produces a bounded recovery plan and never grants mutation authority.

Use **ref hygiene** and coordination retention to bound temporary operational state. Protected/live/referenced refs and records are retained; planners never authorize deletion themselves.

A **blocker proof** is required before BLOCKED can end an invocation: dependency ID, fresh observation, evidence, exact next action, recheck trigger and proof that same-invocation useful work is exhausted.

Use **decision authority** to avoid unnecessary owner interruptions. Reversible/compensatable low-or-medium-risk work inside existing scope proceeds only when durable policy already pre-authorizes it. Human boundaries remain for scope expansion, high risk, destructive/irreversible actions, missing secrets and protected gates.

Use **evidence compaction** to preserve result counts, durable refs and deterministic source digest without copying verbose diagnostics into canonical state. Use **progress enforcement** so DEGRADED/STALLED/RECOVERY_REQUIRED produce concrete continuation/recovery actions. Read `references/operational-hardening.md` and `references/decision-authority.md`.


## CDC 2.8.2 Fleet & Publication Maturity

Use **project-independent fleet control** to supervise normalized project state without product-specific code or super-writer authority. Owners and guards are observed, runnable unowned projects are woken, and stalled projects receive watchdog recovery actions.

Use the **stuck-state detector** to identify repeated action/result fingerprints or unchanged HEAD without meaningful progress. When stuck, **counterfactual recovery** must select a different compatible strategy with positive expected information gain; blindly repeating a failed strategy is forbidden.

Use the **sanitized public export** planner for private-to-public publication. The target is a new public history built from allow-listed product paths after publication guard/history/control-plane checks; never turn the internal development repository public as the publication mechanism.

Use **CDC dogfooding** metrics to measure CDC's own development against terminal-state accuracy, No-Idle, exact-SHA validation, recovery diversity, control-plane isolation and consumer evidence. Dogfooding is observability only and never grants release or policy authority. Read `references/fleet-and-publication-maturity.md`.


## CDC 2.9.0 Deterministic Distribution & Convergence

Treat released CDC package delivery as a carrier-neutral transport problem. The delivery channel is not trusted merely because it can copy bytes. Use scripts/package_transport.py to validate a transport manifest against an independently trusted release version, release commit and exact package Git tree; then verify transported file content and, after adoption, verify the actual vendored Git subtree. The manifest preserves path, Git file mode and blob identity, so archive/filesystem mode loss cannot silently become a different package tree. Read references/deterministic-distribution-and-convergence.md.

The canonical **convergence vector** is stricter than a version label. Use scripts/convergence_vector.py to bind repository/source ref + exact HEAD, CDC version, exact package tree, consumer-lock release identity, semantic policy digest, checkpoint validity, lease state, guard state and adoption state. A project is integrated only when all required bindings agree on the same source HEAD and ownership/guard state is reconciled. A version string alone is never fleet convergence evidence.

Classify CI evidence before choosing remediation with scripts/ci_evidence_classifier.py. Zero-step or pre-job failures are pre_run_infrastructure; setup that never reaches product validation is setup; executed product checks are product_test; terminal successful product validation is terminal_success. Never prescribe a source correction solely from evidence where product validation did not execute. Classifier output is diagnostic and never grants product writes, external starts, merge or release authority.


## CDC 2.9.1 Transactional Migration & Provider Reconciliation

Use scripts/policy_migration.py for idempotent section-aware adoption on a **fresh HEAD**. A moved HEAD requires semantic replanning; strict YAML duplicate keys are rejected, managed sections are replaced by key, and replay of an already-converged policy is a no-op.

Use scripts/checkpoint_builder.py for **schema-typed** checkpoint construction. Typed Boolean/enumerated control fields are explicit inputs, not parsed from display text, and the real v4 checkpoint validator is a mandatory pre-commit gate.

Use scripts/migration_transaction.py for operation-budget-aware Git-object transfer. Batches preserve finalization reserve and produce only **detached tree** checkpoints until every object, exact subtree identity and policy reconciliation are complete. The planner never grants product-write or ref-move authority.

Use **terminal-provider reconciliation** through scripts/provider_reconciliation.py whenever a guarded provider task becomes terminal. Re-enter reconciliation for the exact operation key; provider terminal state or TTL alone never grants takeover. Explicit executor-stopped evidence plus no pending writes/effects may establish a recovery candidate, but normal lease authority remains mandatory. Read references/transactional-migration-and-provider-reconciliation.md.


## CDC 2.9.2 Continuous Autonomy & Learning

Enforce **Progress-Is-Not-Terminal** with scripts/continuation_cycle.py. A milestone or progress update is informational only; immediately re-enter observe → reconcile → choose-next → act unless Terminal-State v2 independently permits a real terminal response.

For **every user command in every CDC-managed chat**, read the **actual current Moscow time** from a fresh runtime or authoritative clock observation and emit exactly one timestamp in the format **[HH:MM DD.MM]** before or with the first substantive progress update. Never extrapolate or manually increment from the previous timestamp. Do not add an MSK label or seconds. Timestamp evidence creates no authority.

Close every material anomaly through the **RCA-to-roadmap** feedback contract in scripts/rca_feedback.py: classify, deduplicate by stable fix key, sanitize sensitive context and produce one systemic disposition.

Every Fleet Watcher run must produce **exactly one improvement** result through scripts/fleet_improvement.py: either a new evidence-based proposal or a deduplicated reinforcement. Do not force novelty and do not allow an empty harvest. Read references/continuous-autonomy-and-learning.md.
