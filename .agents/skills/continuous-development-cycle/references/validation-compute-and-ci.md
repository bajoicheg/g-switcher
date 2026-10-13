# Validation, compute, and CI

## Priority and fallback order

Use Codex Compute first for eligible candidate validation when it is authorized, configured, available and compatible with the required property:

`Codex COMPUTE_ONLY → correct local runtime → other approved compute → hosted/platform CI`

Local availability alone is not a reason to replace Codex for full candidate validation. Cheap syntax/preflight checks and short local RED/debugging loops are allowed. If the adapter explicitly overrides the order, follow the applicable user/repository policy and record the chosen route.

Before launching, reuse or establish the environment following `codex-compute.md`. Distinguish unconfigured, unavailable, ineligible, setup-failed, running and terminal states. Record a concrete fallback reason; never treat a preferred backend failure as a blocker while another valid authorized path exists. Required platform and final CI gates still apply; correctness outranks cost.

An empty/unavailable command means "not available", never PASS.

## Evidence contract

Use the versioned plan, runner and validator in `references/command-evidence.md`. Record each command as PASS, EXPECTED_RED, FAIL or NOT_RUN with its own exit, source observations, environment and actual test report. Compare evidence with the independently expected plan/SHA/environment. A zero wrapper exit cannot override failed or unexecuted checks; EXPECTED_RED never satisfies final GREEN.


Evidence must identify:

- candidate SHA, observed HEAD before/after and clean worktree before/after for compute;
- environment ID plus request/task ID and URL for Codex;
- command or workflow actually executed;
- environment/platform when relevant;
- terminal result and exit/conclusion;
- concise failure diagnostics when RED;
- clean-state requirements for compute when configured.

Reject stale, dirty, mismatched, non-terminal, or implausible evidence. A submitted comment, created environment, task counter or setup spinner is not a passing build. Verify artifact bytes/digest and SHA binding before delivery; a reported APK/package hash alone is not a downloaded artifact.

## Actions budget

The repository adapter should define one of:

### normal
Use ordinary CI policy.

### conserve
Prefer Codex for eligible candidate checks during RED, intermediate, and corrective iterations; use quick local loops or justified fallback as above. A full hosted run is reserved for a compute/local-GREEN candidate according to repository policy. After a failed expensive final run, diagnose and re-establish candidate GREEN through the valid priority path before launching another full run.

### exhausted
Do not launch, rerun, retry, dispatch, or intentionally provoke hosted Actions. Observing an already-running workflow is allowed. Do not probe for restored capacity by starting a workflow. Keep a mandatory platform-final task open if no approved alternative exists.

Use `references/budget-ledger.md` for durable reservations and per-task/per-wake accounting. Reserve before starts and polls; a failed response does not refund a possible start. Local caps are distinct from provider quota. Unknown or stale quota observations cannot restore known exhausted capacity. Preserve checkpoint resources and require a concrete correction/recovery for a repeated failure. A budget decision never replaces ownership, external guard, authorization or final evidence checks.

## Platform integrity

Do not substitute Linux or platform-neutral compute for a required Windows/macOS/UI/packaging/platform-security gate. Compute can reduce iterations without replacing configured final evidence.

## CI failure

On RED:

1. inspect exact failing job, step, and log;
2. identify root cause before changing production code;
3. use systematic debugging;
4. apply the smallest corrective slice;
5. verify the correction through the valid priority path;
6. return to final CI only when the candidate is ready.

Infrastructure failures that occur before repository steps execute are recorded distinctly from code failures. Do not repeatedly burn budget retrying the same infrastructure condition.
