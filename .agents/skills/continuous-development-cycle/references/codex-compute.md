# Priority Codex Compute

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
