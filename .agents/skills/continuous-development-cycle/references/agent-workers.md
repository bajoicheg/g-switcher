# Model workers — Phase 1 candidate

The `cdc-agent-task/v1` envelope supplements the existing native pool. It does not change any pool, attempt, bridge or lease record. The model provider is separate from the compute backend. `AgentWorker` is a Python facade, not a scheduler or a new admission authority.

## Packaged examples

Use `templates/agent-task-v1.json` with `templates/agent-developer-pool-v1.json` for a developer, and `templates/agent-review-task-v1.json` with `templates/agent-reviewer-pool-v1.json` for the opposite-provider reviewer. These are synthetic declarations: replace placeholder commits, task/pool IDs, model, project/repository and coordination endpoint identity with host-authenticated values before admission. No template grants a budget, lease or permission. Reviewer `required_tests` must be `[]`; reviewers inspect the developer's test evidence without executing potentially modifying checks.

Both native plans are immutable. Create the reviewer plan only after the checked developer result has an exact commit. Its base is that proposed head; `review_of.base_sha` remains the developer's original base. Use distinct pool/task/attempt/budget-event identities. A new review stage does not rearm a failed or unknown developer attempt.

## Host construction and one original start

The following code runs inside the existing authorized host lifecycle. `plan`, `envelope`, `original_binding`, repository paths, source/coordination remotes, executable and account/profile are authenticated host inputs, never authority taken from the envelope. Original native lease admission, actual provider eligibility and operating-system containment must already be supplied by the host. Credentials are not part of these JSON examples.

```python
from datetime import datetime, timezone
from agent_worker import AgentWorker
from managed_executor_runtime import ManagedExecutorRuntime, LocalCommandBackend
from managed_executor_store import GitManagedExecutorStore
from project_budget_store import GitProjectBudgetStore

def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

# The original pool and project budget registration already exist remotely.
store = GitManagedExecutorStore(
    repo_root, coordination_remote, plan['coordination_ref'], plan,
    protected_refs=[original_binding['source_ref'], original_binding['coordination_ref']],
)
runtime = ManagedExecutorRuntime(
    plan, store, repo_root, LocalCommandBackend(private_journal_root),
)
budget_store = GitProjectBudgetStore(budget_repo, coordination_remote, original_binding)
worker = AgentWorker(
    runtime, envelope, qualified_cli_path,
    project_id=authenticated_project_id,
    repository=authenticated_repository,
    model_budget_binding=original_binding,
)
reservation = {
    'type': 'reserve', 'event_id': original_event_id,
    'task_id': original_binding['task_id'], 'wake_id': authorized_wake_id,
    'at_utc': utc(), 'operation_key': worker.operation_key(original_attempt_id),
    'attempt_id': original_attempt_id, 'kind': 'agent_start',
    'scope': 'agent-task:' + worker.contract_digest, 'recovery_ref': None,
    'cost': {'tool_calls': 1, 'tokens': envelope['budget']['tokens'],
             'elapsed_seconds': envelope['limits']['timeout_seconds']},
}
budget_revision, _ = budget_store.read()
budget_store.append_event(budget_revision, reservation)
# Preserve the returned original event and its remote readback before launch.
revision, _ = store.read()
worker.start(revision, original_attempt_id,
             reservation_token=original_event_id,
             model_budget_store=budget_store, reservation_event=reservation)
```

If reserve or launch returns uncertain evidence, observe the original stores and attempt. Do not repeat this block, invent a new event, close an unknown charge as free or start another provider automatically. The existing native CAS is the sole launch boundary. Tokens are unknown when null; this is not unlimited or free usage. The charged start is separate from a measurable usage receipt.

## Observation, cancellation and reconstruction

`worker.get_status(original_attempt_id)` observes the original native process. `worker.cancel_execution(original_attempt_id)` requests original cancellation; retain custody until the supervisor proves descendants stopped. Native `awaiting_release` requires the original host's transactional lease closeout. An elapsed timeout, disconnected terminal or missing output is not proof of process absence.

After host restart, reconstruct the exact runtime/store/worker from the persisted immutable plan, envelope, executable, CLI variant and original budget binding, using the same journal root. Call `get_status` or `collect_result`, never `start`. A changed prompt, executable, provider, variant, model, original reservation or plan cannot borrow another execution's result. Missing/corrupt provider terminal output remains unknown even after process exit zero.

## Checked commit and independent review

1. Collect the developer result only after original native custody and physical closure have been reconciled. Require provider success, native exit zero and every exact deterministic command's real zero exit. Retain command, timestamps and private output references. Never infer live provider success from synthetic fixtures.
2. The host verifies changed paths against the original native writer claim and commits the checked bytes in that assigned worktree. `runtime.accept(..., result_commit=head, output_refs=..., evidence_refs=...)` validates native result acceptance. This is distinct from integration/publication and requires the original host authority.
3. Admit a new read-only native reviewer at that exact head with the opposite provider, the original base/head diff, acceptance criteria and authenticated developer check references in `review_of.test_evidence`. References are host-supplied evidence; the envelope alone does not authenticate them. Do not place secrets or raw private sessions in a prompt.
4. Start that reviewer once under its own original charged reservation. Both default CLI directions use this same interface. The reviewer receives the actual Git diff. It runs no developer checks, owns no write path and must retain exact tracked bytes/modes and no untracked/ignored changes. An unchanged `git status` alone is insufficient.
5. `collect_result` returns structured `approved`, `changes_requested` or `blocked` findings. Approval requires successful original execution, complete receipts and an unchanged exact snapshot. Missing evidence blocks approval. `max_iterations:1` is one review round; requested changes need separately admitted work, without resetting the original result or charge.

The facade always reports `accepted:false`: provider evidence cannot grant final integration, release, publication, lease release or human approval. Existing native acceptance/integration and human gates remain separate. Required human approval and deterministic tests cannot be replaced by a model verdict.

## Original budget closure

After verified original terminal/quiescent evidence, the host appends one `outcome` event for the original reservation through the existing `GitProjectBudgetStore`. Use the same project task and wake, a distinct outcome event ID, actual current UTC time, `reservation_id=original_event_id`, the observed terminal status and actual measured usage (otherwise null). `failure` follows the existing budget contract. Preserve unknown dispositions and the original charged start; do not issue a compensating reset. Read back and reconcile an uncertain append before another effect. Native pool runtime/cost accounting and model usage are separate records.

## Validation and deferred live operation

Automated tests use real local Git repositories, native CAS and actual supervised processes with synthetic CLI executables. They cover both developer→opposite-reviewer directions, actual check-reference transfer, concurrent isolated worktrees, conflicting claims, cancellation/timeout, provider failure and reconstruction during an active original invocation. They do not prove real Google eligibility or live model behavior.

The owner deferred live Gemini connection and subsequently requested Kimi Code as the second live provider. Deterministic tests require no login or model invocation; live Codex+Kimi qualification is a distinct acceptance gate. The optional explicit Antigravity parser/command variant is an unadopted technical prototype; consumer subscription wrapping inside third-party agent applications is unsupported by Google's documentation. Production rollout retains a separate concrete qualification and owner approval gate. Repository `docs/multiprovider.md` records the current delivery scope and rollout/rollback procedure.


## Kimi Code host policy

Use only source-qualified official CLI2.2.0 with the packaged explicit developer
or reviewer agent file. The reviewer tools are Read/Glob/Grep; developer tools
add Write/Edit. Neither profile exposes shell, skills or delegation. The native
check runner executes the registered checks after the provider exits. Agent
file hashes are bound into the original Kimi operation key and immutable CLI
configuration; changing them cannot attach to an earlier attempt.

Print mode internally uses auto permissions. The host must enforce native OS
containment, immutable packaged agents, isolated HOME/KIMI_CODE_HOME, an empty
explicit skills directory, verified retry-limited config and no hooks/MCP/user
extensions. Set max_attempts_per_step=1 and compaction_max_attempts=1 in the
profile's loop_control section; set KIMI_LOOP_MAX_ATTEMPTS_PER_STEP=1,
KIMI_CODE_INFINITE_RETRY=0 and KIMI_CODE_NO_AUTO_UPDATE=1. There is no CLI config
flag. Pin profile/config/environment in the trusted host wrapper without
recording credential contents. Internal credential/media recovery is not proven
absent; observable retry metadata is rejected.

Kimi JSONL success requires first system.version2.2.0, completed tool calls, a
final assistant answer and one last session.resume_hint, plus native exit/check
evidence. The hint is never executed; session resume/retry is not authorized.
The witness is qualified from pinned source, not a stable documented result
schema. Usage stays null. Requalify before any CLI upgrade.
