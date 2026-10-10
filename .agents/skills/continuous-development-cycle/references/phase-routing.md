# Phase-specific instruction loading

Read the compact SKILL, current repository instructions, adapter and checkpoint
at startup. Add only the row for the actual next action. Each reference retains
its own authority requirements. A route is not permission to execute an effect.

| Current action | Load before acting |
|---|---|
| Source implementation / small batch | `references/lean-execution-core.md`, `references/task-lifecycle.md`, `references/quality-levels.md` |
| Initialize project / preview migration | `references/project-setup.md`, `references/policy-compatibility.md` |
| Resume mismatch or uncertain state | `references/bounded-recovery.md`, `references/policy-compatibility.md`, `references/progress-and-checkpoints.md`, `references/operational-hardening.md`, `references/deterministic-recovery.md` |
| Shared write, lease or pool claim | `references/execution-ownership.md`, `references/control-plane-v2.4.md`, `references/orchestration-controls.md`, `references/managed-host-bridge.md`, `references/managed-executor-pool.md`, `references/multi-subscription-coordination-and-ownership.md` |
| Measured effort / agent allocation | `references/adaptive-allocation.md`, `references/runtime-routing-and-subagents.md`, `references/budget-ledger.md` |
| Delegate independent work | `references/runtime-routing-and-subagents.md`, `references/budget-ledger.md` |
| Validation / compute selection | `references/command-evidence.md`, `references/capability-routing.md`, `references/cost-aware-routing.md`, `references/validation-compute-and-ci.md` |
| Existing external task / Cloud transport | `references/external-operations.md`, `references/codex-compute.md`, `references/submission-recovery.md` |
| Watchdog health / scheduler or chat recovery | `references/watchdog-recovery-and-migration.md`, `references/watchdog-liveness-runtime.md` |
| Public source publication | `references/publication-safety.md`, `references/autonomous-continuity-and-isolation.md` |
| Release / isolated archived-consumer compatibility | `references/release-management.md`, `references/canonical-source-and-release.md`, `references/deterministic-distribution-and-convergence.md` |
| Live consumer adoption | `references/live-target-resolution.md`, `references/cooperative-project-lanes-and-watchdog-survivability.md` |
| Detached release delivery / forward rollback | `references/release-delivery.md`, `references/execution-ownership.md`, `references/deterministic-distribution-and-convergence.md` |

Historical explanations and older sections remain in
`references/legacy-core-2.12.1.md`. Read a relevant section only when current
contracts do not resolve the actual question. Do not use historical version
labels, old leases, archived provider output or stale evidence as current facts.
