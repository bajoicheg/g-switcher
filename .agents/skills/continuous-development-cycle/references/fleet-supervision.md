# CDC 2.6 fleet supervision

Fleet supervision aggregates project snapshots; it is **not** a super-writer. The fleet layer may read project/product/control-plane state, compute health/version/SLO assessments, append audit events on an authorized control-plane path and recommend recovery. It never grants product writes, takeover, external starts, merges, releases or scheduler mutation.

Each member publishes/refreshes `fleet-project-snapshot/v1` on its own coordination plane. A central `fleet-registry/v1` binds exact repository/source refs, watchdog IDs, target CDC version/package fingerprint and progress-SLO policy. `scripts/fleet_supervisor.py` rejects stale/missing snapshots and combines version convergence, watchdog state and meaningful-progress SLO into HEALTHY / DEGRADED / STALLED / BLOCKED / RECOVERY_REQUIRED.

Recovery recommendations such as `kick_project_watchdog`, `reconcile_scheduler` or `prepare_adoption` are only recommendations. The target project must still pass its normal ownership, quiescence, budget, guard and user-authorization gates.
