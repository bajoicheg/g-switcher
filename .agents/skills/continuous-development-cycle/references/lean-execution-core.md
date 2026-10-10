# Lean execution contract

The compact core routes existing control and quality contracts. It creates no
second orchestrator, budget ledger, release mechanism or authority grant.

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
or plan approval that the user already gave. They still provide independent
reviews, isolation, debugging and evidence-before-completion discipline.

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

Two validation cycles are the default. A repeat needs changed inputs, actual
risk and why old proof is insufficient; another cycle needs a revised strategy.
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
minute may display `(0 мин)`; it does not mean no work occurred. Known measured
tokens may be included; estimates include ≈ and their basis remains in the
observation. Unknown tokens have no placeholder. Emit a fresh Moscow timestamp
once per user command through the existing command timestamp contract.
