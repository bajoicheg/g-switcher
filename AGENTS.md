## CDC 2.9.2 authoritative provenance

Current CDC authority is canonical `bajoicheg/g-cdc` **v2.9.2**, immutable `refs/heads/release/v2.9.2`, release commit `0dd30a888be852d2820f690be04dbd374d732c06`, package tree `f9087eacbffee774c143eabf854c2cf08d610ec7`. The complete package is vendored at `.agents/skills/continuous-development-cycle/`; lower-version CDC statements below are historical and must not override this provenance.

Before work, validate `docs/development-cycle.yaml` and `docs/work-status/current.md` with the vendored 2.9.2 validators. Deterministic package transport/convergence, transactional migration/provider reconciliation, Progress-Is-Not-Terminal, the one-per-command Moscow timestamp contract, RCA-to-roadmap closure and Fleet Watcher improvement harvesting are mandatory in addition to the existing 2.8 controls.

# G-switcher — CDC development policy

These instructions apply to development on the active draft PR #28 (`release/2.0.1`) unless the owner explicitly supersedes them.

## Source of truth

- Repository: `bajoicheg/g-switcher`.
- Current development line: `release/2.0.1`, draft PR #28.
- GitHub/repository facts are durable truth; chat/UI activity is not execution evidence.
- Read this file, `.agents/skills/continuous-development-cycle/SKILL.md`, `docs/development-cycle.yaml`, and `docs/work-status/current.md` before shared writes or external starts.

## CDC 2.7.3

This repository vendors immutable canonical CDC 2.7.3 from `bajoicheg/g-cdc`,
`refs/heads/release/v2.7.3`, release commit
`88ee8a209caf562c02fe2ad53e047d7feee0e007`, exact package tree
`806a66cd973954b3d5348ac36d39631717d9fe7b`.
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


## Bare continuation means terminal state

A bare user continuation command such as «продолжай», «продолжи» or “continue”
means continue the already-authorized current scope until terminal state. Do not stop
after one status read, commit, compute result or intermediate checkpoint. This does not
expand scope or authority. Terminal state is verified scope completion or a real durable
terminal blocker/handoff with exact evidence and one executable next action.
