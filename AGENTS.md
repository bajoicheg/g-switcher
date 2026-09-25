# G-switcher — CDC development policy

These instructions apply to development on the active draft PR #28 (`release/2.0.1`) unless the owner explicitly supersedes them.

## Source of truth

- Repository: `bajoicheg/g-switcher`.
- Current development line: `release/2.0.1`, draft PR #28.
- GitHub/repository facts are durable truth; chat/UI activity is not execution evidence.
- Read this file, `.agents/skills/continuous-development-cycle/SKILL.md`, `docs/development-cycle.yaml`, and `docs/work-status/current.md` before shared writes or external starts.

## CDC 2.7.2

This repository vendors immutable canonical CDC 2.7.2 from `bajoicheg/g-cdc`,
`refs/heads/release/v2.7.2`, release commit
`9f68f150a46dcd2de6933d0469ab12a07dc1fd74`, exact package tree
`6e22d252374634662c95488ba9e7245febf6771a`.
Version equality alone is insufficient; `docs/cdc-consumer-lock.json` and the exact subtree bind convergence.

Use invocation-bound `execution-lease/v2`, durable intents/guards, transactional finalization, hard execution continuity, resume capsule, capability routing, deterministic recovery, continuation queue, fleet/SLO/audit and explicit release before final response. Health/router/fleet recommendations never grant product-write, takeover, external-start, merge, release or scheduler authority.

## Public-repository compute economics

This repository is public. Standard GitHub-hosted Actions are treated as a normal/free compute backend for this project and MUST NOT inherit the private-repository Actions cost penalty. Route by capability, evidence quality and latency rather than by a fictitious Actions cost.

- Windows Rust CI is the authoritative remote platform gate and may be used normally.
- Codex COMPUTE_ONLY remains useful for compatible portable/static/schema checks when configured, but is not preferred merely to save Actions cost.
- Windows E2E, Windows UI/runtime, release artifacts and main-only publication stay on GitHub Actions.
- Product/test failure is fixed rather than blindly repeated on another backend.
- Do not weaken the manual compatibility gate or public promotion approval.

## Existing product/release boundaries

Preserve the current 2.0.1 security model, fail-open behavior, exact-SHA Windows CI, committed lockfile, Defender/release checks, artifact checksums and manual compatibility matrix. CDC adoption is process-only and does not authorize release, merge, signing or compatibility claims.

## Continuous execution

If a runnable next action exists and no real blocker/guard exists, do not finish after status/health/lease/poll only. Continue until meaningful durable progress, a durable external binding, a resumable blocker, or verified completion. Before a final response while owning the lease: drain writes, reconcile external work, checkpoint, pass continuity gate, and explicitly release the exact invocation-bound lease.
