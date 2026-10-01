# Runtime routing and subagents

## Runtime decision

Subagent policy is determined by where the **orchestrating development request** is launched.

| Orchestration origin | Subagents | Default behavior |
|---|---:|---|
| ordinary ChatGPT chat | disabled | orchestrator implements sequentially |
| ChatGPT Work | enabled by default | delegate useful independent slices without per-launch approval |
| Codex orchestration environment | enabled by default | delegate useful independent slices without per-launch approval |
| unknown/ambiguous | disabled | fail closed to ordinary-chat behavior |
| watchdog | inherited | use policy of the runtime executing the wake |

Do not infer Work/Codex origin merely because a repository, GitHub connector, compute backend, or Codex-produced artifact exists.

In Work/Codex, this skill explicitly authorizes and requests useful delegation within the user's already authorized task. Do not wait for an additional phrase such as "use subagents". Higher-priority instructions, explicit task/repository restrictions, actual tool availability and quota still apply. Permission to delegate does not authorize new product scope, external messages to people, merges or destructive actions. If delegation is unavailable, the orchestrator continues sequentially.

## Codex orchestration vs compute-only

These are different modes and must never be conflated.

### Codex as orchestrator

When the user starts the development request inside Codex, Codex owns orchestration for that invocation. It may implement, coordinate subagents, review, commit, push, and advance the task subject to repository policy.

### Codex as COMPUTE_ONLY backend

When another orchestrator sends an exact-SHA command execution request to Codex, Codex is not the project owner. It must:

- verify the expected SHA equals observed HEAD;
- show clean worktree before and after;
- execute only the supplied build/test commands;
- return exit codes and concise diagnostics;
- make no edits, commits, pushes, PR changes, merges, product decisions, or task-closure decisions.

A compute result is evidence only.

The Work/Codex delegation default does not expand a `COMPUTE_ONLY` request. The compute worker executes only the supplied contract; implementation delegation and parent-task closure remain with the orchestrator. See `codex-compute.md` for environment setup and exact-SHA requests.

## Adaptive effort

Subagents use **optimal/minimum sufficient effort**, never blanket maximum effort.

Choose effort per task from observable complexity, ambiguity, risk, and blast radius. A useful mapping when the runtime exposes comparable levels:

- **Low:** repository inventory, file lookup, log collection, deterministic formatting, simple fact extraction.
- **Medium:** routine documentation, localized changes, ordinary unit tests, straightforward analysis.
- **High:** non-trivial implementation, difficult tests, architectural work inside an approved design, independent code/security review.
- **Maximum / Extra High:** exceptional use only when lower effort is insufficient for unusually difficult debugging, concurrency, security-critical reasoning, or high-ambiguity architecture.

This mapping is advisory, not a fixed model name contract. Runtime capabilities change; choose the best available equivalent.

## Delegation contract

When subagents are enabled:

1. Orchestrator remains the single task owner and integrator.
2. Delegate bounded outputs with explicit inputs, acceptance criteria, and evidence expectations.
3. Independent read-only research/review may run in parallel.
4. Two writing agents must not edit the same mutable workspace concurrently.
5. Writing agents use isolated worktrees/branches or non-overlapping ownership when the runtime supports it.
6. Reviewer and test-analysis agents should be independent of the implementation agent when practical.
7. Subagents do not close the parent task, merge, or reinterpret product scope unless explicitly authorized by the orchestrator.
8. Agent failure/quota exhaustion triggers fallback; it does not erase durable repository progress.

Before spawning, reserve an `agent_start` in the durable budget ledger and check task/wake start caps, active-agent cap and checkpoint reserve. Pass only the task inputs and relevant instructions/references, plus exact file ownership and acceptance criteria. Full history is unnecessary for an independent bounded task. Record completion only after the child is actually terminal; an uncertain spawn response retains its charge and active slot until reconciliation. See `references/budget-ledger.md`.

## Anti-patterns

- Launching subagents from ordinary chat because the project is large.
- Giving every agent maximum reasoning "just in case".
- Allowing several writers to race on one branch/worktree.
- Treating a subagent's statement of success as final evidence.
- Treating a compute-only Codex run as permission for Codex to fix the code.
