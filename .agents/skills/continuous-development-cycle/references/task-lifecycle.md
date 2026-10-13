# Task lifecycle

## State machine

A normal coherent task moves through these states:

`RECOVER → DEFINE/PLAN → RED → IMPLEMENT → TARGETED_GREEN → REVIEW → FINAL_GATE → CLOSE_TASK → NEXT_TASK`

A release-capable change may then continue:

`NEXT_TASK/CHANGE_COMPLETE → RELEASE_CANDIDATE → RELEASE_VALIDATION → RELEASED`

Terminal states are:

- `COMPLETE` — all configured work and closure/release gates are satisfied;
- `BLOCKED` — a concrete external/safety requirement prevents progress and no valid fallback remains;
- `RUNTIME_LIMIT` — current execution must stop, after durable handoff where possible.

## Rules

- A commit is not completion.
- A successful targeted test is not final closure unless the adapter says it is the final gate.
- Starting CI is not completion.
- One finished task is not completion when more approved tasks remain.
- A reviewer finding must be resolved or explicitly dispositioned before closure.
- Evidence belongs to an exact SHA; do not transfer GREEN from one SHA to another without justification.

## Planning gates

Use the repository's approved specification/OpenSpec/design process. New or scope-changing work should be designed before implementation. Small bounded changes may use a short approved design if repository policy permits.

Do not invent scope to keep an agent busy. If implementation reveals architectural scope not covered by the approved design, stop that task slice, upgrade the planning path, and record the transition.

## TDD transaction

For a feature or bug fix:

1. add or identify a test that demonstrates the missing behavior;
2. observe RED on a trustworthy backend;
3. make RED state durable when remote execution is needed;
4. implement the smallest bounded production change;
5. run targeted GREEN;
6. run configured broader validation;
7. obtain required review;
8. execute final platform/CI gate;
9. close only after evidence is tied to the candidate SHA.

Tests-only/intermediate commits may use skip-CI only when policy permits and another exact-SHA validation path is immediately available.
