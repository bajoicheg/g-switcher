# Continuous Development Cycle v2.11.9

Installable ChatGPT/Codex/agent skill for recoverable, long-running software development.

## Install in ChatGPT

Upload the ZIP containing this folder through the ChatGPT Skills UI. The ZIP root contains exactly one skill folder, `continuous-development-cycle/`, whose entry point is `SKILL.md`.

## Repository bootstrap

For a project that should persist the policy in Git, copy:

- `templates/development-cycle.yaml` → `docs/development-cycle.yaml`
- `templates/work-status.md` → `docs/work-status/current.md`
- merge `templates/AGENTS.snippet.md` into `AGENTS.md`
- use `templates/watchdog-prompt.md` for a scheduler/watchdog wake prompt

Edit repository-specific commands and policies before relying on the adapter.

## v2 highlights

- durable recovery from GitHub/repository facts;
- ordinary chat runs without subagents;
- Work/Codex orchestration explicitly enables useful subagents by default without per-launch approval;
- adaptive minimum-sufficient subagent effort, not blanket maximum;
- strict separation between Codex orchestration and Codex `COMPUTE_ONLY` backend;
- visible long-run progress updates;
- priority Codex Compute with reusable access/environment/request setup and explicit CI budget states;
- repository migration identity checks;
- watchdog recovery state machine;
- conditional execution ownership with explicit release or verified quiescence and `waiting_external`;
- exact-SHA release candidate and artifact discipline.

## v2.2 contracts

Adapter/checkpoint v3 add versioned policy and strict YAML validation. Versioned check plans produce per-command JSON evidence. External intent records protect interrupted submissions. See `references/policy-compatibility.md`, `references/command-evidence.md` and `references/external-operations.md` for migration and CLI usage.

## v2.3 orchestration controls

- Conditional Git coordination serializes ownership and one-use external submission claims; a designated single-writer fallback remains available.
- Separate queue/setup/run/unknown deadlines and backoff retain unresolved external guards.
- Fresh compact probes avoid rereading unchanged long material while always loading current instructions.
- A durable task/wake ledger reserves spending before effects, retains unknown charges and checkpoint resources, and requires concrete recovery before repeating a failure.

Use `references/orchestration-controls.md` to connect these controls. Existing adapter/checkpoint v3 and operation-intent/v1 records remain readable; enable the additive configuration through an explicit policy reconciliation. Run `python -B scripts/validate_package.py` and `python -B -m unittest discover -s tests` to check the package.

## v2.3.3 compute efficiency

- Higher Codex start capacity is spent for information gain, not identical retries.
- Compute failures are classified as setup, network, runtime or product before another start.
- Environment preparation reuses provider runtimes and uses missing-only dependencies, narrow package-source allow-lists and bounded provisioning instead of repeated heavyweight normalization.

## v2.3.4 watchdog lifecycle

Separate scheduler state from wake eligibility. Preserve recurring schedules through blockers and budget limits, honor verified user pauses, and audit unexplained drift without inventing its cause.


## v2.4 durable control plane

- Invocation-bound execution lease v2 prevents a different wake from renewing or releasing an owner's lease.
- Transactional finalization enforces drain → checkpoint → reconcile → ready → release before a final response.
- A durable resume capsule makes a chat/invocation/backend disposable while requiring exact live-probe agreement before fast resume.
- A hard execution-continuity FSM rejects primitive-only status/health/lease/poll/report completion while runnable work exists.
- Checkpoint v4 records execution continuity; v3 and released lease v1 remain readable for explicit migration.

Read `references/control-plane-v2.4.md`. Validate with `python -B scripts/validate_package.py` and `python -B -m unittest discover -s tests`.


## v2.5 routing and event continuation

- Capability-based routing chooses only freshly evidenced, compatible backends and never treats a route as launch authority.
- Deterministic recovery recipes turn known health/failure diagnoses into allow-listed bounded control-plane steps without repeated improvised RCA.
- A durable continuation queue deduplicates CI/compute/backend/scheduler/policy events, binds delivery to an invocation, and requests immediate wakes when supported; the recurring watchdog remains the fallback.

Read `references/capability-routing.md`, `references/deterministic-recovery.md` and `references/event-driven-continuation.md`.


## v2.6 fleet control plane

- Fleet Supervisor aggregates exact project snapshots without becoming a product writer.
- Version convergence binds version + package fingerprint + checkpoint schema and waits for safe ownership boundaries.
- Meaningful-progress SLO distinguishes real progress from heartbeats/status/polls and classifies degraded/stalled work.
- Hash-chained append-only audit records control-plane transitions and exposes tampering/drift.

Read `references/fleet-supervision.md`, `references/version-convergence.md`, `references/progress-slo.md` and `references/control-plane-audit.md`.


## v2.7 canonical source and independently bootstrapped releases

- One canonical CDC source repository owns release identity; product repositories are consumers, not alternative CDC source trees.
- Stable CDC N-1 develops N. A candidate may never be its only release validator.
- Release evidence is separated into bootstrap, package, compatibility, fault-injection and multi-consumer classes.
- Consumers pin canonical repository + version + immutable release ref + exact release commit + exact package Git tree.
- Local edits inside the vendored core are drift; product-specific policy remains outside the core package.
- Adoption waits for released or independently verified quiescent ownership and a reconciled/empty external guard.

Read `references/canonical-source-and-release.md`. Validate consumer pins with
`python -B scripts/consumer_lock.py <consumer-lock.json>`.


## v2.7.1 autonomy hardening

- Git lease storage is schema-aware and rejects malformed v2 ownership before CAS.
- A missing connector method is a capability gap, not a human approval gate.
- Mechanical execution should route through durable event triggers, compatible backends or policy-safe workflow changes before escalating to the owner.


## v2.7.2 cost-aware compute routing

- Codex Compute is the default low-cost primary backend for eligible portable checks.
- GitHub Actions is an expensive fallback and requires an explicit machine-readable reason.
- Transient/setup/provider Codex failures trigger bounded recovery/probe or `waiting_compute`, not automatic Actions spend.
- Another cheaper compatible backend is preferred before Actions.
- Product/test failure on Codex requires a product/test fix, not an expensive CI second opinion.
- Required platform capability, artifact production, release attestation, or independently confirmed provider outage can justify Actions.
- Backend degraded/unavailable state is re-probed after cooldown and can recover to ready.


## v2.7.3 terminal continuation and visibility-aware cost

- Bare «продолжай» / «продолжи» / “continue” means continue the current authorized scope to terminal state, not one primitive step.
- TS is verified completion or a real durable blocker/handoff with exact next action.
- Repository visibility is part of compute economics.
- Public repositories may treat standard GitHub-hosted Actions as unmetered and route to them normally.
- Private/internal repositories retain Codex-first cost controls and expensive-Actions fallback reasoning.


## v2.8.0 Autonomous Continuity & Isolation

- Terminal-State v2 makes No-Idle executable: runnable work forbids terminal response.
- Execution-channel supervision automatically fails over across compatible authorized backends.
- Concurrent-writer reconciliation replays non-overlapping fast-forwards on fresh HEAD and never force-pushes.
- Sensitive-context scanning covers organization/domain/topology leaks that secret scanners miss.
- Publication guard covers tree, refs, conversations, artifacts and control-plane paths.
- Internal control-plane state is excluded from the publishable product surface; findings require sanitized export.


## v2.8.1 Operational Hardening

- Watchdog self-repair restores delivery paths instead of accepting scheduler/chat drift.
- Ref hygiene and coordination retention bound temporary operational state.
- Blocker proof rejects stale or evidence-free BLOCKED terminal states.
- Decision authority removes unnecessary human prompts while preserving real human boundaries.
- Evidence compaction preserves durable refs and source digest.
- Progress enforcement turns degraded/stalled states into concrete continuation actions.


## v2.8.2 Fleet & Publication Maturity

- Project-independent fleet control drives normalized projects without becoming a super-writer.
- Stuck-state detection prevents repeated no-progress loops.
- Counterfactual recovery requires a new information-gaining strategy.
- Public publication uses sanitized export into new history, not direct visibility switching of internal development history.
- Dogfooding metrics measure CDC's own compliance without granting release authority.


## v2.9.0 Deterministic Distribution & Convergence

- Carrier-neutral package transport binds an independently trusted release version/commit/tree to path, Git mode and blob identity.
- Directory verification proves transported bytes; Git-subtree verification proves the consumer's vendored package tree is exactly canonical.
- The fleet convergence vector binds exact HEAD, package tree, consumer lock, semantic policy digest, checkpoint, lease, guard and adoption state.
- CI evidence is classified before remediation so pre-run/setup failures cannot be mistaken for product RED.
- Version equality alone can never produce integrated fleet state.

Read references/deterministic-distribution-and-convergence.md.


## v2.9.1 Transactional Migration & Provider Reconciliation

- Fresh-HEAD section-aware migration replaces canonical policy sections instead of appending duplicate keys.
- Schema-typed checkpoint builders validate v4 state before commit boundaries.
- Migration transactions reserve tool operations, chunk Git objects through detached trees and keep product refs unchanged until exact convergence.
- Terminal-provider reconciliation wakes the exact guarded operation while terminal provider state or TTL never grants takeover.


## v2.9.2 Continuous Autonomy & Learning

- Progress reports never terminate runnable work; execution continues until Terminal-State v2 permits a real boundary.
- Every user command in every CDC-managed chat gets one freshly observed Moscow timestamp in exact format `[HH:MM DD.MM]`; timestamps are never extrapolated from previous messages.
- Material RCA closes through one deduplicated, sanitized systemic fix disposition.
- Every Fleet Watcher run returns exactly one evidence-based improvement proposal or reinforcement.
- Dogfooding measures timestamp accuracy, premature-stop avoidance, feedback closure and improvement harvesting without granting authority.

## v2.10.0 behavioral skill TDD and verification

- Executable pressure-scenario suites retain a baseline RED and corrected GREEN trace for material CDC behavior controls.
- Systematic RCA requires competing hypotheses and discriminating evidence before selecting root cause and feeding the bounded roadmap disposition.
- Verification-before-terminal re-reads exact authoritative source/check/ownership/artifact state before COMPLETE, RELEASE_READY or INTEGRATED claims.
- The new quality gates are evidence-only and never grant product-write, takeover, merge, release, scheduler or scope authority.

Read `references/behavioral-tdd-and-verification.md`.

## v2.10.1 specification compliance and two-stage review

- Selective brainstorming is required only for genuine material ambiguity; clear authorized continuation does not gain a new approval loop.
- Specification requirements map to plan tasks and durable continuation items with explicit expected/completion evidence.
- Material changes require ordered independent spec-compliance then code-quality review.
- Branch finishing checks exact candidate HEAD, fresh validation, diff/spec reconciliation, review closure and exact-SHA checks before CDC terminal handling.
- Review/finishing gates are evidence-only and never grant merge or release authority.

Read `references/specification-review-and-finishing.md`.

## v2.10.2 worktree-isolated parallel development

- Parallel task waves are dependency- and write-set-aware; overlapping writers serialize.
- Delegated writers bind to isolated branches/worktrees and one exact base SHA; workers never write the shared integration branch.
- A single integrator reconciles terminal worker evidence and shared-HEAD movement; force-push remains forbidden.
- Observed benchmark evidence must show lower wall-clock time without conflict/rollback regression before safe parallelism is considered proven.
- Parallel controls are evidence/planning gates only and never grant launch, product-write, merge, release or scope authority.

Read `references/worktree-parallelism-and-integration.md`.

## v2.11.0 managed executor pool

- Parent-controlled, bounded executor pools provide Work-style delegation without transferring shared-branch, merge, release or scope authority.
- Durable CAS is the launch boundary: eligible in-memory queue state never starts a worker until the exact reservation wins the shared production store.
- Worker launch is capability-gated; unsupported runtimes execute the same plan through deterministic sequential fallback and never fabricate subagents.
- Writers use exact-base isolated branches/worktrees with portable write claims; one integrator owns shared-branch integration.
- Attempts/results are durable and preserve retry lineage; duplicate active launches fail closed.
- Content-addressed result handoff preserves completed worker work when direct push is unavailable; the integrator publishes and revalidates it without blind rerun.
- Independent work survives an unrelated worker failure.
- Required runnable/running work and every unintegrated successful result keep the parent non-terminal.

Read `references/managed-executor-pool.md`.


### Managed-pool final safety boundary

CDC 2.11.0 uses one authoritative coordination ref per pool and a one-shot durable launch CAS. Queue reservation alone cannot start a worker. Writer scope covers every path touched across the introduced history, required tasks cannot depend on omittable optional work, and remote publication is bound to a trusted immutable remote identity rather than a mutable remote name.

The executable adapter in `scripts/managed_executor_runtime.py` provides a real Linux command backend, restart-safe attempt observations, descendant-aware cancellation and managed-parent terminal evaluation. See `references/managed-executor-runtime.md`; the backend is cooperative process supervision, not a security sandbox. `scripts/active_package.py` separately verifies actually installed runtime bytes against a pinned canonical package.

## v2.11.1 liveness

Fresh registry/release target resolution and durable all-project watchdog recovery distinguish premature completion from project terminal state. Owner pause is an explicit overriding gate; unknown effects are never replayed. Actual scheduler adapters remain capability- and authority-gated.


## v2.11.2 cooperative lanes and watchdog survivability

CDC can coordinate disjoint foreground/watchdog/Work/Codex project lanes under one shared-branch integrator, while desired-state watchdog survivability detects and safely reconciles missing, disabled, overdue, drifted, duplicate or flapping scheduler materializations. Explicit owner pause remains authoritative.


## v2.11.3 multi-subscription ownership integrity

- One invocation-bound Fleet Supervisor leader owns Fleet-wide side effects; other subscriptions are standby observers or project executors.
- One-shot Fleet effect claims bind leader generation/invocation and exact Fleet HEAD, so duplicate wake/repair/enqueue attempts reconcile instead of replay.
- Independent runtime evidence distinguishes active execution from orphaned or unknown lease records.
- Persistent lease ownership is package-managed-only; ordinary ChatGPT/Work/Codex/watchdog/API surfaces without a mechanically enforceable terminal boundary are observer/orchestrator-only. Managed owners still require exact durable release proof before terminal completion.
- Consumer adoption binds every required path to an immutable assembly-manifest Git object, validates consumer-lock target semantics, then publishes once by conditional fast-forward and exact readback.

Read `references/multi-subscription-coordination-and-ownership.md`.


## v2.11.4 managed host bridge

- `scripts/managed_host_bridge.py` exposes a transport-neutral `start / observe / cancel / finish` contract around the real package-owned managed runtime.
- Hosts receive only durable handles; the non-serializable managed terminal capability remains inside the package.
- A package-owned worker gate prevents fast tasks from racing lease acquisition.
- Successful writer completion is exact-head conditional publication plus transactional lease release and immutable release-receipt verification.
- The bridge is a host adapter contract, not proof that a ChatGPT plugin/service is installed.

Read `references/managed-host-bridge.md`.
