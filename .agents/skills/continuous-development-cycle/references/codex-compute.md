# Per-mode entry qualification (2.13.0)

## Cloud new-chat entry (2.13.0)

First read the actual project AGENTS, source HEAD, checkpoint, lease/guard and journal. Preserve known operations before setup or a new request. The connected native Cloud runtime is an execution route; official UI and authenticated official CLI are separate modes. CLI401 or unknown nested inventory does not invalidate qualified native work and does not authorize an auth retry, Codespace start or a second executor.

For the canonical source checkout, prepare the typed, hash-bound current observations with:

```sh
python -B src/continuous-development-cycle/scripts/codex_cloud_entrypoint.py prepare --profile docs/cdc-cloud-profile.json --inputs docs/cdc-cloud-entry-inputs.json --project-root .
```

In a consumer, use its actually verified vendor root in place of src/continuous-development-cycle. The installed personal loader uses its verified extracted package path. Inputs are project-local snapshots under cloud-entry-inputs/v1, never credentials or cached authority: context/probe/registry/routing_policy/routing_context references each bind exact UTF-8 JSON file bytes with SHA256. Expanded form uses --context, --probe, --registry, --policy (alias --routing-policy), --routing-context. The profile template is explicitly UNCONFIGURED until genuine per-mode namespace/ID, policy/setup and fresh native host evidence are supplied; null fingerprints/unknown CLI labels fail closed. A native display label alone is metadata. --now is test-fixture-only.

Preparation returns ONE typed next_action, not permission to run it. CONTINUE_NATIVE uses the existing registered managed caller for its exact approved argv; OBSERVE_EXISTING/RECONCILE_EXISTING/INTAKE_EXISTING use the original same-key transport, preserving unknown/submitting effects. READY_FOR_SUBMIT requires the existing fresh owner/intent/guard/budget/one-use callback; no UI-to-CLI or mode/namespace substitution. Qualify only the selected mode; never repeat broad provider inventory just to use this connected native host. Read references/cloud-fast-start.md.

Recovery v2 selection uses current source/environment/policy/input digests and durable append-only history. The existing authorized caller records genuine started/unknown/terminal observations through record_history with fresh callback/CAS/readback. A consumed fingerprint needs explicitly bound unused correction evidence; a reason string, new chat or unrelated proof is not a retry. Unknown/submitting state is observe/reconcile-only. Reused verified dependency/result evidence skips installation/investigation; a concrete record_blocker result is preserved. Recipes do not execute arbitrary shell or grant ownership.

Watchdog resumes use the same entry and actual current facts; inherited paused status remains paused. Do not enable/rebind/reschedule a watchdog or reopen product/security/platform gates to complete CDC metadata.

# Priority Codex Compute

## Supported Codex Cloud CLI transport (2.11.6)

Complete and persist the bounded provider inventory plus actual environment/source readbacks before reserving the short-lived submission grant. Recheck each observation's freshness after slow reads, after claim preparation and at the runner's immediate effect gate. Do not repeat the full paginated inventory inside `launch_authorized`; that authority-only callback must not send provider work. The CLI adapter records `not_submitted` with a fsynced `cancelled_before_send` journal when this callback raises. It writes `started` before entering the runner; an exception after that boundary is `unknown`. Both journals survive reconnect and refuse resubmission. Cancellation is not validation success and does not itself clear a lease guard. A journal predating this protocol or a process interruption without the cancellation record retains uncertainty.

Use `CodexCloudCLI` from `scripts/codex_cloud_cli.py` with the authenticated official CLI. Version 0.160.0 was verified through the authorized Codespace on 2026-10-05. Supported commands are `cloud exec --env ID --branch BRANCH --attempts 1 QUERY`, `cloud list --json --limit 20 --cursor CURSOR`, and `cloud status TASK_ID`. The adapter never reads credentials, calls private HTTP endpoints or applies diffs. Official command definitions: https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/cloud-tasks/src/cli.rs.

Construct `codex-cloud-cli-request/v1` with operation_key, attempt_id, canonical repository, exact candidate_sha, environment_id, environment_label, source_branch and checks (`id`, exact `argv`, `minimum_test_count`, nullable for non-test commands). Use the existing operation-intent binding and durable budget/guard protocol before submission. Provide `submit(request, launch_authorized=callback)` with an in-memory callback checking the fresh exact claimed guard/grant, reservation and remote branch SHA immediately before exec. The callback is not persisted, restored or inferred from a Boolean. The transport's local lock/journal prevents repeats in this host; caller coordination provides cross-host admission. Restored submitting/unknown state is observation-only. Do not erase a journal or invent a new operation key to retry an uncertain dispatch.

Observe through `observe(operation_key)`. Unknown reply recovery inventories every cursor page and filters locally: CLI 0.160.0 was observed returning other environments despite --env. Require one exact operation/attempt title marker and matching environment ID (or the explicitly verified label when provider omits IDs). Conflicting rows, ambiguity, repeated cursors or exhausted page bounds remain unknown. Provider titles may omit the marker; this is a recovery capability gap, not permission to resubmit. Preserve the external guard and reconcile the actual task/report through an authorized host.

Provider READY yields waiting_report and validation_passed=false. The CLI has no supported machine export of the completed assistant report. An observing host reads the report through the official TUI and persists it with the exact task ID from CLI; it must distinguish observed fields from supplied expected bindings. Call `ingest_report(operation_key, report, evidence_ref)` only after observed READY. `codex-cloud-cli-report/v1` binds task_id, operation_key, attempt_id, repository, environment_id/label, head_before/head_after, clean_before/clean_after and checks. Each check supplies exact id/argv, actual integer exit_code, observed test_count and SHA256 of its complete log. The adapter checks these bindings and refuses rewritten terminal reports. Successful transport submission or READY is never package/platform/release GREEN. Log digests identify observed logs; they do not imply that full logs were downloaded.

Persist a well-formed exact-task failed verification as `failed`, including observed source/cleanliness mismatch or insufficient observed test coverage. A failed preflight may report `result: "NOT_RUN"` and `checks: []` even when its observed SHA/cleanliness match. Persist this exact-task result as failed, without invented command exits or logs. NOT_RUN with command evidence is contradictory and rejected. An explicitly reported repository_identity_status=MISMATCH cannot pass matching checks. Matching-source success still requires every planned check and its evidence. Unrelated/malformed reports are rejected. Journal recovery revalidates the report digest, immutable bindings, observed READY and conclusion; an asserted journal status never creates validation success.

The default `portable_primary_preferred=true` cost policy implements the owner's CDC Cloud preference even when public Actions are configured as unmetered. Recover/wait for transient primary failure. Older policies lacking this optional field retain their previous cost ordering. Required platform/release CI remains separate.

## Contents

- Eligibility and authority
- Access and environment setup
- Exact-SHA request and monitoring
- Results, failures and fallback

## Eligibility and authority

Use Codex `COMPUTE_ONLY` as the first choice for candidate checks that its actual environment can execute: compilation, unit/regression tests, lint, schemas and deterministic contracts. Record commands and platform requirements in the repository adapter. A Linux build can produce an Android APK without proving emulator/device execution, installation, Doze or phone acceptance. Keep required final platform/CI gates explicit.

The orchestrator owns source edits, reviews, integration and task closure. A compute worker receives only bounded read-only commands and reports evidence. Its contract forbids tracked edits, fixes, commits, push, merge, PR creation, implementation delegation, Actions launches and watchdog changes. Tool installation/cache warming belongs to the authorized setup/maintenance phase.

Existing authorization to configure and use compute persists. Reuse connected accounts, environments and active requests. Configure reversible preparation within that scope without repeated approval. Adding collaborators, granting App access, changing billing/secrets or sending person-directed invitations requires applicable authorization; the skill does not grant it. Do not change other projects as a workaround.

Use currently available supported tools/UI and consult official documentation when a product-specific detail is uncertain. An environment ID mentioned in a prompt is a requested binding, not proof that the service selected it.

## Access and environment setup

1. Recover canonical owner/repository, branch, exact HEAD, active PR and existing CI/compute. Check for competing work before creating another request.
2. Verify **three separate prerequisites**: GitHub App installation includes this repository; the GitHub user actually connected to Codex has effective repository permission; a Codex environment is associated with this canonical repository. A working Work connector does not establish Codex access. If the selector omits a granted repository, inspect the connected login and effective collaborator/team permissions before proposing reconnects or broader App access.
3. Reuse a matching environment or create a dedicated one. Record its ID/URL, linked identity, repository, image/toolchain, setup/maintenance commands, cache policy, non-secret variables and agent network policy in the project runbook. Never copy another project's IDs or credentials into this reusable skill.
4. **Reuse the provider runtime** and verified preinstalled tools when they already satisfy the contract. Prefer **missing-only** dependency installation: detect what is absent and install only that. **Do not reinstall** JDKs, certificates, package managers or system utilities merely to normalize an image, and avoid broad system upgrades. When an OS package step needs repositories, isolate only the sources required for that step; prefer an explicit **allow-list** of trusted distribution sources when unrelated **third-party package sources** can fail independently. Pin/verify tools that truly must be added, keep bootstrap independent of target-branch checkout, and use bounded command timeouts.
5. Treat setup network access separately from agent network access. Default the agent to offline operation when all dependencies can be prepared beforehand. If curl/Python succeeds but Java/Gradle reports unreachable network, inspect the platform-provided proxy and translate it to the JVM's supported properties during setup. Do not disable TLS verification or bypass network restrictions. Keep credentials out of logs/tracked files and restore temporary configuration after the child exits; hard-kill cleanup is not guaranteed.
6. Save and read back the repository association and settings before enabling the adapter. Track configuration and execution separately: a saved environment is configured, not compute GREEN. Run one bounded verification and inspect its real task, source SHA and logs. A UI task counter can lag or exclude failed setup; use the actual task association and result.

## Exact-SHA request and monitoring

Prefer an existing active PR delegation route when it is supported. Verify the PR source branch and HEAD; issue context can select a different/default branch. Use the GitHub identity linked to Codex when that route requires it. If using direct task creation, explicitly select the verified environment and source ref.

Before dispatch, follow `references/orchestration-controls.md`: inspect active CI/compute, durably reserve budget, persist/read back the intent/guard and pass the ownership submission boundary. Refetch HEAD immediately before the side effect. Send a concrete action with no unresolved placeholders. This template must be filled before posting:

```text
@codex Run this read-only build/test task now.
COMPUTE_ONLY
Repository: <canonical owner/repository>
Source: <active PR and branch>
Exact required HEAD: <literal 40-character SHA>
Environment: <verified environment ID/URL>
Command: <exact repository verification command with that SHA>
Expected checks/totals: <current reviewed acceptance criteria>
Contract: require clean worktree and exact HEAD before/after;
stop on mismatch, dirt or setup failure; no edits, fixes, commits,
push, merge, PR creation, dependency restoration in agent phase,
implementation delegation, Actions launch or watchdog changes.
Report: before/after SHA and cleanliness, commands and exits,
test totals, build/lint status, logs, artifacts and their digests;
mark every unexecuted platform/device gate NOT_RUN.
Do not retry automatically.
```

Persist the returned request/comment ID, actual task ID/URL when available, environment ID and exact candidate SHA. Distinguish submitted, accepted, setup/maintenance, agent execution and terminal result; do not report a sent comment as an executed test.

Set `waiting_external` with the exact external identifiers. While the task is queued/in-progress, keep the source branch stable and avoid duplicate requests. If writing a status commit would move the requested HEAD, use a durable PR coordination comment containing the same checkpoint fields and its authoritative status; reconcile the checkpoint file after terminal result. Do not claim a new status commit's SHA was the tested candidate.

While runtime and budget permit, inspect the actual provider until terminal and give meaningful progress updates. Apply `references/bounded-recovery.md` for queue/setup/run/unknown thresholds, retry timing and capped polling; a missed threshold requests diagnosis, not replacement. Refresh a possibly stale UI before classifying a hang. A watchdog is a recovery path, not a reason to abandon an executable task. On forced handoff, release ownership explicitly while preserving external guard, wait/budget state, task URL, exact SHA and one next action. Do not create duplicate watchdogs or assume a scheduler is continuously running.

## Results, failures and fallback

Before another compute start after a non-PASS result, **classify the failure** as **setup**, **network**, **runtime**, or **product**. Bind the next action to that class: setup changes environment preparation; network changes only approved connectivity/proxy/source configuration; runtime changes process/time/resource handling; product changes source/tests. A new attempt in the same scope needs a concrete correction or observed service recovery, not merely remaining budget.

- **PASS:** confirm exact SHA and clean state before/after, terminal exits, actual test counts and required outputs. Preserve logs and artifact provenance in the repository; verify downloaded bytes before delivery. Advance only the gates this execution actually proves.
- **Tests/build failed:** inspect the concrete failing command/log, diagnose in the orchestrator, publish the smallest reviewed correction, then validate the new exact candidate. The compute worker must not self-repair.
- **Setup/service failed:** record infrastructure failure and which commands/tests were NOT_RUN. Inspect full setup/maintenance logs even if the PR bot gives a generic error. Re-run only after a concrete correction or observed recovery; avoid blind retry loops and duplicate expensive diagnostics.
- **Unavailable/ineligible:** record the reason (access, quota, missing runtime, incompatible platform or service failure). Continue with a trustworthy local runtime or another approved compute backend; use hosted/platform CI only within its authorization and budget. Do not wait indefinitely for the preferred backend when a valid fallback exists.

An exhausted Actions budget stays exhausted after a Codex failure. Existing Android/device, desktop, packaging-security and release requirements remain open until their own evidence is verified.

## Submission and command records

Before submitting, follow `references/external-operations.md` to persist/read back intent and submitting state outside the candidate branch. Include operation key and attempt ID in the request; a lost response means reconciliation, not another request. Use the reviewed plan/runner from `references/command-evidence.md` and return the complete evidence directory. Record setup failures as NOT_RUN for checks that never started, preserving the actual setup exit. An overall shell or task success flag is insufficient.

Native CLI subprocesses execute in the caller-selected journal directory so provider diagnostic files cannot contaminate an ambient candidate checkout. Keep that directory outside the frozen checkout. Explicit environment and source-branch arguments retain provider binding; changing command working directory creates no launch authority.

On 2026-10-05 an actual native Cloud checkout had the exact requested clean SHA but no configured Git remotes. The submitting host verifies the canonical repository/environment association and exact remote branch before launch. Absence of origin inside that provider checkout is not itself conflicting identity and must not stop portable tests. Inspect available identity without changing Git configuration; reject a conflicting configured remote. Report host-bound identity separately from independent observations. Preserve the failed initial task/report and charge when correcting this preflight contract; a retry needs a fresh reviewed correction and remaining admission budget.

### Isolated development transport

`scripts/codex_cloud_development.py` implements a separate development request
using `templates/codex-cloud-development-request.json`. It does not change the
COMPUTE_ONLY contract. A parent supplies a live authority callback which checks
its exact lease, guard, immutable source/branch bindings, reserved budget and
one-use submission claim immediately before official CLI dispatch.

The durable journal records dispatch uncertainty before invoking `cloud exec`.
Restarting never recreates authority or dispatches again. Recovery fully paginates
official inventory and requires unique exact operation/attempt/environment
association; a previously independently verified environment label is usable
when official metadata omits the ID. READY means waiting_result, not acceptance.

Official `cloud diff TASK --attempt 1` exports actual bytes with a SHA256 digest.
The export is untrusted evidence: its base_sha is the request binding, not an
independently observed worker HEAD. Parent report/base/scope/log validation and
the existing managed handoff/integrator remain mandatory before publication.
The transport never applies, commits, pushes, cancels or clears a guard.

### Development admission and handoff

`scripts/codex_development_bridge.py` accepts parent-observed released runtime
lease/pool snapshots and durable budget-ledger evidence. All seven named
controller capability checks must pass. A free ready writer slot, matching
base/branch/scope, fresh owned lease and accepted exact reservation are required.
Snapshot validation is not launch authority: the caller must refresh official
inventory before its short-lived claim and recheck the exact live guard, source,
claim and budget in the transport callback immediately before dispatch.
Unknown outcomes remain charged and permit observation only. Unsupported cancel
does not prove provider quiescence and never clears an external guard.

The bridge requires the exact observed report task/attempt/environment/base,
complete planned argv/exits/counts/log hashes and actual patch scope. Exported
bytes are resolved and hashed by the existing managed handoff validator; Git
parses their path manifest. The returned content_artifact handoff grants no
publication permissions. The parent imports it only into its assigned isolated
branch, then uses existing validate_publication_proof plus live lease/source
checks before publishing. Cloud unit success cannot satisfy platform gates.

Capability qualification is specific to the verified repository, environment
ID/label and supported stable CLI version. Mismatched or blocked receipts are
rejected even if their check booleans claim success. Diff evidence is installed
from a complete fsynced temporary inode; an interrupted export can restart
without a partial final artifact or any second provider submission.

Development transport interprets official stable 0.160 status exit codes with their typed status: READY exits 0; PENDING and ERROR exit 1. Other status/exit combinations remain unknown. PENDING is running, while ERROR records provider failure without redispatch.
