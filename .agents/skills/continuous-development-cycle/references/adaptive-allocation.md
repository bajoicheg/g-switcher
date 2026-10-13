# Measured adaptive allocation

Use `python3 -B scripts/cdc.py allocate templates/adaptive-allocation.json` to
recommend reasoning effort and useful independent agents from existing strategy,
quality, budget and completed-operation contracts. The JSON template is runnable
without measurements and conservatively keeps its explicit safe default.

Profiles bind `id`, `reasoning_effort` (`low`, `medium`, `high`, `xhigh`),
`max_agents`, and the existing `agent_reservations` entries. The selected
profile's prospective costs must conservatively cover its effort and integration
overhead. Historical token savings are not prospective budget permission.
Inline profiles use an empty reservation list. The allocator reevaluates the
selected profile's admissions against an immutable copy of the existing ledger.

Supply actual retrieved `operation-observation/v1` records in `observations`,
each bound to its `profile_id`. Authenticate their sources yourself. A comparison
group identifies the same work, environment and validation window; mismatched
groups and duplicate observation references are rejected. Profile labels and
configuration must retain their meaning across the comparison. This helper
cannot authenticate a provider, infer prices or prove a causal speedup.

At least two completed observations with positive delivered units, known zero
escaped defects and measured tokens are required for adaptive selection.
Estimated or missing tokens, unknown delivery and unknown defects do not prove
an improvement. Any observed escaped defect excludes that profile, including
observations with unknown tokens or zero delivery. A known-defective default
with no measured safe alternative returns WAIT; obtain corrected evidence rather
than relabeling history. FULL tasks require at least high effort; other work
requires at least medium. These floors never lower existing validation gates.

Eligible profiles are ranked by measured tokens per delivered unit, then elapsed
seconds per delivered unit, effort, agent count and profile ID. Aggregate numeric
overflow fails closed. The result retains sample references and measured totals;
it makes no unmeasured savings claim. With sparse evidence use the safe default.

Portable scopes, dependency closure, cumulative budget caps and reservation
replay remain controlled by `execution_strategy.py` and `budget.py`. Baseline or
selected-profile replay preserves WAIT. PARALLEL requires admitted independent
scopes and a profile cap covering the whole task set; otherwise execution is
SINGLE. One integrator remains responsible for acceptance and publication.

Every launch/write/release/takeover/scheduler authority flag is false. The helper
does not reserve, persist, consume, start or publish anything. Before an actual
effect, authenticate current observations and follow the existing durable
intent, lease, guard, budget and one-use claim sequence. Existing compute cost
routing, required platform CI, archived-consumer checks and Fleet pause remain
authoritative. Allocation is a recommendation within those boundaries.
