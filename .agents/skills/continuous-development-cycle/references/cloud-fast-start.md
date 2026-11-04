# Cloud fast start and durable recovery

## Cloud new-chat entry (2.13.0)

First read the actual project AGENTS, source HEAD, checkpoint, lease/guard and journal. Preserve known operations before setup or a new request. The connected native Cloud runtime is an execution route; official UI and authenticated official CLI are separate modes. CLI401 or unknown nested inventory does not invalidate qualified native work and does not authorize an auth retry, Codespace start or a second executor.

For the canonical source checkout, prepare the typed, hash-bound current observations with:

```sh
python -B src/continuous-development-cycle/scripts/codex_cloud_entrypoint.py prepare --profile docs/cdc-cloud-profile.json --inputs docs/cdc-cloud-entry-inputs.json --project-root .
```

In a consumer, use its actually verified vendor root in place of src/continuous-development-cycle. The installed personal loader uses its verified extracted package path. Inputs are project-local snapshots under cloud-entry-inputs/v1, never credentials or cached authority: context/probe/registry/routing_policy/routing_context references each bind exact UTF-8 JSON file bytes with SHA256. Expanded form uses --context, --probe, --registry, --policy (alias --routing-policy), --routing-context. The profile template is explicitly UNCONFIGURED until genuine per-mode namespace/ID, policy/setup and fresh native host evidence are supplied; null fingerprints/unknown CLI labels fail closed. A native display label alone is metadata. --now is test-fixture-only.

For recovery, the existing caller binds `input_digests["cloud-profile:" + access_mode]` to the current `codex_cloud_profile.profile_binding_digest(profile, access_mode)` and independently supplies the actual current toolchain fingerprint. Recovery policy must equal current profile policy. Requalifying changed setup or policy cannot reuse a prior profile binding. This is supplied evidence, never authentication or an action grant.

A non-null capsule external operation remains known until the original journal is reconciled. It cannot disappear behind a restored `NONE_VERIFIED`; conflicting capsule/journal keys produce reconciliation without replacing either saved document or sending again.

Official CLI remote preparation requires the optional context field `routing_request`: an existing `capability-request/v1` with exact context task ID/source SHA, nonempty project-approved required capabilities and explicit `required_backend_id`. Native/UI contexts may omit it. The caller supplies `compute-cost-context/v2` with the same backend, qualified CLI namespace/environment, `provider_kind=codex_cloud`, `consumption=compute_backend`, `action=create` and a compute backend reference. Existing cost routing must select that exact ready/configuration-bound backend. Missing/stale/incompatible registry, product failure, another backend/mode or unavailable policy branch blocks preparation. Never infer capabilities from argv or interpret an environment ID as a backend ID. Submit additionally compares the actual adapter executable with the qualified profile executable before delegation and retains the original fresh authority callback.

Serialized recovery uses the same recipe/selected-step/verification consistency contract as `recovery_recipes.action_plan`. A verified reuse cannot become another diagnostic through a contradictory saved handoff.

Preparation returns ONE typed next_action, not permission to run it. CONTINUE_NATIVE uses the existing registered managed caller for its exact approved argv; OBSERVE_EXISTING/RECONCILE_EXISTING/INTAKE_EXISTING use the original same-key transport, preserving unknown/submitting effects. READY_FOR_SUBMIT requires the existing fresh owner/intent/guard/budget/one-use callback; no UI-to-CLI or mode/namespace substitution. Qualify only the selected mode; never repeat broad provider inventory just to use this connected native host. Read references/cloud-fast-start.md.

Recovery v2 selection uses current source/environment/policy/input digests and durable append-only history. The existing authorized caller records genuine started/unknown/terminal observations through record_history with fresh callback/CAS/readback. A consumed fingerprint needs explicitly bound unused correction evidence; a reason string, new chat or unrelated proof is not a retry. Unknown/submitting state is observe/reconcile-only. Reused verified dependency/result evidence skips installation/investigation; a concrete record_blocker result is preserved. Recipes do not execute arbitrary shell or grant ownership.

Watchdog resumes use the same entry and actual current facts; inherited paused status remains paused. Do not enable/rebind/reschedule a watchdog or reopen product/security/platform gates to complete CDC metadata.

The wrapper digest is sha256-prefixed sorted UTF-8 JSON. Existing transport _canonical/_digest retain default ASCII escaping and plain 64-hex output. Never silently trim argv. `snapshot(operation_key)` is a locked read-only copy of the existing transport journal, not inventory or provider authority. Prepared/restored projections are detached; submit repeats fresh preflight and delegates to the original transport callback. History documents belong to their dedicated document refs, not a replacement of multi-file coordination trees.


### Exact handoff v1 continuation contract

A handoff preserves `operation_key` (nullable only for genuinely no admitted
remote operation), `task_mode`, `access_mode`, `restore_ref`/`restore_digest`
(both present or both null), and nullable `recovery_history_ref`, alongside the
existing source/profile/task/journal/guard/budget/recipe references. `task.mode`
must equal `task_mode`; next-action verification must contain the exact handoff
`operation_key` and `exact_sha`. Every object rejects unknown fields. Accepted
argv strings are never normalized. These references grant no authority.

| Handler | Exact parameters | Additional binding |
| --- | --- | --- |
| run_existing_native_check | check_id, argv | native_runtime, no remote operation |
| observe_existing_operation / intake_existing_result | operation_key, task_mode, journal_ref | Same known key, mode and journal |
| reconcile_existing_operation | operation_key, task_mode, journal_ref; optional terminal_evidence_ref | Same key/mode/journal, including unresolved nullable key/journal |
| submit_existing_transport | operation_key, task_mode | official_cli; exact routing_policy_digest, routing_context_digest and registry_digest verification |
| use_existing_official_ui_boundary | task_mode | official_ui only |
| record_blocker | empty object | No executable parameters |
| execute_existing_recovery_plan | decision | Strict selection/action-plan projection; existing allowlisted typed recipe parameters; exact recovery_history_ref; reconciliation key/task/mode/journal consistency |

Recovery decision validation only checks the serialized contract. It cannot
revalidate observations or execute a stale recipe: the caller must freshly select
against actual history and invoke the original owner/action/claim callbacks.
