# CDC 2.8 autonomous continuity and isolation

CDC 2.8 makes continuity an enforced invariant rather than a conversational convention.

## Terminal-State v2 and No-Idle

Use `scripts/terminal_state_v2.py` before a foreground invocation returns. If an authorized runnable action exists, a terminal response is forbidden. Valid terminal boundaries are verified scope completion, a single durable external binding with an executable recheck action, or a proven durable blocker with evidence, trigger and exact next action. Lease release is required before terminal response.

The terminal-state evaluator never expands scope or destructive authority. A bare continuation request preserves the existing authorized scope but requires the executor to keep crossing durable continuation boundaries until TS.

## Execution-channel supervision

Use `scripts/execution_channel_supervisor.py` after capability and cost routing. A failed backend is added to the bounded attempted set and the supervisor immediately selects the next policy-compatible backend when one exists. Product/test failure is not infrastructure failover: fix the product first. Exhausted failover becomes a durable wait/blocker, never silent idle.

## Concurrent writers

Use `scripts/concurrent_writer.py` whenever expected HEAD differs from observed HEAD. Equal HEAD proceeds. A fast-forward with non-overlapping paths may be replayed on the fresh HEAD. Path overlap, divergence, unknown ancestry or an external guard requires reconciliation. Force push is never authorized.

## Control-plane isolation

Product source repositories should contain product source, tests and product policy. Operational CDC state such as leases, ledgers, authorizations, backend registries, operation intents, handoffs and environment plans belongs in a private control-plane store/ref that is excluded from public export. Publication safety is defined separately in `references/publication-safety.md`.
