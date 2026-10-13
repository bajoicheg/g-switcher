# Worktree-Isolated Parallel Development & Single Integrator

CDC 2.10.2 adds safe concurrency as an execution-quality layer. It does not change CDC authority, runtime routing or ownership rules.

## Runtime boundary

Parallel writer delegation is available only when the actual orchestration runtime already permits subagents/writers, such as ChatGPT Work or Codex orchestration under the project policy. Ordinary ChatGPT chat remains sequential. Planning a parallel wave never creates worker-launch authority.

## Parallel DAG and write-set planning

`scripts/parallel_task_planner.py` turns a dependency DAG into execution waves. Tasks may be `writer`, `read_only` or `review`. Writers declare bounded relative write paths; read-only/review tasks declare none.

Each individual writer write set must first be unique under the portable case-folded Unicode-normalized identity; raw-string distinctions such as case-only or NFC/NFD aliases do not create separate paths. Independent ready writers may share a wave only when their write sets do not overlap by exact or ancestor/descendant path under the same portable identity. This prevents Linux-only case distinctions from creating collisions on Windows/macOS. Overlapping ready writers are serialized into later waves. Cyclic dependencies are rejected. The planner reports sequential and parallel estimates for observability only and never launches workers.

## Isolated worker/worktree contract

`scripts/worktree_worker_contract.py` is **per-wave**. The contract embeds the immutable planner input and requires `plan_ref` to equal the canonical SHA-256 content address produced by the planner for that exact plan JSON. It then recomputes the selected wave and requires the assignment set plus role/write-set/output/evidence contract to match that wave exactly. Changing the embedded plan without changing its durable digest is rejected. Before each wave starts, it binds every delegated task in that wave to:

- durable worker and task identity;
- exact common base SHA;
- isolated branch and worktree identity;
- the wave's exact current base SHA;
- write set for writers;
- expected outputs and evidence;
- an explicit prohibition on shared-branch writes.

The CDC integrator is not a delegated worker. Local branch names are canonicalized to `refs/heads/...` before shared-branch isolation and assignment uniqueness checks, so `main` and `refs/heads/main` cannot bypass the prohibition. Same-wave writer overlap is invalid. Read-only/review workers may not claim write paths. A later writer wave is contracted only after the prior writer wave has been integrated/reconciled. The worker contract resolves a content-addressed prior integration chain from durable evidence. Every wave record binds the exact change, plan, wave, prior base, advanced integrated HEAD and shared branch; resolves a content-addressed GREEN gate artifact and a separate content-addressed assembly artifact; and the assembly artifact itself binds the exact gate digest. Wave one must begin at the plan base, later records recursively bind the predecessor record, and every assembly must advance the shared HEAD. For live later-wave creation the CLI also resolves the real shared branch and proves base→integrated ancestry, so a caller-provided `integrated_head`, evidence label or invented JSON record alone is never sufficient. The next wave therefore receives the actual new shared-branch base instead of inheriting or inventing a stale base.

## Single-integrator gate

`scripts/integration_gate.py` evaluates terminal results for **one wave** before the single integrator assembles that wave onto the shared integration branch. The integration input embeds the exact worker contract for that wave. The gate cross-checks worker/task/role/base identity and requires every changed path to remain inside that worker's assigned write set. It also requires the shared branch to remain at the wave's expected base, all workers to succeed, no unresolved conflicts and no force-push request.

A GREEN result is only `READY_FOR_INTEGRATOR`. The gate creates no shared-branch write, merge or release authority. Every successful writer carries a `git_diff_name_only` proof bound to worker/task/base/result and the **complete** changed-path set. Real integration invokes the CLI with `--git-worktree`, which resolves both commits, proves `base_sha` is an ancestor of `result_sha`, and re-computes the Git diff. There is no CLI contract-only bypass for successful writers; package fixture validation calls the pure evaluator directly. The real integration CLI requires a Git worktree and resolves the live shared branch ref for every potentially ready wave, including review-only/read-only waves; it requires that live ref to equal the caller's observed shared HEAD before it can become ready. For every successful writer it also requires a live `worktree_id=path` mapping and reconciles that path against `git worktree list --porcelain`: the registered branch must equal the assignment branch and both the registered worktree HEAD and branch ref must equal the reported result SHA. The integrator must still use normal concurrent-writer reconciliation before the separately authorized assembly write. If the current wave is not the final planned wave, the gate routes to `integrate_wave_then_contract_next_wave_on_fresh_head`; only after all implementation waves are assembled does it route to CDC 2.10.1 spec/code review and branch finishing, then CDC 2.10.0 verification-before-terminal.

Failed or stale worker output is discarded/rebased/re-run in isolation. It is never force-pushed or partially integrated merely to preserve effort already spent. A successful worker result must satisfy the delegated output/evidence contract; successful writers must report a new result SHA plus changed paths inside the assigned write set, while read-only/review workers must remain at the base SHA.

## Observed parallel benchmark

`scripts/parallel_benchmark.py` validates observed performance evidence. A benchmark is GREEN only when a representative task has at least two workstreams, measured parallel elapsed time is lower than the sequential baseline, and unresolved conflict/rollback counts do not regress.

Estimated planner savings are not release evidence by themselves. The package contains only `evidence_class=fixture` non-observed benchmark fixtures; they can validate the contract shape but always return `release_evidence_eligible=false`. Package validation rejects any attempt to treat fixture timings as release evidence. Actual release evidence lives outside the package tree and contains exactly one structured sequential observation and one structured parallel observation. Both must be marked observed, bind the same exact candidate SHA, environment, cryptographic `sha256:` plan reference and `sha256:` workload fingerprint, and carry distinct durable evidence refs. The benchmark manifest also names the actual plan artifact path and its SHA-256; validation reads those bytes and requires the measured `plan_ref` to equal the artifact digest. Arbitrary matching or merely hash-shaped plan labels are not release evidence. Timings are derived from those observations; arbitrary top-level timing labels are not accepted. Estimates and observed timings must be finite positive numbers; NaN and infinities are invalid evidence. CDC 2.10.2 release evidence must include at least one actually measured multi-workstream benchmark with those bindings.

## Superpowers relationship

Superpowers contributes worktree isolation, task decomposition, bounded delegation, independent review and a single integration point. CDC remains authoritative for scope, ownership, execution eligibility, shared writes, merge/release and terminal state.

## Release evidence

CDC 2.10.2 release evidence must prove:

- dependency cycles are rejected;
- independent non-overlapping writers can share a wave;
- overlapping writer paths are serialized or rejected when assigned to the same wave;
- every writer is pinned to an isolated branch/worktree and exact base SHA;
- no delegated worker can write the shared branch;
- stale/failed worker results cannot pass the integrator gate;
- shared HEAD movement forces reconciliation rather than force-push;
- final integration remains evidence-only until normal review/verification/release gates pass;
- an observed representative multi-workstream benchmark reduces wall-clock time without increasing unresolved conflicts or rollbacks.
