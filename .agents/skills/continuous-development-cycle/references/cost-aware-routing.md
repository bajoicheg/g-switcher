# CDC 2.7.2 cost-aware compute routing

Capability compatibility is necessary but not sufficient for backend selection. A project may have materially different marginal costs across compute providers. CDC therefore separates **capability routing** from **cost/fallback routing**.

Use `scripts/cost_router.py` with a fresh backend registry, the ordinary capability request, `compute-cost-policy/v1`, and `compute-cost-context/v1`. The result is recommendation-only and never grants ownership, product-write, provider-start, scheduler, merge or release authority.

Default policy treats Codex Compute as the primary low-cost compute and GitHub Actions as expensive. Relative weights are policy values, not currency conversion. A ready cheaper compatible backend always wins over an expensive backend.

A Codex setup/network/provider/runtime failure is not, by itself, evidence that GitHub Actions should be spent. These are transient infrastructure failures unless fresh evidence proves otherwise. For portable work:
1. respect a bounded cooldown;
2. perform a deliberately distinct primary recovery/probe when one has information gain;
3. prefer another cheaper compatible backend if available;
4. if bounded primary recovery is exhausted but outage is not independently confirmed, persist `waiting_compute` rather than automatically spending an expensive CI run;
5. an independently confirmed provider outage may permit an expensive fallback if policy explicitly allows it.

A product/test failure on Codex is not infrastructure unavailability. Fix the product or test; do not buy a second opinion from expensive CI.

Expensive fallback requires an explicit machine-readable reason. Normal reasons are: required capability unavailable on cheaper backends, required final platform evidence, required artifact production, release attestation, or independently confirmed primary-provider outage. The request must still pass ordinary ownership, operation-intent, budget, CI and platform gates.

Backend health is recoverable state. `degraded`/`unavailable` should be re-probed after policy cooldown; a successful fresh probe returns it to `ready`. Historical failures must not poison a backend forever.


## Repository visibility

Repository visibility is part of marginal-cost policy. A backend kind is not globally
expensive. When project policy marks standard GitHub-hosted Actions unmetered for a
public repository, cost routing treats that backend as normal/cheap and may select it
directly when compatible. Private/internal repositories may keep GitHub Actions metered
and preserve Codex-first recovery/fallback behavior. Visibility changes cost ranking only;
it never grants launch, ownership, merge, release or scheduler authority.
