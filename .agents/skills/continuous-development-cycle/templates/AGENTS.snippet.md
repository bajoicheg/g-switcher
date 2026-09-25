<!-- continuous-development-cycle-v2:start -->
## Continuous Development Cycle v2.7

For substantial implementation, resume, release, repository migration, or watchdog work, load the installed/repo-local `continuous-development-cycle` skill.

Before coding, reconcile:
1. repository identity and remote HEAD;
2. `docs/development-cycle.yaml`;
3. `docs/work-status/current.md`;
4. active specification/task fingerprints and relevant bodies (skip unchanged long material only after a complete fresh recovery probe);
5. PR/CI/compute/release state.

Follow the instruction hierarchy and reconcile existing user authorization with repository policy. Remote facts override stale checkpoint/chat claims about state.

Subagents depend on orchestration origin: ordinary ChatGPT chat = disabled; Work or Codex orchestration = explicitly enabled by default with adaptive minimum-sufficient effort. This instruction requests useful independent delegation in Work/Codex without additional per-launch approval, subject to higher-priority instructions and explicit task restrictions. Keep one integrator and isolated writers; continue sequentially if tools/quota are unavailable. Do not confuse Codex orchestration with a read-only `COMPUTE_ONLY` backend.

Prefer configured, authorized Codex Compute for eligible exact-SHA build/test/lint checks, even when a local runtime exists. Follow the skill's `references/codex-compute.md` to establish access, environment, request/task binding and terminal evidence; retain the project runbook in `docs/codex-compute.md`. Use cheap local preflight/short debugging loops or a justified fallback; preserve required platform gates and Actions budgets.

Do not stop merely because a commit, compute result, CI launch, checkpoint, review, or one task completed. Continue until configured work/release gates are complete, a real blocker exists, or runtime/tool limits force a durable handoff.

Validate adapter and checkpoint v4 using `scripts/validate_adapter.py` and `scripts/validate_checkpoint_24.py`, reconcile version or policy-digest drift with `references/policy-compatibility.md`, and preserve the source/scope of existing user authorization. Before external submit, persist/read back an operation intent; after a lost reply reconcile the existing task. Unknown submission outcome retains the external guard despite lease expiry. Require per-command `command-evidence/v1` bound to the expected plan, SHA and environment; a successful wrapper, NOT_RUN or EXPECTED_RED is not final GREEN.

Apply the skill's `references/orchestration-controls.md` before shared mutations or external starts. Use invocation-bound execution-lease/v2 with a unique executor UUID, exact invocation ID and generation, or a verified designated single writer; expiry alone never permits takeover. Existing owned v1 leases migrate only after release/quiescence. Git submissions require a fresh one-use claim; restored submitting/unknown records only reconcile. Bound waits and reserve task/wake spending before effects, preserving checkpoint resources and unknown charges. Always read actual current instructions on resume. Use `scripts/resume_capsule.py` only for exact-match fast resume. Before any final response, pass `scripts/execution_continuity.py`, complete transactional finalization (drain/checkpoint/reconcile/ready), and release the exact owned invocation-bound lease.
Before choosing a compute/CI/backend, route an explicit capability request through fresh backend evidence with `scripts/capability_router.py`; routing never authorizes launch. For known failure classes, prefer `scripts/recovery_recipes.py` deterministic allow-listed recovery before open-ended RCA. Drain/claim durable continuation events with `scripts/continuation_queue.py`; an event wake/claim is delivery only, not ownership. Immediate event wakes are preferred where supported and the recurring watchdog remains the scheduler fallback.
Publish/refresh a `fleet-project-snapshot/v1` on the coordination plane when project state materially changes. Fleet Supervisor assessment, version convergence and progress SLO are diagnostic/control-plane only; they never grant product writes, takeover, external starts, merge, release or scheduler mutation. Version adoption waits for released/quiescent ownership and a cleared guard. Primitive activity never resets the meaningful-progress SLO. Append important control-plane transitions to the hash-chained audit log without treating the audit record as authority.
Before chat cleanup or watchdog recovery, reconcile the canonical task-to-conversation binding. Protect its verified chat dependencies; follow the archive prevention/recovery procedure in `references/watchdog-recovery-and-migration.md`. A successful unarchive or enabled flag alone is not recovery: require a fresh completed run, visible result, and preserved enabled schedule.
For watchdog/status/resume, build the six-signal health vector (scheduler, chat, invocation, lease, external operation and meaningful progress) with `scripts/watchdog_health.py`. Treat its result as diagnostic only; it never grants takeover, writes, external starts, scheduler mutation or budget restoration. Persist a changed health fingerprint only on an authorized coordination path without moving a guarded product HEAD.
<!-- continuous-development-cycle-v2:end -->


Canonical CDC core is an immutable released dependency. Keep a validated
`cdc-consumer-lock/v1` binding to canonical repository + version + release ref +
release commit + exact package tree. Local edits inside the vendored core are drift.
Advance the lock only at a safe ownership boundary with no unresolved external guard,
while preserving budget, validation and audit history.


Human interaction is not an execution backend. Missing GitHub/connector/API methods are capability gaps, not implicit approval gates. Prefer durable event triggers, alternate authorized backends or policy-safe workflow changes before asking the owner for a mechanical action. Escalate only for genuine human authorization/judgment, unavailable secrets, protected approvals or external systems with no authorized automation route.


Bare user continuation commands such as «продолжай», «продолжи» or “continue” mean continue the current authorized scope to terminal state. Do not stop after one status/read/commit/compute step. Terminal state is verified scope completion or a real durable blocker/handoff with exact evidence and next action. Explicit narrower user qualifiers and all normal guards still apply.

Cost routing is visibility-aware. Public repositories may classify standard GitHub-hosted Actions as unmetered/normal compute; private/internal repositories retain Codex-first economics and expensive-Actions fallback controls.
