# Command evidence v1

Use the stdlib Python runner for already-authorized, synchronous build, test, lint, schema and deterministic checks. It does not authorize commands, sandbox them, launch compute/CI, deploy, or perform production/security operations. Run it in the selected compatible validation environment after making the candidate durable.

## Declare the check plan

Copy `templates/check-plan.json` to the repository's chosen plan path. Fill every available `argv` with the actual argument array. Empty arrays deliberately produce `NOT_RUN`; the template cannot produce GREEN until configured. Commit a repository-owned plan before checking the candidate, or supply an independently trusted external plan.

`command-check-plan/v1` accepts exactly `schema` and a nonempty ordered `checks` list. Each check requires:

| Field | Contract |
| --- | --- |
| `id` | Unique 1–64 character name; letters, digits, `_`, `-`; first character alphanumeric. |
| `kind` | `build`, `test`, `lint`, `schema`, or `check`. |
| `required` | Boolean; at least one check must be required. Declare every closure gate required. |
| `argv` | Array of argument strings, executed at the worktree root with `shell=False`; `[]` means unavailable. |
| `timeout_seconds` | Positive number, at most 86,400. |
| `expected_red` | Optional object with positive `exit_code` (1–255), literal log `signature`, and nonempty `reason`, declared before execution. |

Reject unknown fields, duplicate IDs/JSON keys, malformed types and plans with no required checks. Split build and test commands into separate entries; do not hide multiple gates inside a shell command that discards earlier exits. Commands remain executable code and require the surrounding repository/user authorization.

For tests, configure the framework's JUnit XML reporter to write `{junit_xml}`. The runner expands that literal within one argv item, without shell parsing. `{check_dir}` similarly expands to the fresh per-command output directory. The same paths are available as `EVIDENCE_JUNIT_XML` and `EVIDENCE_CHECK_DIR` environment variables. For an existing pytest project, the argv may be `['python3', '-m', 'pytest', '-p', 'no:cacheprovider', '--junitxml={junit_xml}']` (encode with JSON double quotes in the plan). Other frameworks need their own actual reporter command; no dependency installation is performed.

Require fresh JUnit `tests`, `failures`, and `errors` integer counters in every leaf suite; `skipped` defaults to zero. At least one non-skipped test must run. Validate supplied testcase counts/outcomes and aggregate counters, and count nested suites once. Missing/malformed XML, all skipped/zero tests, inconsistent counters, or failures/errors with a zero process exit fail the check. JUnit files may be at most 16 MiB; DTDs/entities, namespaces, and mixed direct testcases plus nested suites are unsupported and fail closed. A valid summary-only suite with counters is supported.

`EXPECTED_RED` requires the exact predeclared exit, the literal signature in the command log, and, for a test check, a valid report showing test failures/errors. A timeout, startup failure, absent report, wrong source, wrong exit, absent signature or unexpected zero exit cannot count as EXPECTED_RED. Remove the RED expectation in the separate GREEN plan; do not edit recorded evidence.

## Run and validate

Use Python 3.10+ and Git. Replace these paths and the full SHA with actual values:

```bash
python3 /path/to/skill/scripts/run_checks.py \
  --worktree /path/to/repository \
  --candidate-sha FULL_LOWERCASE_COMMIT_SHA \
  --plan /path/to/repository/docs/check-plan.json \
  --output-dir /path/outside/repository/new-evidence-run \
  --environment-id ACTUAL_LOCAL_OR_COMPUTE_ENVIRONMENT_ID \
  --environment-config-sha256 REVIEWED_CONFIGURATION_SHA256

python3 /path/to/skill/scripts/validate_evidence.py \
  --evidence /path/outside/repository/new-evidence-run/evidence.json \
  --plan /path/to/trusted/check-plan.json \
  --candidate-sha FULL_LOWERCASE_COMMIT_SHA \
  --environment-id EXPECTED_ENVIRONMENT_ID \
  --environment-config-sha256 REVIEWED_CONFIGURATION_SHA256
```

Both CLIs require the bare 64 lowercase hexadecimal SHA-256 of the reviewed environment contract: SDK/toolchain versions, dependency lock inputs, and setup/maintenance configuration. Derive it deterministically from actual reviewed inputs; never reuse a label or unrelated digest. Store it as `environment.configuration_sha256`. Bind operation recovery using `operation_intent.binding.environment_fingerprint = "sha256:" + environment.configuration_sha256`. This stable configuration binding is distinct from `environment.fingerprint`, which additionally hashes observed host/runtime details and environment identity. A validator expectation with a different configuration digest rejects the evidence even when the environment ID is unchanged.

The output directory must not exist, must have no symlink components, and must be outside the entire Git worktree. Configure command reports and build products outside source where possible. The runner itself writes evidence/logs only to this output directory, disables Python bytecode writes for child checks, and never cleans source or commits changes. A command that changes tracked or untracked source fails the clean-tree gate; later commands are withheld. Ignored build products remain subject to repository policy.

Before and after each command, record `HEAD` and Git porcelain status including untracked files and submodule changes. Require the exact full candidate SHA and clean source at every boundary, including run start/end. Run commands sequentially; keep a failed build failed even when a later independent check succeeds. Missing/unexecutable commands are `NOT_RUN`; timeout is `FAIL` with the actual terminated exit code. On POSIX, a timeout kills the command's process group; elsewhere it kills the direct process.

## Consume evidence

`command-evidence/v1` produces a `plan.json` snapshot, `evidence.json`, and one numbered directory per check containing `result.json`, `command.log`, and, for tests, `junit.xml`. Each result records rendered argv, candidate SHA, observed source before/after, environment identity/fingerprint, UTC start/end, duration, actual exit or null when not started, termination, diagnostics, log digest, report digest/counters, status and reason.

The summary distinguishes `runner_status` (`RUNNING`, `COMPLETE`, `ERROR`) from `gate_status` (`NOT_RUN`, `GREEN`, `EXPECTED_RED`, `FAIL`) and `final_green`. A completed runner is not a passing gate. Required `FAIL`/`NOT_RUN`, any candidate/source mismatch, or any EXPECTED_RED prevents final GREEN. Explicitly optional failed checks are retained but do not fail otherwise-passing required gates. Any EXPECTED_RED, even optional, keeps the run non-green.

| Exit | Runner | Validator |
| --- | --- | --- |
| `0` | Completed, final GREEN. | Valid evidence and final GREEN. |
| `1` | Completed, non-green gate, including EXPECTED_RED. | Valid evidence of a non-green gate. |
| `2` | Invalid input, setup or runner error. | Invalid, incomplete or contradictory evidence/input. |

Persist JSON with temporary files, file flush/fsync and atomic rename; finalize logs after command termination. Persist the incomplete summary before commands and after each result. A killed/interrupted runner leaves nonterminal evidence; never infer completion from partial files. Preserve the entire output directory together. It can be copied for validation; recorded argv retains its original absolute output paths.

Supply the validator with the expected SHA and trusted plan, not values copied unquestioningly from the evidence. It checks plan identity and every required command, per-command/summary consistency, ordering/timestamps, source observations, environment fingerprint, actual exits, file hashes and freshly parsed report counts. It recomputes check/gate outcomes rather than accepting a reported PASS. Pass `--environment-id` when the validation route constrains the environment.

These records detect missing, stale, mismatched and internally contradictory evidence; they are unsigned local records, not remote attestation. A malicious command can fabricate a report or rewrite evidence. The observed environment fingerprint covers OS/kernel/architecture, Python executable/version, Git version and the supplied configuration digest. The caller must derive and verify that digest from actual environment inputs; the runner does not independently measure every installed dependency or toolchain byte. Preserve remote task/log provenance and required platform evidence separately. Source checks observe boundaries and Git-visible dirtiness, not transient modifications later undone or ignored-file content. Do not run detached/background jobs through this synchronous runner.
