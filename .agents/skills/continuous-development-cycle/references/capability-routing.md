# CDC 2.5 capability routing

Describe runtime/validation needs as capability tokens such as `os:windows`, `dotnet:8.0.425`, `jdk:17`, `android-sdk:36`, `feature:emulator` or `network:common-dependencies`. Keep a freshly evidenced `backend-capability-registry/v1`; never infer capabilities from a backend name.

`scripts/capability_router.py` filters disabled, non-ready and incompatible backends, then applies declared kind preference and stable rank. A route result never authorizes an external start: ownership, operation intent/guard, budget and provider authorization remain separate gates. A stale registry blocks routing; no match becomes durable `waiting_external/backend_unavailable` instead of a blind launch.


## Cost-aware second stage

After capability compatibility is known, apply `scripts/cost_router.py` and
`references/cost-aware-routing.md`. A compatible backend is not automatically economical.
Transient low-cost-provider failure must not silently promote an expensive provider.

## Cloud entry/profile handoff (2.13.0)

Read the actual verified project vendor_root and use its scripts/codex_cloud_entrypoint.py prepare with docs/cdc-cloud-profile.json and hash-bound docs/cdc-cloud-entry-inputs.json. Capability tokens remain from the existing fresh registry; never derive provider kind from display names. Native Cloud, official UI and independently authenticated CLI retain separate namespaces/IDs and qualification. CLI401/global inventory unknown does not disable a genuinely qualified connected native runtime. A pure preparation, route, recipe or handoff never creates a provider task or ownership.

compute-cost-context/v2 wraps the unchanged base context and typed provider/action/exception facts. Apply Codespace compute/control-host eligibility BEFORE every existing fallback branch; existing live callbacks still check exact source/request/owner/budget/one-use guard. Missing capabilities remain explicit blockers, not a prompt to mutate proxy/auth/allowlist. Root/source/install/consumer/Fleet acceptance and platform gates remain distinct; paused watchdogs stay paused.
