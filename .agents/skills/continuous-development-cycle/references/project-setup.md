# Project initialization and migration previews

Run `python -B scripts/cdc.py init REQUEST.json` or `migrate REQUEST.json`.
Both are read-only planners. Review exact file contents and SHA-256 previews,
then use the existing managed writer with fresh source/ownership/guard evidence,
expected HEAD, invocation-bound intent and durable budget admission. Neither
planner executes validation commands or grants write, release or launch authority.

## Initialization request

```json
{
  "schema": "cdc-init-request/v1",
  "repository": "owner/project",
  "branch": "main",
  "source_head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "preset": "portable",
  "validation": {"quick": "", "full": "python -B full.py", "release": "python -B release.py"},
  "cloud_profile_json": null
}
```

Replace the example identity, SHA and validation commands with real project
values. Full/release command strings are mandatory data and are never executed
by the planner. Presets: portable MEDIUM/any, windows MEDIUM/windows,
android MEDIUM/android, critical FULL/any. A preset is a requirement, not platform
evidence. Generated fixed paths are docs/development-cycle.yaml,
docs/work-status/current.md, docs/cdc-cloud-profile.json and
docs/cdc-cloud-entry-inputs.template.json. The checkpoint begins in recovery with
released ownership and no validation or release success. The Cloud template is
explicitly UNCONFIGURED and cannot run prepare; materialize the genuine five
hash-bound snapshots through references/cloud-fast-start.md first.

## Migration request

Use schema cdc-migrate-request/v1 with exactly these remaining fields:
current_adapter_yaml (the exact YAML text), current_checkpoint_markdown (complete
frontmatter and body), cloud_profile_json (exact reusable JSON text or null),
preset, expected_source_head and probe. The probe has exactly source_head,
observed_at_utc (UTC Z), lease_released (boolean) and guard_reconciled (boolean).
Use a current source observation; CLI accepts at most 90 seconds of age and
5 seconds of future clock tolerance. Embedded tests may inject now_utc.

Original policy/checkpoint bindings validate before planning. This fixed-path
slice rejects custom checkpoint paths rather than redirecting the policy. Even
unbound recovery validates a supplied Cloud profile and project/ref identity.
Any saved external marker, including a keyless partial record, blocks artifacts. An explicit
supported diagnostic version reads an archived policy; default checkpoint
validation still rejects an incompatible installed runtime. Only a known
exclusive ceiling 3.0.0 may be proposed as 4.0.0 for the 3.x target. Report
original compatibility independently of detached proposal validity. Decimal
revision advances once for semantic change. A nondecimal revision needing
change requires a reviewed revision choice. Higher quality and an existing
Windows/Android gate cannot be relaxed. Budgets, pauses, control fields,
external identity, historical evidence and Markdown body survive.

Result schema is cdc-project-plan/v1. INIT/APPLY contain reviewable files;
NOOP preserves exact input bytes and has no changed_paths. RECONCILE means
stale/drifted/incomplete evidence; WAIT means ownership/guard/existing external
work; CONFLICT means incompatible platform selection. These last three return
no file artifacts. All five authorizes_* fields are false for every result.

A reused Cloud profile must match project/ref and remains byte-exact. Matching
policy yields REUSE_PENDING_FRESH_PROBE; changed policy yields REQUALIFY. Neither
status is READY or authorizes an environment start. No Fleet adoption or
scheduler action is implied by initialization, migration or archived qualification.
