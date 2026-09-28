# Specification Compliance, Two-Stage Review & Branch Finishing

CDC 2.10.1 adopts the Superpowers design/plan/review discipline without importing redundant approval loops or changing CDC authority.

## Selective brainstorming and specification

Brainstorming is required only when a material product/design choice is genuinely ambiguous. Routine fixes, mechanically specified work and already-authorized continuation must not be blocked merely because no brainstorming conversation occurred.

`scripts/spec_plan_queue.py` binds an approved specification to an implementation plan and then to durable continuation items. Every task must reference the specification requirement it implements and the evidence expected for completion. The dependency graph must be acyclic. A task marked complete without evidence is invalid. Every runnable non-blocked task must remain represented in the continuation queue.

This mapping prevents a prose plan from becoming an unverified completion claim. It also lets CDC continue automatically after a task milestone because remaining work is explicit and durable.

## Two-stage independent review

Material changes pass reviews in this order:

1. **Spec compliance** — did the implementation satisfy the approved request/spec without scope drift?
2. **Code quality** — is the implementation safe, maintainable, testable and appropriately simple?

Non-material changes with no review started may return `REVIEW_NOT_REQUIRED`; CDC must not manufacture review overhead merely because the pipeline exists. `scripts/review_pipeline.py` enforces that code-quality review cannot substitute for or precede a GREEN spec-compliance review when review is required or voluntarily started. Completed reviews use independent reviewer identities and ordered evidence. Findings are typed as `open`, `resolved` or `dispositioned`: open findings block `REVIEW_GREEN`; resolved/dispositioned findings require a durable resolution/disposition reference and do not disappear silently.

Reviewers are evidence/recommendation roles. Review GREEN creates **no merge authority**, no release authority, no product-write authority and no scope-expansion authority.

## Branch finishing

`scripts/branch_finish.py` standardizes the evidence boundary before CDC terminal/release handling. It requires:

- exact candidate SHA equals freshly observed branch HEAD;
- fresh validation bound to that SHA;
- diff/spec reconciliation;
- spec-compliance GREEN;
- code-quality GREEN;
- no unresolved review findings;
- required checks GREEN on the exact candidate;
- explicit candidate binding;
- clean worktree.

A GREEN branch-finishing result means only `READY_FOR_CDC_TERMINAL`. CDC ownership, verification-before-terminal, merge and release gates still apply independently.

## Relationship to Superpowers

Superpowers contributes the engineering discipline: design/specification, writing plans, independent review and finishing a development branch. CDC remains the control plane for authorization, ownership, external execution, continuation, integration and release.

Do not turn selective brainstorming into a user-interruption requirement. If ambiguity is absent and scope is already authorized, planning and execution continue without asking for a redundant approval.

## Release evidence

CDC 2.10.1 release evidence must prove:

- clear work can proceed without a brainstorming gate;
- ambiguous material work requires a brainstorming/design reference before execution mapping is considered ready;
- completed plan tasks require evidence, task dependencies are acyclic, and runnable tasks remain in the continuation queue;
- code-quality GREEN before spec-compliance GREEN is rejected;
- the two completed reviews are independent and ordered;
- open findings keep the change non-terminal; resolved/dispositioned findings require durable evidence;
- branch finishing fails on stale validation, moved HEAD, wrong check SHA or unresolved findings;
- all new controls remain evidence-only and create no merge/release authority.
