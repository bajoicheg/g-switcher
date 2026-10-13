# Behavioral Skill TDD & Verification

CDC 2.10.0 adopts selected Superpowers engineering disciplines as a quality layer while CDC remains the control plane for authority, ownership, continuity, execution, merge, release and terminal-state decisions.

## Behavioral Skill TDD

A CDC control is not considered proven merely because the prose says the right thing or a helper has unit coverage. For material behavioral controls, use an executable pressure scenario:

1. **Baseline RED** — describe facts and a plausible agent trace that demonstrates the undesired behavior.
2. **Correction** — change the skill/control, not the expected outcome.
3. **Corrected GREEN** — evaluate the corrected trace under the same pressure facts.
4. **Regression retention** — keep the scenario in the behavioral eval suite so the failure cannot silently return.

`scripts/behavioral_eval.py` is the deterministic behavioral oracle. It evaluates traces; it does not execute an LLM, mutate a repository or create authority. The core 2.10.0 suite covers premature milestone stop, terminal-provider stale guard, schema-invalid checkpoint, duplicate per-command timestamp, stale checkpoint ownership versus live coordination, and unchanged recovery retries.

The behavioral eval is intentionally thin. Existing CDC scripts remain the source of operational semantics. The eval asks whether the resulting agent/control trace obeys those semantics under pressure.

## Systematic debugging and RCA

For a material anomaly, do not jump from symptom directly to fix. `scripts/systematic_rca.py` requires:

- evidence references;
- explicit competing hypotheses;
- a discriminating test for every hypothesis;
- observed test results;
- exactly one supported selected root-cause hypothesis;
- bounded correction;
- defense-in-depth;
- the invariant that must hold afterward.

The result feeds the existing bounded `rca-feedback/v1` disposition. Systematic RCA is evidence-only and creates **no authority** to write a product or roadmap. The existing CDC authority gates still decide whether any proposed correction may be applied.

## Verification-before-terminal

Before a terminal success claim such as `COMPLETE`, `RELEASE_READY` or `INTEGRATED`, run `scripts/verification_gate.py` against freshly re-read authoritative evidence.

The verification gate checks, where required:

- expected versus freshly observed source HEAD;
- required validation states and their exact candidate SHA;
- checkpoint validity and current policy binding;
- live coordination ownership state and guard reconciliation;
- required artifact identity;
- clean state;
- completion evidence references.

Live coordination is the ownership authority. A stale checkpoint cannot override a newer coordination lease.

The verification gate is **evidence-only**. Passing it does **not** authorize product writes, external starts, takeover, merge, release, scheduler mutation or scope expansion. It can reject a terminal claim; it cannot create permission to make one.

## Relationship to Superpowers

CDC borrows the strongest Superpowers patterns here:

- skill TDD through pressure scenarios and retained regressions;
- systematic debugging before corrective action;
- verification before completion claims.

CDC does not import interactive approval loops as mandatory gates. Existing user authorization, project policy and CDC control-plane state remain authoritative. Routine bug fixes and already-authorized continuation should not be forced through redundant clarification.

## Release evidence

CDC 2.10.0 release evidence must include:

- package/unit regression GREEN;
- all core behavioral scenarios baseline RED and corrected GREEN;
- verification-gate negative tests for stale source, wrong SHA, active ownership/guard, artifact mismatch and dirty state;
- systematic-RCA ambiguity rejection and bounded feedback handoff;
- independent bootstrap under released CDC 2.9.2;
- the normal canonical multi-consumer validation required by CDC release policy.

A behavioral evaluator or verification result never replaces platform-specific product gates. It only proves CDC control behavior.

## Explicit quality policy and valid reuse

For explicitly migrated projects, FAST/MEDIUM/FULL determine applicable review depth; legacy behavior remains unchanged. Verification-gate/v2 validates explicit dependency-bound reused checks in addition to exact candidate checks. It retains fresh source/checkpoint/ownership and artifact gates. Reuse never relabels the original command run. Current exact-final-SHA requirements override cross-SHA reuse. Run templates/behavioral-quality-suite.json for unchanged-validation, critical-risk and cycle-budget pressure regressions; these deterministic traces do not prove that an LLM actually obeyed instructions.
