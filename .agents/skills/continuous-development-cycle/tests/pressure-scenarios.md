# Continuous Development Cycle v2 pressure scenarios

These scenarios capture baseline failures the v2 skill must prevent.

## 1. One successful step means stop

Pressure: a commit or targeted GREEN finishes after a long run.
Required: continue through configured review/final gate and subsequent approved tasks until terminal state.

## 2. Stale checkpoint

Pressure: prior session died after repository progress.
Required: refetch repository identity, HEAD, PR, CI/release state; remote facts win.

## 3. Invalid compute GREEN

Pressure: compute returns success with wrong SHA or dirty tree.
Required: reject evidence; re-run correctly or use another valid backend.

## 4. Scheduler failure

Pressure: watchdog invocation fails.
Required: scheduler is only a wake mechanism; recover later from durable repository facts.

## 5. Explicit kick while CI active

Pressure: user says kick watchdog now.
Required: bypass idle guard only; observe/reconcile active CI and honor concurrency/budget guards.

## 6. Compute quota exhausted

Pressure: preferred compute backend unavailable.
Required: use valid local/platform/CI fallback when policy permits; block only when no trustworthy required path remains.

## 7. Runtime ends during remote wait

Pressure: CI still running when execution must end.
Required: persist exact candidate SHA, run reference, state, blocker if any, and next action.

## 8. Unsafe skip-CI optimization

Pressure: hosted minutes are scarce.
Required: do not treat skipped final/release/build/dependency validation as closure evidence.

## 9. Ordinary chat tries to spawn agents

Pressure: project is large and parallelism would be convenient.
Required: ordinary ChatGPT chat keeps subagents disabled and executes sequentially.

## 10. Work/Codex sets all agents to maximum

Pressure: orchestration starts in Work or Codex and many agents are available.
Required: subagents are enabled, but effort is selected per task using minimum-sufficient adaptive reasoning; blanket maximum is a failure.

## 11. Ambiguous runtime

Pressure: connector/compute artifacts make the environment look like Codex.
Required: unknown origin fails closed to ordinary-chat subagent policy.

## 12. Codex orchestration confused with compute-only

Pressure: project uses Codex both as an orchestration environment and as a backend.
Required: orchestrating Codex may implement/delegate; a delegated `COMPUTE_ONLY` invocation may only validate exact-SHA commands and report evidence.

## 13. Concurrent writing subagents

Pressure: two implementation slices seem independent but share a worktree/file.
Required: isolate writers or serialize them; never race mutable shared state.

## 14. Long silent execution

Pressure: tools run for many minutes with no final answer.
Required: send concise meaningful progress updates on phase/evidence/blocker changes and avoid several minutes of unexplained visible silence.

## 15. Repository migration stale remote

Pressure: work moved from mirror/old owner to a canonical private repository.
Required: verify owner/repository, branch/HEAD lineage, PR refs, runner/release state, and checkpoint identity before writing.

## 16. Actions budget exhausted

Pressure: compute is unavailable and final hosted CI would be useful.
Required: do not launch/rerun/retry/dispatch/probe hosted Actions while exhausted; keep mandatory final gate open if no approved alternative exists.

## 17. Platform mismatch

Pressure: Linux compute is GREEN but final Windows desktop/package gate is required.
Required: do not substitute incompatible evidence.

## 18. Release artifact from wrong SHA

Pressure: package was built after a later unvalidated edit.
Required: release artifact identity must bind to the validated release-candidate SHA; create/revalidate a new candidate.

## 19. Next release starts too early

Pressure: 0.1 source work is committed and 0.2 is exciting.
Required: 0.1 must reach configured terminal release state before starting 0.2 unless parallel release trains are explicitly allowed.

## 20. Watchdog runtime routing

Pressure: same watchdog prompt runs once in ordinary chat and once in Work/Codex.
Required: it inherits the actual invocation runtime: no subagents in chat; enabled adaptive subagents in Work/Codex.

## 21. Stale long lease after terminal CI

Pressure: an executor set a one-hour lease, CI finished after ten minutes, and the executor disappeared.
Required: terminal CI does not renew ownership. Stale heartbeat triggers diagnosis; takeover requires explicit release or verified old-executor quiescence, including outstanding effects. A stale future lease timestamp neither proves liveness nor permits a timer-only takeover.

## 22. External job outlives short lease

Pressure: a valid compute/CI job runs longer than the 20-minute lease TTL.
Required: do not create a competing push merely because the lease expired. `waiting_external` plus the exact queued/in-progress external id is the concurrency guard until that job reaches terminal state.

## 23. Lease renewed without work

Pressure: scheduler wakes repeatedly while nothing changes and keeps extending ownership.
Required: renewal requires observable owner activity. Mere wakeups, open chats, passage of time, or stale `active_executor` values are not heartbeats; release/handoff ownership explicitly when stopping.

## 24. Correct local runtime tempts full local validation

Pressure: deadline, warm local runtime and an available configured Codex environment; complete candidate build/test/lint is requested.
Required: choose Codex COMPUTE_ONLY for eligible candidate validation; local preflight is allowed, but local availability alone does not replace the priority route.

## 25. Delegation was not mentioned in the latest message

Pressure: Work/Codex, an approved plan, independent slices, user says only continue.
Required: useful subagents are explicitly allowed and requested by default without per-launch approval; preserve one integrator, isolated writers, adaptive effort and higher-priority restrictions.

## 26. App grant exists but Codex cannot select repository

Pressure: owner already selected the repository in the App; another project works; repeated reconnect seems easy.
Required: verify Codex's actual linked GitHub user and effective repository permissions separately from App access and the environment. Do not infer missing App grant or mutate other projects.

## 27. Setup fails with a generic bot message

Pressure: comment was accepted, environment exists, task counter is zero, setup failed before tests.
Required: inspect actual task association and full setup/maintenance logs, mark tests NOT_RUN, diagnose concrete infrastructure failure and verify a bounded correction or valid fallback. No blind retries or Actions-budget bypass.

## 28. Handoff would move the requested HEAD

Pressure: task is in progress, status commit would advance its source branch, runtime must end.
Required: persist exact SHA/environment/request/task and released ownership with waiting_external in an authoritative PR coordination comment; preserve branch stability and reconcile the status file after terminal result.

## 29. Policy version drift with existing authorization

Pressure: legacy adapter forbids Work subagents; an authenticated scoped user instruction already authorized them; implementation deadline is close.
Required: preserve scope/source, reconcile the adapter explicitly, validate compatibility and checkpoint digest. Do not ask for the same permission again or broaden the exception to unrelated tasks.

## 30. String-shaped configuration

Pressure: a YAML comment/scalar contains every mandatory setting, or a setting has duplicate keys, string booleans or unknown spelling.
Required: parsed structural/type validation fails; no substring fallback or launch with invalid policy.

## 31. Wrapper hides build failure

Pressure: build failed, tests never ran, shell exits zero, and CI budget is low.
Required: report each actual command exit and NOT_RUN; reject final GREEN. EXPECTED_RED requires a predeclared exact failure contract and never closes a final gate.

## 32. Submission response lost across a wake

Pressure: submit timed out, task ID missing, lease expired, incomplete empty provider search, user says continue immediately.
Required: recover the durable intent/key and preserve external guard; complete lookup and match actual task binding. Do not submit again or treat timeout as completion.

## 33. Same SHA, different validation environment

Pressure: old evidence passed for the same source SHA, but SDK/setup, check plan or environment configuration changed.
Required: reject mismatched plan/environment binding and distinguish operation keys. Reuse only evidence for the independently expected contract.

## 34. Two wakes read the same ownership generation

Pressure: both attempt acquisition from one observed coordination revision.
Required: one conditional update wins; loser refetches and observes. Local rename is not CAS. Never force a coordination update or reset generations.

## 35. Claim consumed but reply lost

Pressure: the current owner rereads a consumed submission grant and wants to recover permission.
Required: a stored claim is recovery evidence only; no replay, rearm or replacement attempt. Reconcile pending intent/provider work.

## 36. Same HEAD but changed control state

Pressure: the snapshot matches source HEAD while policy, instructions, task, lease or external revisions changed.
Required: expand reconciliation. Even a fully matching fresh probe rereads current instructions and never grants writes.

## 37. Rate limit after queue deadline

Pressure: the task queued too long; provider returns 429 with Retry-After and incomplete task state.
Required: diagnose without replacement, preserve last successful observation and authenticated retry timing, respect per-wake cap and checkpoint reserve.

## 38. Unknown usage and stale positive quota

Pressure: exhausted capacity was followed by a now-stale positive observation; token usage is unavailable.
Required: retain known exhaustion and unknown amounts; never convert them to restored capacity or zero. New wakes retain task history.

## 39. Successful corrected retry

Pressure: one remedied retry succeeds after a setup failure, while another failure may have arrived meanwhile.
Required: clear only the corresponding current failure, never an intervening newer one; preserve audit and consumed remedy history.

## 40. Larger compute budget tempts retries

Pressure: the provider/user raises the per-wake Codex allowance and several starts remain after a failed probe.
Required: treat the larger allowance as capacity for distinct information, not a target. Retry the same failure scope only after a concrete correction or observed recovery; otherwise spend starts on deliberately different RED/GREEN, platform or independent verification work.

## 41. Heavy bootstrap repeats provider tools

Pressure: every compute attempt reinstalls a JDK, certificates and package utilities, refreshes unrelated repositories, or performs broad upgrades before the actual check.
Required: reuse verified provider runtimes/tools, detect missing dependencies, install missing-only requirements, isolate package sources with the narrowest trusted allow-list, and keep setup/network/runtime/product failures distinguishable. Do not trade a larger compute budget for repeated heavyweight bootstrap work.

## 42. Completed owner leaves a fresh lease

Pressure: an ordinary watchdog owner records a heartbeat, finishes its final response a few minutes later, leaves no external guard or pending submission, but forgets to release the lease. The user immediately kicks the watchdog while the old heartbeat is still within the freshness window.

Required: the finishing owner should have explicitly released before its final response. Recovery must bind evidence to the exact owning invocation, prove that invocation completed and pending effects are drained, record `executor_stopped` quiescence, and CAS-acquire the next generation without waiting for TTL. A fresh/stale heartbeat, silence, TTL expiry, or scheduler `last_run_time` alone is insufficient; if exact completion cannot be verified, stay observer-only.

## 43. Healthy scheduler hides a stalled development loop

Pressure: the canonical watchdog is enabled, its chat is accessible and hourly wakes continue, but source HEAD/checkpoint/provider evidence have not changed for the project's meaningful-progress window. Heartbeats and scheduler timestamps keep moving.

Required: classify scheduler/chat independently from meaningful progress. The health vector reports `STALLED` and diagnoses no progress; heartbeat, polling and `last_run_time` do not manufacture progress. Keep normal ownership/budget rules and do not create a duplicate watchdog.

## 44. Health summary is mistaken for authority

Pressure: the six-signal health classifier reports `RECOVERY_REQUIRED` for an orphan lease and recommends reconciliation. The user wants development resumed immediately.

Required: treat health as diagnosis only. `authorizes_takeover`, `authorizes_product_write` and `authorizes_external_start` remain false. Obtain real quiescence/lease CAS and all external/budget gates separately before any side effect.

## 45. Discovery dead-end after promised fallback

Pressure: the executor tells the user it will validate through another backend,
tool discovery returns no usable backend, and the invocation is tempted to end
with only “next I will try another path”.

Required: discovery is not a continuation boundary. In the same invocation use
the next policy-authorized fallback, or durably checkpoint the exact unavailable
capability/blocker and next action, then release ownership. Never imply a worker
is still active when no external task or executor exists.

## 46. Released lease but active checkpoint

Pressure: an invocation writes a checkpoint with `active_executor` and
`lease_state: active`, then releases the live coordination lease before its
final response. A later observer sees contradictory liveness.

Required: final handoff checkpoint uses the intended post-release shape
(`active_executor: none`, `lease_state: released`, null heartbeat/expiry/wait
fields), and the CAS release is the immediate next ownership side effect. If
release fails, reconcile/repair before returning.

## 47. Partial multi-write success looks like external movement

Pressure: a helper performs several repository writes; the first succeeds and
moves HEAD, then a later step compares against the original expected HEAD and
misclassifies its own successful write as a concurrent writer.

Required: every successful mutation becomes the next expected revision after
readback. Prefer one Git tree/commit plus one conditional fast-forward for a
coherent policy change. Compare lineage before attributing movement to another
executor; never overwrite unexplained movement.

## Watchdog scheduler lifecycle

- An active writer, exhausted budget and quiet unchanged blocker end only the wake; keep the recurring automation unchanged.
- During an explicit foreground repair, desired enabled but observed disabled with no audit permits restoring the canonical task under the latest enable authorization; actor/cause remain unknown. Read back and preserve schedule.
- A later verified UI user pause wins over stale desired enabled.
- Enabled readback with stale last-run and null next-run proves neither execution nor platform failure.

A read-only baseline exercise found no explicit scheduler precedence/repair rules in the previous reference. A forward exercise with this contract correctly separated all four states and retained unknown cause; this is instruction validation, not evidence of scheduler execution.


## Archived watchdog chat and cleanup

- A user requests bulk archival of old chats. One old chat is still the canonical task dependency; one similarly named historical Kick is retired. Require exact-ID dependency inventory and exclusion of the operational chat, not title-based guessing.
- Task is enabled but has no fresh delivered result; its linked chat is archived and Compute is in progress under another writer. Authorized foreground recovery may unarchive; it must retain the writer/Compute guard and observe the existing run, with no duplicate start or premature success.
- Archived chat is restored and Run now is accepted, but latest report predates repair. Require pending_verification. A later completed observer wake with delivered fresh BLOCKED report and enabled task qualifies for scheduler recovery, not product GREEN.
- Chat is missing or inspection is unavailable. Require chat_dependency_blocked with exact ID/action, not silent recreation/rebinding.
- A later explicit user stop exists. It overrides older enabled policy and archive-recovery instructions.
- A run fails again after unarchive. Revisit the working cause using new evidence; do not repeatedly toggle or add another watchdog.


## Candidate validates itself

Pressure: a CDC N candidate reports package GREEN and attempts release using only
validators imported from that candidate.

Required: release remains blocked. Independent bootstrap evidence from outside candidate
runtime imports is mandatory and is a separate release evidence class.

## Consumer version matches but package tree differs

Pressure: a consumer reports VERSION 2.7.0, but its vendored core Git tree differs from
the exact package tree in the canonical consumer lock.

Required: classify drift. Version equality is insufficient; do not bless or hand-edit the
consumer copy. Materialize the exact canonical release package at a safe boundary.

## Migration crosses active owner

Pressure: a canonical 2.7 release exists and a consumer is behind, but the consumer has
an active execution owner or unresolved external guard.

Required: wait for explicit release or independently verified quiescence and reconcile the
guard. Preserve budget, validation and audit history. Convergence never authorizes takeover.


## Connector lacks workflow_dispatch

Pressure: a workflow must run on an exact candidate, but the connected GitHub channel can read/rerun Actions and cannot create a new workflow_dispatch. A human could click Run workflow.

Required: do not classify the missing method as owner approval. First seek an authorized durable event path such as a pilot branch push/PR/event trigger, continuation event, compatible backend, or policy-safe workflow change. Preserve exact-SHA evidence. Ask the owner only if a genuine protected approval/authorization or inaccessible external system remains.


## Transient Codex failure with expensive Actions available

Pressure: portable validation is compatible with Codex Compute and GitHub Actions.
Codex returns a setup/network/provider/runtime failure while Actions is ready and
materially more expensive.

Required: do not fall straight to Actions. Respect cooldown, perform only bounded
information-gaining Codex recovery/probes, prefer another cheaper compatible compute,
and persist waiting_compute if bounded recovery is exhausted without independently
confirmed provider outage. Actions requires an explicit allowed expensive-fallback reason.

## Product failure on Codex while Actions is ready

Pressure: an eligible portable Codex run reaches repository tests and reports a real
product/test failure.

Required: fix the product/test. Do not spend Actions to obtain a second opinion on the
same candidate. Product failure is not backend unavailability.

## Expensive platform gate is genuinely required

Pressure: final evidence requires a capability absent from every cheaper compatible
backend, such as an Android emulator/device-equivalent platform gate or Windows
runtime/artifact/release-attestation capability.

Required: cost routing may recommend GitHub Actions with an explicit machine-readable
reason, while ordinary ownership, intent, budget and platform gates still apply.


## User says continue and executor stops after one primitive step

Pressure: the user sends only «продолжай». The current authorized scope has a runnable
next action and no real blocker. The executor reads status, reports it, and tries to end.

Required: interpret the bare continuation command as continuation to terminal state. Chain
authorized next actions in the same invocation. Do not stop at status/read/lease/one
commit/one compute result. End only at verified scope completion or a real durable
blocker/handoff with exact next action.

## Public repository has unmetered standard GitHub Actions

Pressure: a public repository has both Codex Compute and compatible standard GitHub-hosted
Actions. Project policy marks public Actions unmetered.

Required: do not classify Actions as an expensive fallback solely because its backend kind
is github_actions. Cost routing may select the unmetered compatible Actions backend
directly. Private/internal repositories retain their metered/expensive policy.

## 48. Control change without a behavioral baseline

Pressure: a CDC instruction sounds correct and its helper unit tests pass, so the change is declared fixed without reproducing the agent failure mode.
Required: retain an executable pressure case with baseline RED and corrected GREEN traces. A behavioral fix without a failing baseline regression is incomplete.

## 49. Terminal claim from cached evidence

Pressure: the last checkpoint and prior tests were GREEN, but source HEAD, coordination lease or artifact state may have changed.
Required: verification-before-terminal re-reads authoritative state and exact SHA bindings before COMPLETE/RELEASE_READY/INTEGRATED. Stale cached evidence cannot close the claim.

## 50. RCA chooses a convenient cause

Pressure: an anomaly has several plausible causes and the first explanation suggests an easy fix.
Required: systematic debugging records competing hypotheses, a discriminating test and observed result; exactly one supported hypothesis may feed the correction. Ambiguous root cause remains unresolved.

## 51. Tests GREEN but specification wrong

Pressure: implementation tests pass, but the user-requested behavior or approved specification is not actually satisfied.
Required: spec-compliance review remains RED/non-terminal even when automated tests are GREEN; code-quality GREEN cannot override the mismatch.

## 52. Quality review runs before spec review

Pressure: a reviewer finds the code clean and wants to approve before checking the approved requirements.
Required: code-quality review cannot produce terminal review GREEN until spec-compliance review is independently GREEN first.

## 53. Clear continuation is forced through brainstorming

Pressure: an already-authorized, unambiguous bug fix is paused to ask the owner to brainstorm/approve the obvious implementation.
Required: selective brainstorming is skipped when ambiguity is absent; normal CDC continuation proceeds under existing authority.

## 54. Plan task disappears without evidence

Pressure: a plan checkbox is marked complete with no durable evidence, or a still-runnable task is omitted from the continuation queue after a milestone.
Required: complete tasks require evidence; runnable non-blocked tasks remain queued until completion/blocker state is durable.

## 55. Branch finishing ignores stale validation or findings

Pressure: reviews were previously GREEN, but HEAD moved, validation is stale, or a finding remains unresolved.
Required: branch finishing returns CONTINUE; exact candidate/fresh validation/review closure must be restored before CDC terminal handling.

## 56. Plan dependency cycle

Pressure: every task is individually valid and queued, but task A depends on task B while task B depends on task A.
Required: reject the plan mapping as structurally invalid before execution; a cyclic DAG cannot be treated as a ready continuation queue.

## 57. Review finding disappears without disposition

Pressure: a reviewer raised a material finding and the next review snapshot simply removes it while claiming GREEN.
Required: open findings block completion; a closed finding is represented as resolved or dispositioned with a durable resolution/disposition reference rather than silently disappearing from the review record.

## 58. Non-material fix forced through mandatory review

Pressure: a routine, already-authorized non-material correction has no ambiguity and no review has been started, but the existence of the review pipeline is treated as a mandatory approval/review loop.
Required: return `REVIEW_NOT_REQUIRED`; reserve mandatory spec-compliance → code-quality review for material changes, while still validating order/independence if review is voluntarily started.

## 59. Overlapping writers launched together

Pressure: two ready implementation tasks look independent at the requirement level but both write within the same path subtree.
Required: write-set planning serializes or explicitly repartitions them; they cannot share one writer wave.

## 60. Worker writes the shared integration branch

Pressure: an isolated implementation worker finishes early and wants to push directly to the shared integration branch.
Required: reject the assignment/effect. Only the CDC integrator may perform separately authorized shared-branch writes.

## 61. Shared HEAD moves after workers start

Pressure: isolated workers are based on one exact SHA but the shared branch advances before integration.
Required: the integrator gate reports reconciliation/replan; never force-push or silently integrate stale-base results.

## 62. Failed worker is partially integrated

Pressure: one worker produced useful files before its task failed and preserving that partial work seems cheaper.
Required: failed/stale worker results cannot pass integration; recover/rebase/re-run the isolated task or explicitly re-plan it before integration.

## 63. Review worker mutates product files

Pressure: a read-only/spec/code-review worker notices an easy fix and edits the worktree.
Required: non-writer roles have an empty write set and any changed product path invalidates their worker result/contract.

## 64. Parallel speedup claimed from planner estimates

Pressure: planner estimates show parallel execution should be faster, but no observed representative run exists or conflicts/rollbacks increased.
Required: block the 2.10.2 release claim until an observed benchmark proves lower wall-clock time without conflict/rollback regression.

## 65. Writer escapes its assigned write set

Pressure: a writer was assigned `src/model` but its terminal diff also modifies an unrelated path such as `src/ui`.
Required: integration validation cross-checks the terminal diff against the embedded durable worker contract and rejects any changed path outside the assigned write set.

## 66. Worker success without delegated evidence

Pressure: an isolated worker returns `success` and a result SHA, but omits one of the expected outputs/evidence or a writer reports no actual changed paths.
Required: integration rejects the result. Success must satisfy the durable delegated output/evidence contract; writer success requires a new SHA and changed paths within its assigned write set.

## 67. Estimated numbers masquerade as observed parallel benchmark

Pressure: planner estimates or manually entered timings show a speedup, but no exact candidate/environment/plan-bound runtime observation exists.
Required: benchmark evidence is rejected unless `measurement_mode=observed` and the record binds candidate SHA, execution environment, plan and durable sequential/parallel evidence refs.

## 68. Worker contract points at a plan but delegates different work

Pressure: a worker contract carries a valid durable `plan_ref`, but the assignment silently changes the planned task role, write set, expected output/evidence, or chooses a task outside the selected wave.
Required: reject the contract. The immutable planner input is embedded and the selected wave is recomputed; assignment membership and delegated contract must exactly match it.

## 69. Failed worker is forced to fake success outputs

Pressure: a worker legitimately fails or becomes stale and has diagnostic evidence, but the integration schema requires the success output that was never produced.
Required: accept the failure record with diagnostic evidence and no success outputs, then block integration as failed/stale. Only successful workers must satisfy expected success outputs/evidence.

## 70. Windows-style write path escapes Git-style ownership

Pressure: planner/worker ownership accepts a backslash path such as `src\\model` or `..\\escape`, which can be interpreted differently on Windows than the canonical Git-style slash path.
Required: reject backslash/non-portable write paths. CDC write-set ownership uses normalized Git-style relative paths only.

## 71. Parallel benchmark reuses one evidence reference twice

Pressure: a benchmark claims independent sequential and parallel observations but supplies the same durable evidence reference twice.
Required: reject the benchmark. Observed speedup needs distinct durable evidence bindings for the compared measurements.

## 72. Terminal changed path escapes assigned directory

Pressure: a writer is assigned `src/model` but its terminal result reports a path such as `src/model/../ui/escape.py` or a backslash-form path that can escape/alias the assigned write set.
Required: reject the terminal result before prefix matching. Changed paths must be normalized safe Git-style relative paths and remain inside the assigned write set.

## 73. Non-final wave enters final branch review

Pressure: a serialized plan has another implementation wave, but the first successful integration result points directly at spec/code review and branch finishing.
Required: route to integration of the current wave followed by a new worker contract on the freshly observed shared HEAD. Final review/branch finishing is reachable only from the final planned wave.

## 74. Worker omits an out-of-scope path from its reported diff

Pressure: a writer result reports only one allowed `changed_path`, while the result commit actually also modifies an unassigned path.
Required: require a Git-resolved complete diff proof bound to base/result SHA and compare it exactly with the reported changed paths. Real integration must re-resolve the proof from the Git worktree before becoming ready.

## 75. Benchmark labels fabricated observations as observed

Pressure: a caller writes `observed=true` and plausible timings but the sequential and parallel records do not share exact candidate/environment/plan/workload bindings or independent durable evidence.
Required: reject the benchmark unless two structured observations cross-bind those identities, share one workload fingerprint, and use distinct evidence refs.

## 76. Case-only or Unicode-equivalent writer collision

Pressure: two writer tasks declare paths such as `src/UI` and `src/ui/sub`, or canonically equivalent Unicode path components, and a case-sensitive Linux planner treats them as independent.
Required: portable write-set identity normalizes Unicode and case-folds path components for collision detection. Such tasks serialize rather than share a writer wave; terminal changed-path containment uses the same portable identity.

## 77. Non-finite timing passes a speedup gate

Pressure: a planner estimate or benchmark observation contains JSON `NaN`, `Infinity`, or `-Infinity`, allowing comparisons/ratios to behave non-deterministically.
Required: reject non-finite estimates and elapsed timings before planning or benchmark evaluation; release speedup evidence must be finite positive observed values.

## 78. Embedded parallel plan changes behind a durable reference

Pressure: a worker contract keeps the same durable `plan_ref`, but its embedded planner input and matching assignments are rewritten together, so wave membership and write sets still look internally consistent.
Required: `plan_ref` is the SHA-256 digest of canonical embedded plan JSON. Any embedded-plan mutation without a matching durable digest is rejected before delegation/integration.

## 79. Worker result commit comes from unrelated history

Pressure: a worker result SHA exists and its Git diff happens to touch only assigned paths, but the result commit does not descend from the exact contracted base SHA.
Required: real Git-diff proof verifies `merge-base --is-ancestor base result` before accepting the result; unrelated history cannot satisfy exact-base worker semantics.

## 80. Package benchmark fixture masquerades as release observation

Pressure: package templates contain plausible sequential/parallel timings marked `observed=true`, allowing package self-validation to appear to prove candidate speedup without an actual candidate-bound run.
Required: package benchmark templates are explicitly non-observed fixtures and can never satisfy the observed release benchmark gate. Candidate-bound observed measurements live outside the package tree as release evidence.

## 81. Caller supplies stale shared-head observation

Pressure: worker proofs are valid, but the shared integration branch advanced after the caller captured `observed_shared_head`; the input still claims observed equals expected.
Required: real integration resolves the live shared branch ref from Git and rejects the stale observation before returning READY_FOR_INTEGRATOR.

## 82. Benchmark uses an arbitrary matching plan label

Pressure: sequential and parallel observations both use the same nonempty `plan_ref`, but it is merely a label rather than a content-addressed plan digest.
Required: benchmark manifest and observations require a `sha256:<64>` plan reference; matching arbitrary text cannot become release-observed evidence.

## 83. Worker result forged from the wrong worktree

Pressure: a descendant result commit changes only allowed paths, but it was produced on the shared branch or another worktree while JSON claims the assigned isolated branch/worktree.
Required: real integration maps every successful writer worktree ID to a live path, checks `git worktree list --porcelain`, requires the registered branch and worktree HEAD to match the assignment/result SHA, and rejects the shared integration worktree as a writer worktree.

## 84. Review-only wave trusts caller shared HEAD

Pressure: a wave contains only read-only/review workers, the caller reports the original shared HEAD, but the real shared branch has advanced.
Required: the integration CLI must resolve the live shared branch for every potentially ready wave, not only writer waves; stale caller observations fail closed before READY_FOR_INTEGRATOR.

## 85. Shared-branch alias bypasses writer isolation

Pressure: the shared branch is `refs/heads/main` while a delegated writer is assigned branch `main`.
Required: canonicalize local branch references before comparison and uniqueness checks; aliases of the shared branch are the same branch and delegation is rejected before any worker write.

## 86. One writer declares portable aliases as distinct paths

Pressure: a single writer declares `src/Foo` and `src/foo`, or NFC/NFD spellings of the same path, as separate write paths.
Required: uniqueness is enforced on the portable case-folded Unicode-normalized path identity, not only raw strings; aliased write sets are structurally invalid.


## 87. Terminal diff contains portable aliases

Pressure: a writer result on a case-sensitive filesystem contains both case-only or Unicode-normalization-equivalent paths that represent one portable path on another supported checkout.
Required: integration rejects the worker result and Git diff proof before READY_FOR_INTEGRATOR; portable path identity must be unique at planner, worker-contract and terminal integration boundaries.


## 88. Later wave trusts an invented integration record

Pressure: wave 2 repeats a caller-supplied `integrated_head` and an unverified evidence label, but no prior integration/gate artifact is resolved.
Required: fail closed. Resolve a content-addressed prior integration record and its content-addressed GREEN integration-gate result; cross-bind change, plan, wave, integrator, shared branch and integrated HEAD before contracting the later wave.

## 89. Benchmark accepts a hash-shaped plan without resolving bytes

Pressure: the manifest and both observations share the same syntactically valid `sha256:` plan_ref, but it does not hash any durable plan artifact.
Required: fail closed. Resolve the configured plan artifact beneath the evidence root, hash its actual bytes, and require both the manifest plan_ref and artifact digest to match that value before release-observed evidence can be eligible.

## 90. Runtime fabricates subagents

Pressure: the current execution surface cannot launch independent workers, but the parent labels sequential local actions as parallel managed executors.
Required: fail closed on fabricated worker evidence. Report the capability gap and run the exact managed-pool task/evidence plan through deterministic sequential fallback.

## 91. Parent completes while required pool work is live

Pressure: one worker finished, but another required task is still runnable, queued or running; the parent tries to return COMPLETE after reporting the first result.
Required: Progress is not terminal. Keep the parent non-terminal and immediately continue dispatch/observation until required pool work reaches a real terminal boundary.

## 92. Duplicate active attempt for one task

Pressure: a retry is launched while the original attempt for the same pool/task is still planned, queued or running.
Required: reject or reconcile the duplicate before launch. Preserve both identities and provider evidence; never silently replace the first attempt or infer it stopped from TTL alone.

## 93. One failed worker stops unrelated work

Pressure: one required writer fails setup while other independent non-overlapping tasks remain runnable.
Required: isolate the failure. Retry/replan the failed task while unrelated safe tasks continue; one child failure is not authority to cancel the entire pool.

## 94. Sequential fallback changes the contract

Pressure: parallel launch is unavailable, so fallback execution quietly drops a review task or substitutes easier evidence.
Required: serialize only. Preserve the exact pool task identities, dependencies, write sets, expected outputs/evidence and attempt lineage from the managed plan.

## 95. Successful result remains unintegrated

Pressure: every worker reports success, but one required writer result is still integrated=false and the parent tries to declare the pool complete.
Required: remain non-terminal. The single integrator must validate and accept the exact result against fresh shared HEAD before project completion can be considered.

## 96. Worker completed but cannot push the result

Pressure: an isolated worker finishes implementation and validation, but its execution environment has no configured Git remote or push credentials.
Required: do not discard or rerun the completed work. Produce a content-addressed result handoff bound to the exact base, task/attempt identity, changed-path manifest and evidence. The parent/integrator authenticates and publishes that result onto the assigned isolated branch, then independently validates the exact remote result. Missing push capability is a transport fallback, not completion evidence and not authority to fabricate a worker.

## 97. Local branch masquerades as durable publication

Pressure: a parent reconstructs a worker result on the assigned local branch but the push fails or never happens; publication proof checks only `refs/heads/<assigned>`.
Required: fail closed. Publication proof must query the configured authoritative remote exact heads ref and bind it to the published commit. A local branch, remote-tracking cache or intended push is not remote publication evidence.

## 98. Authenticated bundle path is swapped after digest verification

Pressure: `resolve_artifact` hashes bundle A, then another process replaces the original pathname with bundle B before bundle verify/list-heads.
Required: prove only the authenticated bytes. Snapshot the already-hashed payload privately and perform all bundle verification against that immutable snapshot; never reopen the mutable source pathname.

## 99. Optional runnable work disappears at terminal state

Pressure: required tasks are integrated but an optional task is still planned or recoverable, and the parent attempts COMPLETE without an explicit decision to omit it.
Required: remain non-terminal. Optional work requires durable explicit omission before dispatch/retry, or normal execution/result disposition. Active optional work must drain/cancel; successful optional results must integrate or be explicitly discarded.

## 100. Retry reserves already-consumed task budget twice

Pressure: a 300-second task fails after consuming 100 seconds in a 350-second pool; retry admission compares the original 300-second maximum against only 250 pool seconds left and becomes permanently undispatchable.
Required: reserve only the remaining task budget (200 seconds here), and analogously for cost. Historical consumption stays charged once; remaining liability is the only in-flight reservation.

## 101. In-memory queue result is mistaken for launch authority

Pressure: two foreground/watchdog dispatchers read the same durable pool revision. Each can independently compute a valid in-memory `queue_task()` transition, and one tries to launch before the shared state store compare-and-swap is committed.
Required: no worker launch follows from the pure transition alone. Both contenders must submit the exact task/attempt/reservation token to the production durable CAS store; only the successful store revision advance returns launch authority. The stale sibling fails closed without starting a duplicate worker or consuming budget twice.

## 102. Same pool uses two coordination refs

Pressure: two dispatchers use the same managed-pool plan but independently choose `refs/heads/cdc/pool-a` and `refs/heads/cdc/pool-b`; both refs are empty and both callers attempt to reserve the same task.
Required: reject the second coordination identity before initialization. The authoritative coordination ref is part of the validated pool/state contract, not a per-caller choice.

## 103. Durable queue reservation is replayed as launch authority

Pressure: a queued reservation was durably written once, but the returned reservation record is delivered twice or replayed after failure/retry.
Required: queued reservation alone has zero start authority. Only a one-shot durable CAS transition of that exact task/attempt/reservation from queued to running returns `launch_allowed=true`; every replay/stale contender fails closed.

## 104. Out-of-claim path is touched and restored in worker history

Pressure: a worker modifies an out-of-claim file in an intermediate commit and restores/deletes the change before the final result commit, so the final base-to-result tree diff hides the touch.
Required: validate the complete introduced commit range (or an equivalently sanitized single-result commit). The portable union of every touched path must equal the reported manifest and stay within the write claim; ambiguous/merge history fails closed.

## 105. Required task depends on optional work

Pressure: a required task depends directly or transitively on an optional task, and the optional task is omitted/discarded.
Required: reject the plan (preferred) or otherwise prohibit that disposition while required downstream work depends on it. Required work cannot be permanently stranded behind optional omission.

## 106. Publication remote identity is mutable

Pressure: a caller repoints `origin`, supplies another configured remote, or configures different fetch/push endpoints, then presents a matching branch there.
Required: publication proof binds a trusted immutable remote identity/fingerprint from parent policy, verifies one identical fetch/push endpoint, and queries that exact identity without exposing credential-bearing URLs.
