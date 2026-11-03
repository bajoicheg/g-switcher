# Retained project budget custody

`scripts/project_budget_store.py` provides `GitProjectBudgetStore` for an
**existing** registered task ledger. It neither initializes a ledger nor moves it
to another ref. The original task identity, policy, wake history, events, unknown
usage, active agents and failure circuits remain authoritative.

The host authenticates owner/task authority, the original policy override chain,
canonical source/lease/checkpoint history and pending operations before using the
store. A valid ledger, serialized registration, digest, receipt or budget decision
does not authenticate those facts. In particular, later adapter templates and
prospective Linux caps cannot establish a historical policy override. Missing
policy authority is a reconciliation blocker, not permission to reset the ledger.

## Trusted registration

Construct the store from root-owned host registration, never from caller task
fields or a claimed approval in JSON. Registration pins these exact fields:

```python
binding = {
    "schema": "project-budget-binding/v1",
    "repository": "example/project",
    "source_ref": "refs/heads/work/task",
    "coordination_ref": "refs/heads/cdc/coordination",
    "coordination_store_id": pinned_endpoint_identity,
    "ledger_path": "budget-ledger.json",
    "budget_field": None,
    "task_id": original_task_id,
    "anchor_revision": authenticated_original_revision,
    "anchor_ledger_digest": authenticated_original_ledger_digest,
    "wake_authorizations": {
        "owner-connection-wake": authenticated_owner_decision_reference,
    },
}
```

The anchor and ledger digest come from the authentic original coordination
history. The host verifies all policy authority through that anchor. The native
store verifies the configured endpoint, the anchor in current authoritative Git
ancestry, its actual original ledger bytes/digest and every post-anchor ledger
transition. A rewrite later restored to matching bytes still fails. Merged,
rewound, substituted or truncated post-anchor history fails closed. An established
instance also rejects a rewind behind its last observed revision.

Supported original storage locations are `budget.json`, `budget-ledger.json`,
or the top-level `budget` field of `document.json`. No nested paths or arbitrary
field updates are accepted. Fields must be unique, including Unicode-normalized
case-folded ambiguity; duplicate keys anywhere in the document and nonfinite JSON
values are rejected. The ref is portable-isolated from the registered source and
all supplied protected refs. The repository/source names are trusted host pins;
the store does not infer repository ownership from endpoint syntax.

## API

```python
from project_budget_store import GitProjectBudgetStore

store = GitProjectBudgetStore(
    repo_cache, "coordination", binding,
    protected_refs=[binding["source_ref"]],
)
revision, original = store.read()
historical = store.read_revision(revision)

# The event belongs to original["task_id"] and its current wake.
# Use the exact original operation key, attempt and kind; do not mint an alias.
receipt = store.append_event(revision, reservation_event)
assert receipt["authorizes_launch"] is False

# A lost reply is not a reason to repeat submission. This method only observes.
observation = store.observe_event(reservation_event)
assert observation["authorizes_launch"] is False
```

`read()` returns `(authoritative_revision, detached_ledger)` after a fresh stable
remote read. `read_revision(revision)` authenticates the requested revision is in
the same authoritative history at or after the registered anchor. Both validate
the native budget schema and original task/policy/event/wake prefixes.

`append_event(expected_revision, event)` derives the only proposed ledger through
native `budget.apply_event`; reservations also pass native `budget.decide` through
that function. Raw replacement ledgers are not an API. Conflicting event IDs,
operation/attempt/kind aliases, wrong task/wake, numerical denial and failure
circuits fail before push. An exact already recorded event is idempotent and never
grants another launch. Stale revisions are rejected even when the caller intends
to reuse an old operation. `observe_event(event)` distinguishes an exact durable
event from absence or conflicting payload without submitting anything.

The return mapping contains `revision`, detached `ledger`, `already_recorded`,
`authorizes_launch: false` and `authorizes_product_write: false`. It is accounting
readback, not a serializable capability. Authenticating outcome/provider/remedy
evidence remains the host's duty; structural event validation does not supply a
provider result or justify terminalizing an old unknown agent reservation.

For a genuinely new owner-authorized activity on the **same** project task:

```python
revision, original = store.read()
receipt = store.begin_wake(revision, "owner-connection-wake")
# Optionally require the exact already registered owner reference as argument 3.
```

Only a wake present in trusted `wake_authorizations` may be appended. This calls
native `budget.begin_wake` and uses the same conditional write/readback contract.
No old wake is reopened, no event is changed, and task-wide charges, unknown
liabilities, active agents and failure circuits remain. A denied task cap cannot
be recovered by trying another wake ID. Registration of a wake requires the host
to authenticate a real fresh owner activity; a text reference alone is not that
authority. No new-task substitution or automatic wake fallback is supported.

## Conditional update and recovery

The proposal has exactly the observed parent and an unpredictable nonce. An
ordinary non-force Git push accepts at most one competing sibling. The selected
budget blob alone changes: every other Git tree entry keeps its exact name bytes,
mode and object ID, including `lease.json`. When a document field is selected,
the JSON decoder locates the actual top-level value lexically and replaces only
that value's span. Every byte outside the budget value, including escaped strings,
number spellings, spacing and trailing newline, remains identical.

The store revalidates the pinned fetch/push endpoint immediately before the effect
and independently reads back the resulting exact revision and ledger. A failed or
lost push reply produces no success receipt and is never internally retried.
Observe the original event against the original authoritative ref. If another
coordination writer moves the ref after a successful push, the original receipt
may remain uncertain; matching event readback provides accounting reconciliation,
not a reconstructed launch permit.

Budget persistence, Root task CAS, native pool launch CAS and managed lease
acquisition remain separate gates. Partial interruption leaves conservative
charges and stops launch. Before every real effect, the host rechecks source,
lease, guard, policy, original budget readback and one-use native start authority.
It must not release a slot merely because accounting has been updated.

This primitive grants no product/provider start, source publication, Windows or
real AD acceptance, scheduler authority, policy increase, takeover or UNKNOWN
replay. Linux results remain sidecar evidence. Prospective `ci_starts: 0` and
model/agent-start zero caps can narrow the existing ledger without relaxing it.
Old exhausted CI and uncertain agent liabilities remain recorded and enforced.

The focused real bare-Git fixtures in `tests/test_project_budget_store.py` cover
neighbor and lexical preservation, concurrent sibling CAS, stale/lost replies,
history rewrites, task/policy substitution, malformed documents, quota denial,
operation aliases and retained liabilities across a legitimate wake. Complete
release qualification and ordered independent reviews precede live adoption.


## Bounded history payload retention

Each read still authenticates the current endpoint, full original anchored parent chain and fresh final ref. Cold validation streams all intermediate immutable ledgers with their original policy/event/wake checks, keeping only needed preceding/current payloads. The existing detached process-local cache retains the verified tip and chain, not every historical ledger. An earlier selected historical revision is loaded from its actual immutable object only after matching that freshly authenticated canonical prefix. The original4MiB document bound is checked before reading a blob body; Git fetch/pack resources and parsed-object overhead are separate. No new launch, lease, provider or owner authority is supplied by cached data.
