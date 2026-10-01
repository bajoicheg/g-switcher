# CDC 2.5 capability routing

Describe runtime/validation needs as capability tokens such as `os:windows`, `dotnet:8.0.425`, `jdk:17`, `android-sdk:36`, `feature:emulator` or `network:common-dependencies`. Keep a freshly evidenced `backend-capability-registry/v1`; never infer capabilities from a backend name.

`scripts/capability_router.py` filters disabled, non-ready and incompatible backends, then applies declared kind preference and stable rank. A route result never authorizes an external start: ownership, operation intent/guard, budget and provider authorization remain separate gates. A stale registry blocks routing; no match becomes durable `waiting_external/backend_unavailable` instead of a blind launch.


## Cost-aware second stage

After capability compatibility is known, apply `scripts/cost_router.py` and
`references/cost-aware-routing.md`. A compatible backend is not automatically economical.
Transient low-cost-provider failure must not silently promote an expensive provider.
