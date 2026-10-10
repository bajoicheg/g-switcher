# CDC 2.5 deterministic recovery recipes

Known failure classes should not require fresh open-ended RCA every wake. Normalize evidence to `recovery-diagnosis/v1` and select from `recovery-recipe-catalog/v1` with `scripts/recovery_recipes.py`.

Recipes use only an allow-listed control-plane action vocabulary; they cannot carry arbitrary shell commands, URLs or provider mutations. Selection is deterministic by diagnosis, required/forbidden facts and priority. Recipes never grant takeover, product-write, external-start or scheduler-mutation authority. If no exact recipe matches, persist a blocker/escalation instead of improvising destructive recovery.

## Scoped v2 history and action plans

2.13.0 retains v1 callers and explicitly adds recovery-recipe-catalog/v2, recovery-bindings/v1 and recovery-observation-history/v1. See references/cloud-fast-start.md and the concrete API table in the canonical design. Call select with actual bindings/now/history/new_signal, then action_plan with that freshly derived selection. Persist strict selected_signal reference/digest/changed_inputs/completed_correction_ref; reason strings cannot manufacture correction identity. Unknown/submitting history precedes recipe matching. Only fixed typed parameter contracts are accepted; read-role fingerprints exclude incidental chat/wake/attestation keys. Reused evidence selects resume_next_action with its actual proof and exact check reference; no new diagnosis/setup loop.
