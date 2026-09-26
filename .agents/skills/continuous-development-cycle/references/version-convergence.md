# CDC 2.6 version convergence

Use `scripts/version_convergence.py` to compare each project with a fleet target that binds the stable CDC version, exact package fingerprint and checkpoint schema.

States are `CONVERGED`, `LAGGING`, `DRIFT`, `AHEAD` and `INCOMPATIBLE`. Version equality alone is insufficient: package fingerprint and checkpoint schema must also match. A project with an active owner or unresolved guard is never migration-ready; the result becomes `wait_safe_boundary`, not a policy push.

Convergence assessment is read-only. It cannot merge, write, take ownership or bypass project-specific validation.
