# Native retained-project adoption observation

`scripts/project_adoption.py` joins existing Source, lease, budget, and owner
authorization channels without remote writes. It preserves runnable product work,
original budget history, unresolved charged agents, and the original final
validation platform. Linux fixed checks never establish Windows acceptance.

The host must authenticate registration before constructing the factory inputs.
Readable JSON, a serialized registration, repository ownership, or a ledger policy
alone does not establish owner authority. This API does not raise historical caps,
substitute a task, reset charges, or resolve UNKNOWN operations.

## Trusted registration and original authority

Registration has exactly these fields:

```python
registration = {
    'schema': 'project-adoption-registration/v1',
    'project_id': 'product', 'repository': 'example/product',
    'source_ref': 'refs/heads/work/product', 'source_sha': source_sha,
    'source_store_id': source_endpoint,
    'lease_ref': 'refs/heads/cdc/coordination', 'lease_store_id': lease_endpoint,
    'budget_binding_digest': binding_digest,
    'authority_store_id': root_endpoint,
    'authority_ref': 'refs/heads/cdc/owner-control',
    'authority_revision': authorization_revision,
    'authority_path': 'project_adoption_authorizations/product',
    'authority_digest': authorization_digest,
    'final_platform': 'windows', 'check_ids': ['diff-check'],
}
```

Digests use SHA256 of UTF8 JSON with sorted keys, compact separators, and finite
numbers, prefixed `sha256:`. Endpoint identities use `git_remote_identity`.
The immutable native Root document contains this exact authorization object at
the registered two-component path:

```python
authorization = {
    'schema': 'project-adoption-authorization/v1',
    'project_id': 'product', 'repository': 'example/product',
    'source_ref': registration['source_ref'], 'source_sha': source_sha,
    'source_policy_revision': source_policy_revision,
    'source_policy_digest': source_policy_digest,
    'lease_ref': registration['lease_ref'], 'lease_store_id': lease_endpoint,
    'budget_binding_digest': binding_digest,
    'task_id': original_task_id, 'budget_policy_digest': original_policy_digest,
    'anchor_revision': original_budget_anchor,
    'anchor_ledger_digest': original_anchor_ledger_digest,
    'preserved_counts': {'compute_starts': original_compute_count,
                         'ci_starts': original_ci_count,
                         'agent_starts': original_agent_count,
                         'active_agents': original_unknown_agent_count},
    'owner_decision_ref': authenticated_original_policy_decision,
    'owner_wake_id': fresh_owner_wake_id, 'owner_wake_ref': fresh_owner_wake_reference,
    'scope': {'role': 'read_only', 'mode': 'COMPUTE_ONLY',
              'execution_platform': 'linux', 'ci_starts': 0, 'agent_starts': 0,
              'product_writes': False, 'check_ids': ['diff-check']},
    'remaining_work': ['Original Windows acceptance remains pending'],
}
```

Root must independently authenticate the original policy decision before writing
this authorization. It attests that the existing task policy remains authorized
for the narrow prospective scope; a template or this API cannot supply missing
historical authority. Counts describe the original budget anchor and include
UNKNOWN agent liability. Later events remain charged under that same ledger.
The owner wake reference must also match the trusted original budget binding's
`wake_authorizations`; it must describe genuinely new owner-authorized activity.
No fallback wake or replacement task is permitted when a quota is denied.

The original budget may occupy a separately registered coordination ref or
endpoint, including a `document.json` top-level `budget` field. The complete
binding digest pins that original endpoint, ref, path, field, task, anchor and
wake authorizations in both registration and immutable Root authorization. It
must retain the registered project repository and Source ref; matching a ledger
or changing the lease ref cannot authorize a substituted budget channel.

The factory authenticates the authorization revision as an ancestor of the
actual native `GitDocumentStore` channel. Every subsequent revision must retain
the exact authorization object. Unrelated Root document updates are supported;
changed-and-restored authorizations are rejected. Use a new authenticated
authorization revision and registration when original pins legitimately change.

## Executable host integration

The following uses existing authenticated host configuration; it creates no
authorization or project state:

```python
from live_target import GitSource
from git_lease_store import GitLeaseStore
from git_document_store import GitDocumentStore
from project_budget_store import GitProjectBudgetStore
from project_adoption import observe_project_adoption

source = GitSource(project_cache, source_remote, registration['source_store_id'])
leases = GitLeaseStore(project_cache, lease_remote, registration['lease_ref'])
original_budget = GitProjectBudgetStore(
    project_cache, budget_remote, authenticated_original_budget_binding,
    protected_refs=[registration['source_ref']],
)
owner_authority = GitDocumentStore(
    root_cache, root_remote, registration['authority_ref'],
    registration['authority_store_id'], protected_refs=protected_root_source_refs,
)
observation = observe_project_adoption(
    source, leases, original_budget, owner_authority, registration,
)
facts = observation.revalidate_for(
    source, leases, original_budget, owner_authority, registration,
)
assert facts['authorizes_launch'] is False
assert facts['authorizes_product_acceptance'] is False
assert facts['scope']['agent_starts'] == facts['scope']['ci_starts'] == 0
assert observation.budget_store is original_budget
```

`payload` returns a detached informational copy. `budget_store` exposes the
original native store and `budget_revision` its observed revision. Constructor
calls without the factory's process-local seal, raw dictionaries, reconstructed
payloads, changed payloads, substituted channel objects or registrations, and
observations older than 90 seconds fail closed. The clock argument is for trusted
host/testing use; callers cannot provide a different clock at revalidation.

Source adapter and checkpoint are read at the registered live SHA and validated
with native CDC 3.6 contracts. Repository, Source branch, policy, lease endpoint,
lease ref, checkpoint original budget ref, and final platform must agree. The
complete, nonshallow first-parent ancestry must contain the exact Source-selected
checkpoint lease revision. CDC 3.6.2 derives its native observation interval from
that immutable revision and the uniquely matching genuine owner/generation/
invocation closure. For a released snapshot, walk back through the exact retained
release identity to the actual ready predecessor and release edge; an unchanged
released snapshot is not the edge. For an owned snapshot, validate the original
record through its later exact release. A selected generation-zero snapshot must
be the canonical native initializer.

Every interval record is native-valid. Missing or malformed entries, merges,
generation rewind, schema downgrade, changed bindings or owner/invocation identity,
rewritten claims/resolutions/retirements and nontransactional releases fail closed,
even if later restored. A new owned generation must advance exactly once and use
a fresh owner UUID. A genuine v2 release uses the unchanged native transactional
release validator. Native conversation or automation metadata registration may
change within the same owner/invocation/surface/start-time identity. Earlier
blobs remain immutable ancestry and supply no present native proof, readiness,
closure or terminal authority. They are not repaired, reanchored or interpreted
as current lease permission. Legacy and incompatible records outside the selected
interval therefore cannot prevent this read-only observation or supply its closure.

No arbitrary baseline argument or registration fallback exists. The registered
Source SHA and immutable owner authorization already pin the checkpoint that
selects the original identity and revision. Informational `lease_baseline_revision`
and `lease_release_revision` identify the authenticated interval and actual
release. They remain serialized observations, not capabilities. Every released snapshot and same-owner interval edge uses the native transition
contract, including unchanged invocation metadata. Ownership changes preserve the
exact prior guard, terminal observation, consumed claims, resolutions, retirements,
migration and last release. A claim-null owned guard clears only through its exact
persisted native terminal reconciliation. Current clean state cannot replace a
missing historical reconciliation. Canonical historical retirement appends are
compared to the native pure projection with the exact original revision; they
retain UNKNOWN and never reconstruct an extinct or current capability. Actual managed
ownership/start, CAS, reporting and terminal gates are unchanged.
A released checkpoint may retain runnable next actions and may name an older
authentic released generation while the current generation is released. An
active checkpoint projection is supported only when its original lease revision,
executor, generation and invocation match a genuine release of that original
generation. A later authentic read-only generation may have completed; the
current lease must still be released, unguarded and at least as recent as the
original generation. The original checkpoint's active fields, budget charges
and remaining product work stay unchanged. Its active compute identifier must
be the native managed-host form or the native empty/`none` sentinel. Current ownership, guard, unresolved Source
operation pointers, wait, CI run, or unknown compute state blocks adoption.
The factory preserves the checkpoint verbatim; it writes no synthetic closure.

Before admission the host must append the actual event through
`original_budget.append_event(observation.budget_revision, event)`, honoring
native quota denial and uncertain-write observation rules. That changes the
budget revision and invalidates the old observation. Obtain and revalidate a
fresh observation, then separately use native lease/pool ownership and managed
start contracts. This object is not `VerifiedTerminalProof`, a lock waiver, a
provider permission, a product writer permission, or a launch capability.

## Validation

The isolated bare-Git tests exercise authentic typed channels, released runnable
work, prelease Source ancestry, older opaque ancestry, Source-selected native closure, independently registered
budget channels, native invocation metadata registration, exact stale active
projections across later releases, older historical releases, source/ref/task/
policy substitutions, guarded/live leases, fabricated release edges, immutable
authority history, endpoint drift, budget drift, expiry, and payload seals:

```sh
python3 -B -m unittest discover -s src/continuous-development-cycle/tests \
  -p test_project_adoption.py -v
```
