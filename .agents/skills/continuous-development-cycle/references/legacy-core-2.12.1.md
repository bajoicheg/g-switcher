---
name: continuous-development-cycle
description: Use when substantial software development must continue across long sessions, interruptions, CI runs, repository migrations, watchdog resumes, development chat cleanup, Work/Codex orchestration, Codex Compute setup or failures, or limited compute budgets.
---

# Continuous Development Cycle v2.12.1

## Active execution contract — apply before recovery detail

A request to continue/develop/fix means execute the authorized scope through its real terminal boundary. After every commit, test, review, report or child task, choose and perform the next eligible action in the SAME invocation. Send progress in commentary; do not use a final response as a progress report. A milestone is never permission to stop.

1. Verify the code actually loaded: installed `VERSION`, `manifest.json`, `SKILL.md` and the authorized canonical release must agree. A version label in a repository does not update the installed skill. Resolve drift by loading the verified authorized package before using its controls; never claim adoption until installed bytes are verified.
2. Keep the remaining scope and next runnable action explicit. A dependency blocks its dependent work, not unrelated authorized actions. Missing workflow dispatch or a failed tool route means try a safe available route, not ask the owner to do a mechanical step.
3. Before beginning lease finalization, evaluate `scripts/execution_continuity.py` against fresh scope facts. `allowed` alone is insufficient: only `final_response_allowed=true` permits the terminal path. `continue` and `progress` are always nonterminal. Supply `terminal_state` (Terminal-State v2) with separate scope-completion evidence or an exact external binding; BLOCKED also requires a fresh `blocker_proof`. Bind these to the same invocation and persisted checkpoint. A pre-release decision skips only the release check; final response still requires actual lease release. Do not enter draining while more work is runnable.
4. End only for verified scope completion, an evidenced blocker/external wait with no eligible same-invocation work, an explicit owner pause, or an actual runtime/tool/budget limit requiring durable handoff. Report the specific limit and remaining action; never relabel a milestone or model convenience as a limit. Preserve the unfinished queue and external guards. A child task's completion is not scope completion when another task remains.
5. Current user authorization governs routine recovery and existing implementation plans. Engineering skills supply tests/review/worktree discipline, not redundant requests to approve already-authorized work. Apply the governing instruction hierarchy; never waive a real security, destructive, ownership or protected gate.
6. Honor an explicit owner scheduler pause. Never enable paused watchdogs merely to make the system appear continuous. Continue eligible foreground work.

These are cooperative agent/runtime controls. Python validators do not intercept ChatGPT's final-response channel or autonomously launch workers; the active executor must actually invoke them and obey the decision. Test the real lease path and agent behavior, not just words in a response.

Minimum supported CDC runtime is **2.11.3**. Older executable runtime compatibility is retired. Historical checkpoint, lease, operation-intent and audit records remain readable as data for current-runtime recovery. Historical producer labels do not authorize executing an older runtime.

Durable repository state is the project state. Sessions, agents and schedulers are disposable. Apply the instruction hierarchy, preserve the source/scope of existing user authorization, and reconcile repository policy. Live remote facts override stale checkpoint/chat claims. A spinner, lease or submitted request is not progress evidence.

Before scheduler status, recovery or changes, read `references/watchdog-recovery-and-migration.md`. Keep user-authorized scheduler state separate from current-wake execution eligibility. Blockers, budget/runtime limits and quiet notifications do not authorize disabling a recurring watchdog. Honor a later verified user pause; audit unexplained drift rather than invent its cause. Protect verified task-linked chat IDs from cleanup; diagnose archived/missing chat dependencies before retrying. Read the chat recovery procedure in that reference.

For watchdog/status/resume work, build the **six-signal health vector** from fresh evidence before deciding that development is healthy, blocked, stalled, or recoverable: scheduler state, chat dependency, invocation state, execution lease, external operation/guard, and last meaningful progress. Use `scripts/watchdog_health.py` and the contract in the watchdog reference. For live recovery also supply the current project scope, owner pause and exact invocation to `scripts/watchdog_liveness.py`; v1 six-signal HEALTHY alone cannot prove that a completed invocation exhausted its runnable work. The aggregate assessment is diagnostic only: it never grants takeover, product writes, external starts, scheduler mutation, budget restoration, merge, or release authority. Persist a health snapshot on an authorized coordination path when useful; never move a guarded product HEAD merely to publish health. Use the assessment fingerprint to suppress unchanged noise while still reporting new drift or a changed recovery action.

## Route the executor

- **Ordinary ChatGPT chat:** no subagents; execute sequentially.
- **ChatGPT Work:** useful independent subagents explicitly allowed and requested within authorized work.
- **Codex used as the orchestration environment:** same delegation permission as Work.
- **Unknown origin:** no subagents. Watchdogs inherit their actual runtime.

Use adaptive **minimum sufficient effort**, one integrator and isolated/non-overlapping writers; honor configured agent budgets. Read `references/runtime-routing-and-subagents.md` when delegating; use its bounded parallel operating recipe with two independent writers by preference, an optional analyst within existing caps, one integrator and aggregate validation. A delegated Codex `COMPUTE_ONLY` worker only verifies supplied exact-SHA commands; it cannot edit, commit, push, merge or close tasks. Unavailable delegation means sequential work.

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

Use `scripts/execution_continuity.py` as the hard pre-final-response gate. The execution FSM is `BOOTSTRAP → RECONCILE → OWNERSHIP → EXECUTE → VALIDATE → CHECKPOINT → CONTINUE` with explicit `WAIT_EXTERNAL`, `BLOCKED` and `COMPLETE` outcomes. A runnable invocation cannot terminate on status/health/lease/poll/report/heartbeat activity alone. Meaningful durable progress is nonterminal. Terminal boundaries require no eligible remaining action plus a durable external binding, an evidenced resumable blocker with exact next action, or verified completion of the authorized scope.

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

## CDC 2.10.0 Behavioral Skill TDD & Verification Gate

Use **behavioral skill TDD** for material CDC behavior changes. A prose rule or helper unit test is not sufficient by itself: capture the pressure scenario, retain a **baseline RED** trace that demonstrates the failure, apply the control correction, and require a **corrected GREEN** trace under the same pressure facts. Run `scripts/behavioral_eval.py` and keep the case as release regression evidence.

Use **systematic debugging** before material RCA disposition. `scripts/systematic_rca.py` requires competing hypotheses, discriminating tests, observed results, exactly one supported root-cause hypothesis, a bounded correction and defense-in-depth. Feed its result into the existing RCA feedback disposition; neither stage creates product or roadmap write authority.

Before any terminal success claim (`COMPLETE`, `RELEASE_READY` or `INTEGRATED`), run the mandatory **verification-before-terminal** gate in `scripts/verification_gate.py` against freshly re-read authoritative evidence. Verify exact source HEAD, required checks and SHA binding, checkpoint/policy state, live coordination lease/guard, required artifacts and clean state where applicable. A stale checkpoint never overrides newer coordination state.

Verification is evidence-only. GREEN verification can reject or permit the claim path, but it never authorizes product writes, external starts, takeover, merge, release, scheduler mutation or scope expansion. Normal CDC authority and terminal-state gates still apply.

Superpowers is the engineering-quality layer here; CDC remains the authority/ownership/continuity control plane. Do not import redundant approval loops for routine fixes or already-authorized continuation. Read `references/behavioral-tdd-and-verification.md`.

## CDC 2.10.1 Specification Compliance & Two-Stage Review

For material new or scope-changing work, use **selective brainstorming** only when the product/design choice is genuinely ambiguous. Clear fixes and already-authorized continuation must not be forced through redundant clarification or approval loops.

Bind **spec → plan → continuation queue** with `scripts/spec_plan_queue.py`. Each plan task references the specification requirement and expected evidence. A complete task without evidence is invalid; every runnable non-blocked task remains in the continuation queue so a task milestone cannot silently end the authorized scope.

For explicit migrated quality policies, use `scripts/quality_levels.py` and `review-pipeline/v2`: FAST self-review, MEDIUM one independent combined requirements/quality review, FULL ordered spec-compliance review and code-quality review by separate independent reviewers. Critical CDC/authority/authentication/AD-write/migration risk requires FULL. Legacy policies and review-pipeline/v1 retain their existing ordered two-review requirements. Open findings block completion. Authenticate policy, risk classification and review evidence against the actual scoped change; a self-declared lower category is not proof. Read `references/quality-levels.md`.

Use **branch finishing** through `scripts/branch_finish.py` before handing a candidate to CDC terminal/release handling. Require fresh validation, exact candidate/HEAD binding, diff/spec reconciliation, required level-specific reviews GREEN, no unresolved findings, required checks and clean state. Legacy branch-finish/v1 retains both reviews and strict exact-SHA checks; branch-finish/v2 accepts explicit validated reuse without relabeling the original run.

Review and branch-finishing results are evidence-only: they create no product-write, merge, release or scope-expansion authority. CDC ownership, verification-before-terminal and release controls remain independently mandatory. Read `references/specification-review-and-finishing.md`.

## CDC 2.10.2 Worktree-Isolated Parallel Development & Single Integrator

Use **worktree-isolated parallel development** only when the actual orchestration runtime and project policy already allow delegated writers. **Ordinary ChatGPT chat remains sequential.** A parallel plan never grants worker-launch authority.

Build a dependency DAG and explicit **write-set** plan with `scripts/parallel_task_planner.py`. Independent ready writers may share a wave only when write paths are non-overlapping; overlapping writers are serialized or explicitly repartitioned. Cyclic task graphs are invalid.

Before delegation, bind each worker through `scripts/worktree_worker_contract.py` to a durable worker/task identity, exact common base SHA, isolated branch and worktree, bounded write set, expected outputs and evidence. For wave 2+, a claimed base is insufficient: resolve a content-addressed prior integration record and its content-addressed GREEN integration-gate artifact before accepting the fresh integrated base. Delegated workers cannot write the shared integration branch, merge, release or expand scope.

Preserve one **single integrator**. After worker completion, use `scripts/integration_gate.py`; stale/failed workers, shared-HEAD movement, writer-result overlap, unresolved conflicts, missing spec/code review or any force-push request require reconciliation/replanning. A GREEN `READY_FOR_INTEGRATOR` result is evidence-only and creates no shared-branch write authority.

Measure real benefit with an **observed parallel benchmark** through `scripts/parallel_benchmark.py`. Planner estimates are not release evidence. The benchmark manifest must resolve the actual plan artifact bytes and require `plan_ref` to equal their SHA-256; matching hash-shaped labels are insufficient. The benchmark is GREEN only when observed parallel wall-clock time beats the sequential baseline without increasing unresolved conflicts or rollbacks.

After integration, the final candidate still passes CDC 2.10.1 branch finishing and CDC 2.10.0 verification-before-terminal controls, plus normal ownership/release gates. Read `references/worktree-parallelism-and-integration.md`.

## CDC 2.11.0 Managed Executor Pool

Use a **managed executor pool** for bounded Work-style delegation. The parent invocation remains authoritative for the change; children receive task contracts and evidence obligations, never shared-branch write, merge, release, scope-expansion, scheduler or user-approval authority.

Worker launch is **capability-gated**. When the current runtime cannot launch independent executors, use the **deterministic sequential fallback** over the same task/evidence plan and **must not fabricate subagents** or parallel execution evidence. Already-authorized child tasks need no per-launch user approval when runtime and project policy permit delegation.

Writers remain isolated on exact-base branches/worktrees with portable write claims, and a **single integrator** is the only shared-branch writer. Read-only/review executors carry no write claim.

Worker launch authority is **durable-CAS gated**. Queue/dispatch calculation is advisory until a production durable state store (the built-in `scripts/managed_executor_store.py` Git CAS store or an equivalent store satisfying the same compare-and-swap contract) atomically commits the exact task/attempt/reservation token. **Never launch from an in-memory `queue_task()` result alone.** Only the successful CAS winner may launch; stale sibling reservations fail closed.

Every attempt has durable lifecycle and **attempt lineage**. Duplicate active launches are reconciled, retries create new attempt identities, and one worker failure does not cancel unrelated independent tasks. A successful worker result is still an **unintegrated successful result** until accepted by the integrator. If a worker cannot push, return a **content-addressed result handoff** for parent-mediated publication; missing push capability must not discard or rerun completed work. Publication is GREEN only when the exact **authoritative remote ref** equals the verified result commit; a local branch is not publication evidence. Verify bundle artifacts from an immutable snapshot of already-authenticated bytes.

Required runnable/queued/running work, required recoverable failures, or an unintegrated successful result keep the parent non-terminal. Optional planned/recoverable work also requires explicit execution or omission, and retries reserve only their remaining per-task runtime/cost budget. **Progress is not terminal**: after a child or milestone completes, continue the CDC loop until the project-level terminal gate accepts a real boundary.

Read `references/managed-executor-pool.md`.


### Final managed-pool trust boundaries

A managed pool has exactly one **authoritative coordination ref** bound into the validated plan and durable state. Initial durable state pins the full canonical plan digest before queue admission; altered scope, backend or budget cannot reuse an existing queued claim, including across restart. Callers do not choose a different ref for the same pool. Queue reservation is not worker-start authority: only a successful **one-shot durable queued→running CAS** for the exact task/attempt/reservation token may return launch authority, and replay/stale contenders fail closed.

Writer acceptance covers the **entire introduced commit history**, not only the final tree delta. A touched-and-restored out-of-claim path is still an escape. Ambiguous/merge history must be rejected or normalized into an independently validated sanitized result before acceptance.

A required task may not depend directly or transitively on optional work that can be omitted/discarded. Optional disposition must never strand required work.

Publication proof uses a trusted immutable **remote identity/fingerprint** supplied by parent/integrator policy. The configured remote must have one identical fetch/push endpoint, and proof must verify the exact remote branch without logging credential-bearing URLs. A mutable remote name alone is not authority.

### Actual execution and parent closure

Use `scripts/managed_executor_runtime.py` to connect durable pool claims to actual backend effects. Its Linux local-command backend supervises real argument-array subprocesses in isolated Git worktrees, retains an exact attempt journal, and requires descendant quiescence before terminal process acceptance. Host adapters implement the documented start/observe/cancel interface; a validator or stored claim cannot create a Work/Codex tool capability. Unknown starts are observed, never blindly replayed.

Before managed-parent finalization, call `ManagedExecutorRuntime.evaluate_parent()` with fresh continuity evidence. It reads the authoritative pool and combines it with the 2.10.3 terminal contract; required active or unintegrated work keeps the parent running. Read `references/managed-executor-runtime.md`.

Verify active installation with `scripts/active_package.py` against the pinned canonical tree. Exact Git vendoring is strict; explicit host normalization may cover only equivalent interface YAML, icon substitution and executable-mode normalization. Modified runtime/instruction bytes and unpinned executable bytecode caches fail closed. Before installation verification, remove only known generated Python caches; use source-only imports or an empty external cache prefix when execution must avoid loading local cached bytecode (`-B` alone disables writes, not reads). Package verification does not prove that the model obeys its instructions.


## CDC 2.11.1 Persistent watchdog liveness and live target resolution

At every watchdog/Fleet entry, resolve the configured authoritative live registry and target at one fresh revision using `scripts/live_target.py`. Verify canonical released version, release commit and package tree. An embedded prompt version or an old project target alias is historical context; it cannot replace the current authority. Target resolution is evidence, never adoption permission.

Use `scripts/watchdog_liveness.py` to distinguish critical nonterminal inactivity from verified project completion and explicit owner pause. A completed invocation with runnable work is a liveness incident even when it released its lease. Budget exhaustion preserves continuation for the next wake and never disables the recurring schedule. Uncertain invocation, owner, lanes or external operation must be observed/reconciled before any competing effect.

Use `scripts/fleet_watchdog_runtime.py` for a bounded all-project recovery pass with an actual authorized scheduler adapter and durable conditional journal. Refresh the latest owner pause and other gates before every effect, including between enable and run. Persist one-shot effect claims before submission; lost/unknown results retain their claim across controller restart and require reconciliation. Preserve every deferred project for continuation. An enabled scheduler or accepted run request is not observed execution or meaningful product progress.

An explicit current owner pause wins over enabled-until-terminal policy. Never enable, run, rebind or reschedule paused automations. Foreground eligible work continues. Cooperative validation cannot intercept an agent's final channel, manufacture unavailable host capabilities or fence arbitrary downstream writes. Read `references/watchdog-liveness-runtime.md` and `references/live-target-resolution.md` for exact contracts and capability boundaries.


## CDC 2.11.2 Cooperative project lanes and watchdog survivability

Use `scripts/project_lanes.py` and `scripts/project_lane_runtime.py` to coordinate concurrent foreground, watchdog, Work and Codex execution on one project. Before the first lane, establish the durable legacy migration gate with independent proof that the old project-wide lease is absent/released/quiescent, external guards are none/reconciled, and legacy acquisition is disabled; the registry revalidates this proof on every read and admits nothing without it. Every lane binds exact executor/invocation identity, source HEAD, role, portable read/write claims, isolated branch/worktree and generation. Disjoint writers may coexist; portable path overlap, branch/worktree reuse and multiple integrators fail closed before effects. Read-only/review lanes may coexist with writers on pinned source snapshots.

For actual worker execution, use `scripts/project_lane_executor.py` with an explicitly available backend and an authorized worktree root that is disjoint from the product worktree and durable journal. Every worker worktree must resolve beneath that root. The adapter commits a one-shot durable start claim before any worktree/process effect and re-reads it immediately before backend start. Unknown starts keep the lane pending and are observed without replay. The managed-executor local-command backend is compatible and creates the isolated Git worktree only after lane admission. Do not treat a stored lane claim or a process demo as proof that a worker was actually launched.

A foreground lane never implicitly pauses the project watchdog. When a watchdog encounters an occupied write claim, select another runnable non-conflicting task or observation/review work. Existing claims are not stolen for urgency. Handoff/recovery requires a durable checkpoint plus independently verified quiescence; TTL or silence alone never frees a lane. Heartbeats require both a new activity reference and independent evidence that the activity was actually observed. Lane release is executor/invocation/generation-bound, requires drained effects and persists an exact checkpoint reference.

Before accepting a writer result, verify base ancestry and every path touched by every introduced commit against the original portable claim. Successful computation is not integration: accepted results remain in the durable integration queue. Before a shared-ref effect, the single integrator must persist a one-shot integration intent binding both the observed shared HEAD and intended integrated HEAD; unknown publication outcomes retain that claim. For Git publication use `GitLaneIntegrationPublisher` with the trusted remote identity: it verifies fast-forward ancestry, requires the authoritative remote to match the observed HEAD, uses an exact-head lease as the CAS primitive, and performs exact readback. `GitLaneIntegrationVerifier` is read-only evidence (`conditional_update=false`) and cannot close the queue by itself. Remove a result only on `conditional_update=true` evidence for the exact intent with no history rewrite. Any active/runnable lane, unknown effect or unintegrated required result keeps project completion nonterminal.

Treat scheduler watchdog objects as replaceable materializations of durable desired state. Use `scripts/watchdog_survivability.py` for evidence-only health classification and `scripts/watchdog_survivability_runtime.py` only with an actually authorized scheduler backend and durable CAS store. Missing, disabled, overdue, configuration-drifted, duplicate and flapping watchdogs are explicitly classified. Recovery is gated by fresh owner/guard/external/pause evidence and explicit owner authorization.

Missing or configuration-drifted watchdogs are recreated with a newer generation before scheduler I/O only when the current materialization is non-running; old generations are fenced. A running materialization is never destructively replaced for config drift/flapping and is never kicked again merely because a timestamp is old. Its disabled schedule may be enabled without creating a second run. Lost/unknown create or run outcomes are observed and reconciled, never blindly replayed. Duplicate materializations are quiesced only after the canonical generation is known and repairs remain bounded.

When Fleet supervision has an authorized survivability runtime, compose it with `scripts/fleet_watchdog_runtime.py`: assess every registered desired watchdog, share one bounded effect budget across survivability and ordinary wake recovery, and retain any deferred/broken repair as continuation work. An unresolved scheduler effect blocks desired-generation replacement. A fresh explicit owner pause/stop or exact project-terminal proof suppresses self-heal. The current owner-paused scheduler policy remains authoritative.

Protect the Fleet Supervisor itself with `scripts/watchdog_sentinel.py` when an independent scheduler capability exists. The sentinel targets only the durable `fleet-supervisor` desired-state role and may recreate/enable/wake that materialization through the same authorized survivability runtime; it is not a second Fleet controller and has no product-write authority. Keep the sentinel on an execution plane independent from the Fleet Supervisor when the host supports one. Cross-provider HA for the sentinel is deferred beyond 2.11.2.

Read `references/cooperative-project-lanes-and-watchdog-survivability.md` before project-lane admission or survivability recovery.


## CDC 2.11.3 multi-subscription ownership integrity

Multiple ChatGPT subscriptions may observe/orchestrate the same Fleet, but Fleet-wide side effects are single-leader. **New execution-lease/v2 ownership is admitted only for the package-managed execution surface.** Ordinary ChatGPT chat, Work, Codex, watchdog/API labels without that package-owned terminal boundary are observer/orchestrator-only and must not acquire a persistent lease. This is the fail-closed fallback when the host exposes no mechanically interceptable final-response channel. Use `scripts/fleet_supervisor_control.py` on a dedicated CAS document to elect exactly one **Fleet Supervisor leader** bound to `execution-lease/v2`, the authoritative Fleet ref, generation and invocation. Standby supervisors may observe/plan or act as ordinary project executors, but they cannot emit Fleet writes, wake/repair requests or continuation-enqueue effects without the leader claim. Fleet leadership itself follows the same transactional finalization: drain → checkpoint → reconcile all outer Fleet effects → ready → `release_leader_cas()`. An unresolved claimed/submitted/unknown Fleet effect blocks reconcile/release. Every Fleet effect gets a one-shot deterministic canonical SHA-256 `effect_id` from kind + target + intent + exact observed Fleet HEAD; callers cannot invent alternate IDs. Duplicate intent is observed/reconciled and moved HEAD replans. Unknown/submitted effects block leader replacement. A standby may reconcile an old effect only from exact authoritative provider observation bound to the original effect ID/intent; it cannot submit or replay it. TTL alone never grants leadership takeover.

For truthful status use `scripts/execution_liveness.py`. A lease owner is **not** automatically active: `active` requires exact independent **fresh** runtime-running evidence plus lease freshness; stale running observation degrades to `unknown`. Exact stopped runtime with no pending effects is `orphaned_recoverable`; stopped runtime with pending writes/guard/**unresolved** current-generation submission effects is `blocked_unknown_effects`. Submission claims remain append-only audit/idempotency history, while terminal provider reconciliation appends an exact `submission_resolution` so resolved claims no longer masquerade as pending; unproven runtime is `unknown`; no owner is `released`. Classification is evidence only and never grants takeover.

Immediately before any terminal/final response use `scripts/final_response_gate.py`. If this invocation acquired a lease, the gate requires an immutable `execution-release-receipt/v1` captured from the exact release revision for that owner/generation/invocation, plus post-release execution-continuity evidence. Do not rely on the current mutable `last_release`, which a successor generation may replace. Use `execution_lease_v2.release_cas()` (the CLI `release` command uses it automatically) and persist its `execution-release-receipt/v1` output. Before allowing final response, re-read `receipt.lease_revision` through `GitLeaseStore.read_revision()` and require the historical released record to match the receipt exactly. A pre-release `ready` state is insufficient. This makes an orphaned owned lease a failed executable terminal check rather than a prose warning.

Watchdog survivability `create/enable/run/disable` effects use the same pinned Fleet leader binding and recheck it immediately before provider I/O; leader/HEAD loss before I/O is blocked, not recorded as an unknown provider effect.

Consumer CDC adoption is atomic. Use `scripts/consumer_adoption.py` with detached migration assembly: prepare the immutable package, lock, adapter, checkpoint and adoption/provenance paths off the shared source ref; bind every required path to an immutable Git object in the assembly manifest; include the manifest digest in the publication claim/journal; verify consumer-lock version/package-tree/release bindings plus the exact target package subtree and candidate root tree; then perform one conditional fast-forward and exact readback. VERSION-only or metadata-only shared-ref exposure is not a valid adoption state. Read `references/multi-subscription-coordination-and-ownership.md`.


## CDC 2.11.4 managed host bridge

When a host needs to turn observer/orchestrator intent into actual project execution, use `scripts/managed_host_bridge.py` rather than weakening the 2.11.3 lease admission rule. The bridge launches the exact package-owned `ManagedExecutorRuntime`, acquires execution-lease/v2 only through its live non-serializable managed-terminal capability, and returns an opaque durable handle to the host.

The v1 host contract is `start → observe|cancel → finish`. `start` verifies exact repository/remote/source HEAD and an immutable single-task writer or read_only managed-pool plan before effects, holds the real worker behind a package-owned gate until managed lease acquisition is durable, and never publishes the shared source ref. `observe` and `cancel` address only the exact durable task/attempt/launch and never replay a start. A successful writer `finish` requires the worker's managed `awaiting_release` state, verifies exact result ancestry/full-history write scope, and uses a durable expected-head conditional publication journal. A read_only finish instead requires a persisted result checkpoint and unchanged clean detached checkout/history/source HEAD, with no publication or product result commit. Both paths run transactional finalization/release, wait for supervisor quiescence, close the pool result, and validate the immutable release receipt through the final-response gate.

For CDC projects Codex Cloud is the owner-preferred environment for eligible portable compute, including public repositories. The default cost policy sets `portable_primary_preferred=true`; transient Cloud failures recover or wait. Required platform/release CI remains a separate evidence gate. Use `scripts/codex_cloud_cli.py` for supported CLI submit/observe/recovery and explicit host-observed report ingestion. Its durable journal prevents repeat dispatch after a lost reply, but grants no ownership, budget or submission authority. Supply a live callback rechecking the existing exact one-use claim/guard/budget/source immediately before exec. Provider READY means waiting_report, never PASS. Read `references/codex-compute.md` for the supported CLI and report boundary.

Hosts may wrap this JSON contract as a ChatGPT plugin/tool, Work adapter, scheduler adapter or another service. The package does not infer that such transport is installed. `LocalCommandBackend` remains cooperative and inherits the invoking host's privileges; the host must apply its own command/user/repository authorization before supplying argv. Read `references/managed-host-bridge.md`.


## Taskless submission recovery

After an authenticated pre-acceptance GitHub 403 or an immutable cancellation-before-send barrier, use `scripts/submission_recovery.py` on an explicitly released v2 lease. The barrier path also supports `COMPUTE_ONLY` on `codex_cloud_cli` with the entire original execution binding pinned in its exact target. Independently authenticate, persist and read back the exact provider, worker and parent-dispatcher evidence first. Empty provider results, a missing grant, elapsed time, a cancellation request or a lost reply alone never clear an operation. Never reconstruct a missing historical barrier from a traceback. The canonical CAS preserves the original claim and release history, appends its resolution and grants no submission authority. Released records are sealed against ordinary rewrites; new ownership still requires the managed terminal capability. See `references/submission-recovery.md`.

## Compatible managed finish recovery

For the verified 2.11.6 stale-finish defect, follow references/managed-host-finish-recovery.md. A verified immutable corrected controller may finish the same held handle without replacing the consumer package or owner. Ordinary atomic adoption remains gated on release and quiescence.

## Codex Cloud Development and transitioned guards

Cloud Development is a separate scoped editing contract returning an existing managed handoff; COMPUTE_ONLY remains read-only. Provider READY waits for an observed report. Unknown submissions retain guards and reservations. The conditional lease store binds a terminal resolution to the original consumed claim digest and terminal evidence to the current transitioned guard digest, while retaining full canonical clear_guard equality, immutable history and unrelated-field rejection. See references/codex-compute.md.

## Explicit separate canonical release evidence

Use live-target-release/v2 only with an exact canonical evidence endpoint identity, stable ref, pinned commit and derived evidence path. Never substitute current main or relabel old metadata as a current snapshot. Recheck registry/release/evidence refs, ancestry, exact package/version and released evidence before returning. Legacy v1 remains strict colocated-only. Resolution grants no Fleet/adoption/scheduler authority; see references/live-target-resolution.md.


## Quality levels and evidence reuse

Use the explicit project quality policy and risk assessment before selecting checks. Missing quality settings preserve legacy behavior; new templates recommend MEDIUM. Record the effective level and escalation reason in the existing durable checkpoint/continuation record. Required platform/product/release and authority gates remain mandatory.

Reuse verified test results while dependencies, command, parameters, check definition and relevant environment are unchanged and independently justified coverage is recorded. Preserve the original candidate SHA and evidence reference. Use evidence-reuse/v1, verification-gate/v2 and branch-finish/v2 explicitly; v1 exact-SHA semantics remain unchanged. Fresh source/ownership observations are not reusable test results. Report-only edits do not invalidate unrelated product evidence. A released package adoption needs exact installation/compatibility evidence, not an automatic rerun of its unchanged full package suite.

Before repeated validation use validation-cycle/v1 through quality_levels.py. A repeat needs changed inputs, concrete risk and why the prior proof is insufficient. Default budget permits two cycles; exceeding it requires a revised strategy. Budget exhaustion never grants a waiver or resets historical usage. Carry time/token/start observations and unknown metrics honestly. See references/quality-levels.md.

