---
name: continuous-development-cycle
description: Use when substantial software development must continue across long sessions, interruptions, CI runs, repository migrations, watchdog resumes, development chat cleanup, Work/Codex orchestration, Codex Compute setup or failures, or limited compute budgets.
---

# Continuous Development Cycle v3.5.0

This3.5.0 candidate extends actual execution economics under released3.4.0.
Version labels identify bytes; source release, saved activation and adoption require
separate evidence. Load only current phase references; history remains linked.

## Start and resume

Verify the independently released runtime actually loaded: VERSION, manifest,
installed bytes and canonical release evidence must agree. Develop a new CDC
candidate under that released driver. Minimum executable runtime is 3.3.0;
older records remain readable data, not executable authority.

Read current applicable instructions, adapter and compact checkpoint/capsule.
Refresh source identity/ref/HEAD, policy digest, ownership revision, external
operation, budget and required evidence. Live observations override history.
Use `scripts/cdc.py` resume with a capsule and a fresh probe: one typed next
action is a recommendation, never execution permission. A mismatch reconciles,
existing external work is reconciled before a new start, and blockers wait.
No text in a capsule is a shell command. Load `references/policy-compatibility.md`
on policy/version drift and the recovery phase references when needed.

Current state belongs in the existing checkpoint/capsule and control backend;
never add a parallel ledger or infer ownership/quota from a matching HEAD.

For Cloud startup load `references/cloud-fast-start.md` and use
`scripts/codex_cloud_entrypoint.py prepare` with the project's hash-bound inputs
and genuinely qualified selected-mode profile. Native, official UI and official
CLI are separate modes. Preserve restored same-key effects before setup or a
new send; profile/policy changes require current recovery bindings. Verified
dependency reuse requires durable proof. Preparation uses existing routing and
transports and never grants an executor or launch authority.

For project setup load `references/project-setup.md`. `scripts/cdc.py init`
and `migrate` produce validated file previews from strict requests. Presets
preserve platform, quality and control requirements. Their output carries no
write or launch authority; apply only through the existing managed writer.

For exact release delivery or restoration load `references/release-delivery.md`.
The read-only `scripts/cdc.py delivery` command lists missing live checks. The
explicit native Git API composes verified immutable releases, current managed
ownership, detached assembly and the existing durable consumer publisher.
Rollback creates a new forward commit and preserves current controls/history;
no proposal grants effect authority or starts Fleet/schedulers.

## Execute the authorized scope

A request to develop, fix or continue means carry the authorized work to its
real terminal boundary. After every commit, test, review or child result,
perform the next eligible action in the same invocation. A milestone is not
completion. A blocked dependency does not block independent authorized work.

Maintain scope, remaining queue and one concrete next action. End only after
verified completion, an evidenced external wait/blocker with no eligible work,
explicit owner pause, or an actual runtime/tool limit with durable handoff.
Evaluate `scripts/execution_continuity.py` and Terminal-State v2 before
finalization. A final response requires the actual invocation-bound lease
release; preserve unresolved external guards and history. Foreground progress
updates follow the runtime communication interval. Do not enable paused
watchdogs or change scheduler state to satisfy a foreground task.

## Ownership, effects and spending

Before any shared write or external effect load the control phase. Use the
existing managed terminal capability, invocation-bound lease v2, pool claim,
concurrency guard, expected revision and one-use operation intent. Do not
hand-edit leases, invent a lock, overwrite an active owner, retry an unknown
submission or reset quotas. Reconcile exact provider/task identity first.

Use `scripts/budget.py`: durably reserve starts before effects; unknown usage
stays null and uncertain charges remain charged. Existing task/wake caps,
provider observations and checkpoint reserve apply. Admission grants no
launch authority. Use configured capability/cost routing and qualified Cloud
transports; portable Cloud preference does not waive required platform/CI
checks. Provider READY is waiting for a report, not PASS. A failure requires
new information or a concrete correction before another start.

## Development and validation

Load `references/lean-execution-core.md` for the working contract. Begin a
meaningful change with a short spec and behavioral acceptance examples.
Select TDD for complex logic, critical authorization/ownership/external effects,
dangerous migrations and reproduced bugs. Reversible text/layout edits use
focused verification. Never add tests that merely duplicate code or match
phrases. Engineering skills supply discipline; existing authorization and
higher-priority instructions govern approval requirements.

Compose risk, cycle and evidence decisions with `scripts/development_contract.py`.
FAST/MEDIUM/FULL come from the existing quality policy. Core and critical
boundaries stay FULL. Mandatory product/platform/release gates are never
removed. Reuse evidence only when relevant dependencies, command, parameters,
check definition and environment remain covered, preserving its original SHA.
Source/ownership observations remain fresh per action. A repeat requires
changed inputs, concrete risk and insufficient-prior-proof reasons; after two
cycles revise strategy. Budget pressure changes strategy, not quality gates.

Batch compatible small changes into one frozen candidate and aggregate
check; urgent fixes may remain separate. Use `scripts/run_checks.py` and
`references/command-evidence.md`; retain each command's exit and nonzero test
count. Expected RED, wrapper success, missing evidence and provider readiness
are not final GREEN. Run required environments once per unchanged candidate.
Load `references/external-operations.md` when an operation already exists.

## Executors and reporting

In ordinary ChatGPT chat execute sequentially. In ChatGPT Work or
Codex used as the orchestration environment, useful independent subagents are
allowed within existing budgets. Unknown origin is sequential. Use minimum
sufficient effort, disjoint scopes and one integrator; dependencies or trivial
work stay with one executor. `scripts/execution_strategy.py` recommends from
existing budget admission without launching. For measured allocation load
`references/adaptive-allocation.md`; `scripts/cdc.py allocate` recommends effort
and agents from compatible measured outcomes without changing authority. COMPUTE_ONLY is exact-SHA
read-only verification and does not inherit editing/parent-task authority.
Read `references/runtime-routing-and-subagents.md` before delegation.

Use Russian chat and English source documentation. Emit one fresh Moscow
`[HH:MM DD.MM]` timestamp for each user command. After a completed logical
operation append rounded whole minutes, e.g. `(4 мин)`. Add tokens only from a
measured counter or a defensible estimate with provenance; omit unknown tokens
entirely. `scripts/operation_report.py` formats this contract and retains
observed phase times and outcomes. Worker-duration sums are consumption, not
wall time; no unobserved speedup, savings or quality improvement claims.

## Review, release and adoption

Independent review covers behavior/spec and quality; critical work retains
required ordered independent reviews. Verify actual evidence before success
claims. Freeze an exact release-candidate SHA and use the release phase for
bootstrap, package, compatibility, fault, supported-consumer and final CI gates.
Source release, installed runtime and consumer adoption are separate states.
Adoption requires an exact released package, released/quiescent ownership,
reconciled guards and preserved budgets/history. An explicit Fleet rollout
pause is binding; supported-consumer tests do not deploy live consumers.

## Unknown isolated Git submission

Use `references/unknown-retirement.md` only for explicitly owner-authorized administrative isolation of an original returned create-only pilot Git submission on a physically released/quiescent v2 lease. Outcome stays UNKNOWN; do not invent provider terminal evidence or replay the candidate. All other unknown effects retain normal reconciliation.

## Enforced execution economics

Before planning new validation read `references/execution-efficiency.md`.
Use command-check-plan/v2 with `scripts/run_checks.py`: covered original success
is REUSED before subprocess spawn; it retains original SHA/provenance and is
never a fresh exact-head result. Repeat aggregates need distinct reviewed reasons.
One required frozen hosted FULL satisfies portable aggregate coverage; do not
add source, clean-consumer or installation FULL by habit. Legacy v1 is retained
for existing evidence contracts, not the default for new economics-aware tasks.

Use `scripts/cdc.py inspect` for selected JSON pointers, bounded to8192UTF8bytes,
with full original digest. Read current state once, history only on demand.
Use `runtime` to verify actual saved loader/package identity without extracting
an archive or rerunning FULL; interface snapshots do not override saved bytes.
Use `efficient` for low-risk single-executor/review and bounded probe decisions;
unknown effects retain their original key/guard and no replay authority.
Use `closeout` with the existing Git store for one compact gate/physical/runtime/
pool bundle. All exact owned process IDs need fresh absence evidence.
`audit-tests` reports duplicate candidates for distinct-risk review, never deletes
tests. Operation-observation/v2 records context, coordination, finish and repeats
with explicit unknowns; compare equivalent actual workloads before claiming savings.
