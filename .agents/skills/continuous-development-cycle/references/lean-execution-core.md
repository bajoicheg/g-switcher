# Lean execution contract

The compact core routes existing control and quality contracts. It creates no
second orchestrator, budget ledger, release mechanism or authority grant.

## Persistent contract for every project

Apply this contract at every CDC-managed project entry and resumed operation.
The user does not need to repeat it in each task. Read it through the loaded CDC
package; project instructions and checkpoints reference this central contract.
Current user authorization determines scope and duration. This document grants
no new permission and never extends an expired work window.

- Preserve original task, attempt, handle, report and operation IDs, FAILED and
  UNKNOWN outcomes, guards, claims, reservations, budgets, spent and append-only
  history. Continuation never resets charges or quotas, refunds uncertainty,
  invents success or repeats an effect under a replacement identity.
- For UNKNOWN, perform one bounded reconciliation of available original facts.
  Safely finish or stop only the old uncertain execution through its supported
  mechanism and exclude a dangerous duplicate. Retain UNKNOWN where terminal
  proof is absent. If duplicate exclusion is impossible, stop only the dependent
  effect; continue independent authorized work. Never replay a one-use journal
  or CAS after an unknown reply; use original receipts to finish only the remainder.
- Reuse qualified evidence within its recorded scope and dependencies. Do not
  repeat completed acceptance, unchanged FULL, login, broad inventory or an
  unchanged probe for reassurance or reporting. Tests address a concrete
  objective risk or an actual project requirement. Exact-candidate, platform,
  authorization and independently mandatory release gates remain required.
- One actual executor carries a coherent preparation, edit, necessary-check,
  application and publication pipeline. Use references for a compact handoff
  when a real boundary requires it, and wait for the existing terminal signal.
  Do not add an observer, reviewing model, repeated verification or control
  mechanism because of distrust in your own work. Required independent project
  or release admission remains distinct from routine extra review.
- Before an effect, save a short result/time/resource/spending forecast in the
  existing plan. After the logical operation report the concrete applied result,
  proof, remaining UNKNOWN, measured rounded minutes and actual usage, noting
  material differences from that forecast. Preserve application, native, provider,
  canonical release and consumer adoption as separate evidence boundaries.
- Account from monotonic total-token counters over a stated scope/window, keeping
  App, native and provider observations separate. Count each distinct child once.
  Cached input is inside input; reasoning is inside output. Do not sum cumulative
  snapshots or add last-token counters again. Emit numeric counts only when
  measured; unavailable scope, tokens or money are explicitly UNKNOWN with a
  reason, never invented zero or a cost converted from quota.

Keep real Source, role, provider, lease, guard, expected-head and one-use limits,
secrets and inherited pauses. Use the existing runtime and records; this contract
does not introduce a guard, ledger, daemon, scheduler or orchestrator.

## Entry point

`python -B scripts/cdc.py resume --capsule FILE --probe FILE` reads the existing
resume-capsule/v1 and resume-probe/v1. The probe must come from current live
observations; a JSON file with invented matching values is not evidence.
The command checks capsule agreement and probe age against the runtime clock,
then returns one cdc-resume-result/v1 next_action:

| Kind | Required continuation |
|---|---|
| RESUME | Perform the checkpoint task through the current authorized runtime |
| RECONCILE | Refresh changed, stale, incomplete or unhealthy source/control facts |
| RECONCILE_EXTERNAL | Observe the exact preserved operation, retaining its guard |
| WAIT | Honor the recorded blocker/pause and its established recheck trigger |

All authorizes fields remain false. This executable entry performs observation
and routing; existing managed callers own effects. Task text is data and is
never evaluated as shell/Python. The qualified Cloud fast-start entry from the
separate 2.13 line is an integration prerequisite for the final 3.0 candidate;
this branch does not recreate or claim that transport is released.

`python -B scripts/cdc.py assess FILE` composes quality-assessment/v1,
validation-cycle/v1 and evidence-reuse/v1 through development-assessment/v1.
`python -B scripts/cdc.py report FILE` returns the measured observation and
compact Russian suffix. `python -B scripts/cdc.py strategy FILE` recommends
one executor, bounded independent executors, or waiting from existing budget
events. These commands are pure assessments, not effect launchers.

## Change contract and selective TDD

Record problem, desired behavior, scope, acceptance examples, risk and required
evidence in a short specification. For a small reversible change this may be a
few sentences in the existing task record. A complex change needs a plan and
independently reviewable boundaries. Avoid a parallel documentation ledger.

TDD is required for complex logic, critical authorization/ownership/external
effects, dangerous migrations and reproduced defects. Observe a meaningful
RED before implementation and GREEN after. Use direct edits and focused
verification for reversible documentation, layout and formatting. A test must
cover an independent behavior, risk or regression; remove redundant checks
only after their coverage is mapped to the retained check. Do not replace a
critical test with phrase matching or implementation duplication.

Current user authorization and higher-priority instructions settle workflow
approval requirements. Companion engineering skills do not re-request design
or plan approval that the user already gave. Use their isolation, debugging and
evidence guidance for the actual risk; independent review follows the real
project or release contract, without a routine extra reviewer.

## Validation economics

Use the existing quality evaluator and project floor. FAST does not waive
ownership/authentication/migration/product/platform/release gates. Core remains
FULL. Keep mandatory check IDs explicit; missing evidence remains missing.

One aggregate candidate may contain compatible independent small changes;
urgent fixes may stay separate. One integrator runs the aggregate check per
required environment. A changed dependency invalidates only evidence whose
recorded coverage includes it. Reuse preserves original candidate SHA and
evidence reference. Exact-candidate release checks cannot be reused across
SHAs. Source/control observations are action-bound and never recycled.

Use the minimum sufficient validation cycle. Repeat only for changed inputs or
a concrete uncovered risk, recording why prior proof is insufficient; after two
cycles revise the strategy before another repeat.
Do not spend an identical full suite per worker or buy another backend's
opinion about an unchanged product failure. Measure from existing budget and
evidence events, retain unknowns, and reserve checkpoint capacity.

## Measurements and communication

Record actual startup, implementation, validation and dependency/provider wait
time with provenance in the existing checkpoint/evidence stream. Unknown phase
time, tokens or defect counts remain null with a reason. Worker durations may
overlap: their sum is not elapsed wall time. Compare observed compatible runs
only; one parallel run cannot establish a speedup over an unobserved baseline.
Every operation-observation/v1 includes an observation_ref and comparison_group;
the group identifies equivalent work, observation window and environment.
The comparator rejects different groups. These references are caller-supplied
provenance and must point to actual observations, not invented evidence.
Delivered-work and escaped-defect counts need an actual comparable observation
window, not hypothetical savings or an invented zero-defect count.

Russian operation suffixes use half-up rounding to whole minutes. Under half a
minute may display `(0 мин)`; it does not mean no work occurred. Include numeric
usage only from measured counters with provenance. Unavailable usage scope,
tokens or money remain explicit UNKNOWN
with a reason. Emit a fresh runtime Moscow `[HH:MM DD.MM]` timestamp for EACH
substantive progress, blocker, continuation and final report. Only an exact
idempotent retry of the same command_id/report_id may suppress a duplicate;
legacy per-command timestamp behavior is compatibility, not the reporting rule.
