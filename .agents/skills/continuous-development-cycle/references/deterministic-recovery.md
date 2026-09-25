# CDC 2.5 deterministic recovery recipes

Known failure classes should not require fresh open-ended RCA every wake. Normalize evidence to `recovery-diagnosis/v1` and select from `recovery-recipe-catalog/v1` with `scripts/recovery_recipes.py`.

Recipes use only an allow-listed control-plane action vocabulary; they cannot carry arbitrary shell commands, URLs or provider mutations. Selection is deterministic by diagnosis, required/forbidden facts and priority. Recipes never grant takeover, product-write, external-start or scheduler-mutation authority. If no exact recipe matches, persist a blocker/escalation instead of improvising destructive recovery.
