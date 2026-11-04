# CDC 2.8.2 fleet and publication maturity

CDC 2.8.2 closes the 2.8 roadmap by making cross-project supervision, stuck-state recovery, publication and self-measurement explicit.

## Project-independent fleet control

Use `scripts/fleet_controller.py` over normalized project records. The controller does not contain product-specific code and never gains product-write, takeover or external-start authority. It observes live owners/guards, wakes runnable unowned projects, repairs stalled watchdog delivery and requests recovery for inconsistent projects.

## Stuck-state detection and counterfactual recovery

Use `scripts/stuck_state.py` to detect repeated action/result fingerprints and unchanged HEAD without meaningful progress. When stuck, repeating the same strategy is invalid.

Use `scripts/counterfactual_recovery.py` to select a different compatible strategy with positive expected information gain. Failed strategies are excluded. If no new information-gaining strategy exists, preserve a blocker instead of looping.

## Sanitized public export

Use `scripts/public_export_planner.py` after the CDC 2.8 publication guard. The preferred publication architecture is private development history → sanitized export → new public history. Preserve private history; copy only allow-listed product paths; exclude coordination/control-plane paths. The planner never authorizes visibility changes or pushes.

## CDC dogfooding

Use `scripts/dogfood_metrics.py` to measure CDC development against its own contracts: terminal-state accuracy, No-Idle compliance, exact-SHA validation, recovery diversity, control-plane isolation and consumer evidence. The result is observability, never release authority or policy authority.
