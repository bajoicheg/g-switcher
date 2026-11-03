---
name: continuous-development-cycle
description: Use when substantial software development must continue across long sessions, interruptions, CI runs, repository migrations, watchdog resumes, development chat cleanup, Work/Codex orchestration, Codex Compute setup or failures, or limited compute budgets.
---

# Continuous Development Cycle v3.6.17

This 3.6.17 candidate adds explicit opt-in bounded immutable task storage on
GitDocumentStore's original native channel. Legacy mode retains its 4 MiB bound;
opted-in reads reconstruct all original control task rows through mixed history.
Original IDs, UNKNOWN, budgets/spent, typed authority and single-parent CAS stay
strict. Read `references/task-sharded-control-storage.md` before enabling storage;
no old pinned actor may still act at activation. A live native same-boot proof
of the exact already released SUCCEEDED writer may preserve terminal_pending
unchanged while only registry pins and physical storage migrate; original metadata
completion then follows through the new runtime. Existing FAILED reboot recovery
stays strict and separate. Develop under released3.6.16.

This 3.6.16 candidate permits a provably different-birth foreign process reusing
only an original descendant PID in the explicit root-authenticated released
FAILED reboot route. Original process identity absence is recorded separately
from numeric PID reuse and revalidated at every use. Ordinary same-boot and
controller/worker/supervisor presence denials stay strict. Develop under released3.6.15.

This 3.6.15 candidate adds an explicit protected local-journal boot transition
for an already failed and genuinely released original invocation. Ordinary
terminal verification remains strict. Read `references/released-crossboot-recovery.md`
only for that recovery; root historical host evidence alone grants no terminal,
lease, replay, publication or refund authority. Develop under released3.6.14.

This 3.6.14 candidate adds bounded legacy guardian prehandle UNKNOWN retirement
through the existing sealed proof and fresh physical/source barriers. It retains
all IDs, history, reservations and spending. It invents no consumption or
NOT_SENT assertion. Developed under independently released CDC 3.6.13.

This 3.6.13 candidate accepts the bounded legacy preconsume rejection-site
diagnostic as documentary evidence, retaining all original custody, digest,
independent-channel, UNKNOWN and spending checks. It adds no terminal, refund or
resend authority. Developed under independently released3.6.11.

Historical3.6.12 documentation-only candidate makes the persistent execution contract
the common entry for every CDC-managed project and resumed operation, developed
under independently released 3.6.11. The user need not restate identity/history
preservation, bounded UNKNOWN recovery, evidence reuse, minimum coordination and
actual spending in each task. Runtime algorithms, provider eligibility and
mandatory release/authority gates are unchanged. Preparation, qualification,
native release, installed runtime and consumer adoption remain separate facts.

Historical 3.6.11 adds the qualified optional pinned decoder-only acceleration, developed under independently released 3.6.10. The original canonical encoder, strict error fallback and history/authority gates are unchanged. The CPython3.12 manylinux x86_64 wheel is bundled with its provenance and licenses; unsupported platforms retain stdlib.


Historical3.6.10 composition: this prior candidate consolidates qualified native history transport/reuse, original UNKNOWN recovery, operational budget bounds and successful-preparation rejection closure over independently released 3.6.9. It is developed under released 3.6.9. Provider eligibility, account configuration and host containment remain separate. No host policy, prior IDs, UNKNOWN, budgets or spending are rewritten by this package.

The prior release descriptions below are retained history.

The 3.6.9 candidate adds provider-neutral Codex/Gemini/Kimi agent tasks while
retaining the released 3.6.8 native recovery and history controls below. Read
`references/agent-workers.md` for model/check/review boundaries. Actual provider
eligibility and host containment remain independent admission requirements.

This 3.6.8 patch reconciles only the original live controller’s issued consumption
proposal after a lost acknowledgement. A fresh typed SDK observation may confirm
that exact proposal or prove a pre-effect retry safe; an unresolved send stays
UNKNOWN. Strict hash-bound creator guardian waits remain documentary and never
grant worker terminal authority. It retains the 3.6.7 patch that stores bounded process-local immutable history compactly and authenticates
retired intake rows in one fresh snapshot. Fresh endpoint/ref/head, complete
linear ancestry, UNKNOWN history and native capabilities remain mandatory. It
retains the 3.6.5 patch that eliminates repeated accumulated-prefix copying during private
budget validation replay. Every event check, denial and public deep-copy
isolation contract remains enforced. It retains the 3.6.4 patch that authenticates unconsumed guardian bootstrap-failure streams
and monotonic original project-budget preparation receipts. It preserves UNKNOWN, charges,
independently authenticated Root/project channels, protected preconsume custody,
all native absence/consumption barriers and replay exclusion. It also authenticates retained-project observation from the pinned
Source-selected original native interval while preserving older blobs as
non-authorizing history. It includes the 3.6.1 native UNKNOWN recovery fix when an interrupted original
controller has not saved its informational writer result. Fresh native accepted
result and original release custody remain mandatory. Native administrative
recovery covers source publications and prelaunch intake. Distinct sealed capabilities authenticate
original custody and forbid replay without inventing terminal outcomes or refunding
charges. Developed under independently released 3.6.8. Legacy raw command streams,
actual exits and truthful negative closeout remain supported. The executable floor
stays 3.3.0; ordinary terminal, lease, budget and one-use authority remain enforced.
Existing strict administrative Actions UNKNOWN quarantine remains unchanged.
Missing transport cancellation proof remains UNKNOWN; native evidence and CAS
retire only the exact read-only pilot without replay or a new submission grant.
Load `references/unknown-retirement.md` only for that authorized recovery phase.
For explicitly authorized native source publication quarantine or prelaunch intake
disposition, load `references/native-unknown-recovery.md`. Its separate sealed
capabilities preserve UNKNOWN, charges and history; they never supply a launch,
wait, provider terminal result or conditional Git confirmation.
Version labels identify bytes; source release, saved activation and adoption require
separate evidence. Load only current phase references; history remains linked.

## Start and resume

Read and apply the persistent contract in `references/lean-execution-core.md`
at every project entry and continuation, including existing projects. This is
the central working contract; a missing repeated user reminder does not disable
it. Project checkpoints reference it rather than copying a second policy.

Verify the independently released runtime actually loaded: VERSION, manifest,
installed bytes and canonical release evidence must agree. Develop a new CDC
candidate under that released driver. Minimum executable runtime is 3.3.0;
older records remain readable data, not executable authority.

Read current applicable instructions, adapter and compact checkpoint/capsule.
Reuse qualified unchanged observations; refresh source identity/ref/HEAD, policy,
ownership, external operation, budget and required evidence when changed or
when the next action requires a fresh admission. Live observations override history.
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
Source/ownership observations remain fresh per action. Use the minimum sufficient
cycle; a repeat requires changed inputs or a concrete uncovered risk, with an
insufficient-prior-proof reason; after two
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
`[HH:MM DD.MM]` timestamp for EACH substantive progress, blocker, continuation
and final report. Read the runtime clock at the emission boundary; never infer
minutes from previous updates. Use no timezone suffix or seconds. After a completed logical
operation append rounded whole minutes, e.g. `(4 мин)`. Add tokens only from a
measured counter with provenance; mark unavailable scope, tokens and money
UNKNOWN with a reason. Count monotonic totals over the stated measurement window,
each distinct child once, App/native/provider separately; cached input and
reasoning are subsets of input and output. Never sum cumulative snapshots or
invent zero. `scripts/operation_report.py` retains
observed phase times and outcomes. Worker-duration sums are consumption, not
wall time; no unobserved speedup, savings or quality improvement claims.

## Review, release and adoption

Independent review follows the actual project/release admission contract;
critical work retains required ordered independent reviews. Do not launch an
extra reviewing model or control from self-distrust. Verify actual evidence before success
claims. Freeze an exact release-candidate SHA and use the release phase for
bootstrap, package, compatibility, fault, supported-consumer and final CI gates.
Source release, installed runtime and consumer adoption are separate states.
Adoption requires an exact released package, released/quiescent ownership,
reconciled guards and preserved budgets/history. An explicit Fleet rollout
pause is binding; supported-consumer tests do not deploy live consumers.

## Unknown isolated Git submission

Use `references/unknown-retirement.md` only for explicitly owner-authorized administrative isolation of an original returned create-only pilot Git submission on a physically released/quiescent v2 lease. Outcome stays UNKNOWN; do not invent provider terminal evidence or replay the candidate. For native source publication quarantine (including claim-null guards) or
prelaunch intake disposition, use `references/native-unknown-recovery.md`.
The original row CAS competes with a one-use start consumption; every controller
and guardian must enforce that barrier, and old dispatch actors must be stopped.
Retired contracts/candidates remain permanently excluded from native admission.
Other unknown effects retain normal reconciliation.

For existing project task adoption, use `references/project-budget-store.md`
and `references/project-adoption.md`. Authenticate the original policy authority
and native release before constructing protected registrations. Retain original
task ledgers, charged UNKNOWN agents and remaining Windows or real AD work.
Append admission events through the original native budget store, then obtain a
fresh sealed adoption observation. Adoption grants no launch, terminal proof or
product acceptance; native lease, pool and one-use start gates remain required.

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
Load `references/systemic-closeout.md` for native current report, continuation,
RCA admission, receiving CI and detached-result boundaries. `closeout` uses
terminal-bundle/v2 and the original managed handle, canonical lease/pool history,
actual journal and birth-bound fresh PID absence. Caller booleans are observations,
not terminal authority. Open/deferred RCA stays visibly open.
`audit-tests` reports duplicate candidates for distinct-risk review, never deletes
tests. Operation-observation/v2 records context, coordination, finish and repeats
with explicit unknowns; compare equivalent actual workloads before claiming savings.
