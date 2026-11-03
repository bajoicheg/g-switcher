# Native administrative UNKNOWN recovery

These two protocols provide administrative custody. They never convert the
original effect to success, failure, cancellation, a wait return, or conditional
Git confirmation. They do not refund budgets or satisfy successful dependencies.
CDC 3.5.4 histories remain readable. The release binding changes only during the
reviewed release workflow; an implementation checkout is not release evidence.

## Prelaunch intake

`unknown_recovery` accepts the original `cdc-vps-control/v1` document through an
actual `GitDocumentStore`. Its public APIs are:

- `authenticate_prelaunch_intake(store, task_id, *, source_store, trusted_contract, at)`
  issues a `PrelaunchIntakeDispositionProof` after authenticating complete native
  ancestry, the original managed-host start request, intent, charged budget,
  guardian nonce and identity, canonical source lease, protected native channels,
  absence of native runtime artifacts, and current creator/guardian PID absence.
- `retire_prelaunch_intake_cas(store, expected_revision, task_id, proof, *, at)`
  makes one CAS on that same row and returns `revision`, `row`, and a newly issued
  retired `proof`. It preserves task, operation, budget, and the archived original
  row. `state` becomes `retired_unknown`; `result.administrative_disposition`
  records `original_effect=UNKNOWN`, `actual_wait=null`, and permanent no replay.
- `observe_prelaunch_intake_disposition(store, task_id, *, contract_digest, source_store)`
  observes an already committed tombstone and reissues its distinct administrative
  capability. After a lost reply, observe this entry; never repeat the CAS or start.
- `validate_prelaunch_disposition(store, task_id, row=None)` authenticates historical
  custody for host reads. It tolerates later genuine source generations. The
  row-only form is structural validation and grants no slot or terminal authority.
- `assert_new_intake_allowed(store, task)` and
  `assert_intake_start_allowed(store, task_id, start_request_digest)` check admission.
  The native document CAS also enforces replay exclusion atomically.
- `consume_intake_start(store, expected_revision, task_id, *, start_request_digest,
  controller_identity)` consumes a one-use start CAS before `bridge.start`.
  A tombstone and start consumption race on the original row; exactly one wins.
- `migrate_intake_registry_cas(store, expected_revision, old_digest, new_digest)`
  changes only the configured registry digest once every row is inactive. Supply
  independently reviewed old/new root configuration digests. It preserves every
  original task, charge, queue entry, and tombstone.

All guardian/controller entrypoints must enforce the native barrier. Stop old
creators and guardians before issuing a prelaunch proof; a check followed by
`Popen` supplies no start authority. Any canonical controller history, including the legacy
`controllers` field, a controller identity, native handle, checkpoint, finish
result, start consumption, or actual native pool blocks prelaunch retirement.
Prepared-to-submitting intent history and the exact pinned observational metadata
remain readable; they cannot conceal consumed authority.

`trusted_contract` is deployment configuration, obtained independently from the
original protected channel. Required pins are `original_revision`, `row_digest`,
`source_revision`, `source_digest`, `creator`, `guardian`, `guardian_nonce`,
`pool_ref`, `launch_roots`, and `custody`. Process identities contain `pid`,
`birth`, and `boot_id`. `custody` contains deployment-owned `controller_root`,
`worker_launch_root`, `controller_uid`, and `worker_gid`. The SDK derives the
controller scope as `controller_root/task_id` and the worker scope as
`worker_launch_root/executor/task_id`, using the original canonical row.
`launch_roots` must contain exactly those two scopes plus the original request's
journal and handle roots. Their exact paths, ownership and write permissions are
checked; every entry in the controller/worker scopes is inspected recursively.
The controller group comes from the independently pinned original guardian lock;
the worker scope uses configured `worker_gid`.

`artifact_pins` names only pre-effect static custody and always uses
`{sha256, uid, gid, mode}`. Original `guardian.lock`, `record.json`, and
`registered-record.json` are required and individually pinned. The guardian lock
must be empty. Registered launch data must match the exact original task,
executor and native task digest; preparation data must match task ID and original
source SHA/ref. A prepared checkout, if present, must be clean, detached at the
original source SHA with no remotes; every existing file is pinned. Committed
source blobs are compared directly, independently of index cache or
`assume-unchanged` flags. Only committed files and recognized Git preparation
metadata paths are static; extra files or directories cannot be pinned away. Git
inspection disables optional writes, fsmonitor commands and hooks. These checks
never authorize original task replay.

Native session, gate, lock and task/attempt journal paths must be absent even if
listed in pins. Their directories, including empty directories, and symlinks also
block disposition. The worker output directory must be empty and cannot be
whitelisted. Unknown controller/worker entries, special files, mutable static
custody or altered pin ownership block disposition. Live, reused, zombie,
unprobeable, or wrong-boot process identities fail closed. Native start-request
and runtime-journal hashes use the issuing runtime's original ASCII JSON encoding;
bridge handle UUID and operation/capability encodings retain their own original
canonical encodings. Stored legacy digests are never rewritten.

CDC 3.6.3 also supports independently configured Root intake and project lease/
pool endpoints. Add `channels={intake_store_id, intake_ref, lease_store_id,
lease_ref, pool_store_id, pool_ref}` to the trusted contract. The SDK joins the
Root pins to the actual intake store and the project pins to the original
request's repository directory, coordination remote, lease ref and plan endpoint/
pool ref. Supply the actual original typed `GitLeaseStore`; matching repository
labels or a supplied empty store are insufficient. Native pool and publication
absence probes run on that original project channel. Omitted independent pins,
foreign endpoints/refs and drift fail closed. Legacy single-endpoint contracts
remain supported. Historical observation derives the archived original project
channel; it never substitutes the Root endpoint or grants a new start.

A controller can fail before canonical consumption without creating a native
worker. Its genuine protected wait artifacts are a separate documentary class,
never static pins or a terminal proof. This branch requires `channels` and
`preconsume_exit={schema: native-preconsume-controller-exit/v1, controller,
receipt_sha256, stdout_sha256, stderr_sha256, guardian_stdout_sha256,
guardian_stderr_sha256}`. Hashes include the `sha256:` prefix; `controller` is
its independently observed original `{pid,birth,boot_id}`. Pin the original
receipt and streams from protected custody, not reconstructed or copied claims.
Only original nonce-derived `.receipt.json`, `.stdout`, `.stderr`,
`.guardian.stdout` and `.guardian.stderr` names are admitted. The receipt must
join the canonical task, exact guardian nonce/birth, exact child birth, actual
exit 2, UTC observation and exact stream paths/digests. Controller stdout and
both guardian streams must be empty; controller stderr must be exactly the
fixed preconsume rejection marker. Files must be regular, singly linked,
protected by the configured controller UID/group, mode 0600 or 0640, and match
all independent digest pins. Extra/missing files, altered status/schema/birth,
mutable custody, wrong raw bytes or live/reused/zombie/unprobeable processes fail.
All creators, guardians and that controller must be physically absent when the
proof is issued and revalidated. A live current/replacement creator blocks it.

This branch still rejects ANY canonical controller/controllers, consumption,
handle, result, checkpoint or finish history, even if later erased. All native
session/gate/lock/journal/pool/publication effects must remain absent; worker
output stays empty. Original source lease revision/content and all task/budget
fields remain unchanged. The actual controller wait is archived documentary
evidence only: `original_effect=UNKNOWN` and native `actual_wait=null` remain.
Retirement uses the same sealed capability and original-row CAS, racing native
start consumption. Lost replies are observed without another CAS or original
contract replay. No project-budget outcome, refund or terminal authority is
created by this administrative transition.

The replay key retains all task fields except `id` and `dependencies`, so changing
IDs, attempts, dispatch routing, or dependency names cannot replay the same
retired task contract. A genuinely distinct source candidate remains eligible.
`PrelaunchIntakeDispositionProof` is distinct from `VerifiedTerminalProof`.
Serialization discards its capability; hosts must never call normal terminal
completion with it or reinterpret UNKNOWN budget liabilities as terminal usage.

## Source publication quarantine

`source_publication_quarantine` supports a released native v2 source guard with
or without an original submission claim. Its public APIs are:

- `authenticate_source_publication_quarantine(store, *, terminal_proof,
  publication_store, source_remote, trusted_contract, at)` issues a sealed
  `SourcePublicationQuarantine` capability from actual native stores and an actual
  original `VerifiedTerminalProof`. Revalidation authenticates the original handle,
  issued controller/runtime descriptor, request, consumed pool attempt, genuine
  release, accepted integrated result, and complete relevant native ancestry.
- `quarantine_source_publication_cas(store, expected_revision, capability,
  evidence_reference, at)` archives the exact guard in one append-only
  `source-publication-quarantine/v1` entry in `submission_retirements`. All other
  lease fields, journal entries, generations, claims, terminal facts and charges
  stay unchanged. Raw CAS, serialized terminal proofs, and booleans cannot append it.
- `observe_source_publication_quarantine(store, *, operation_key, evidence_reference)`
  observes the authoritative entry after a lost reply and reports UNKNOWN with
  `conditional_update=false` and no submission authority.

The independently configured source pins contain `lease_revision`, `lease_digest`,
`original_lease_revision`, `handle_root`, `handle_id`, `request_ref`,
`publication_revision`, `publication_digest`, `operation_id`, `source_remote_id`,
`control_store_id`, `owner_decision`, and `publication_processes`. The owner
decision contains action `quarantine_source_unknown_without_replay`, the exact
`guard_digest`, and an immutable evidence `reference`. Publication processes are
all original sender birth identities from protected original observations; do not
invent a missing birth or infer complete closure from a wrapper's exit.

The guard must describe the original native `local_command` writer. Its exact
environment and contract stay bound through the original trusted lease digest.
The publication must join the actual integrated writer result and original handle.
An interrupted legacy controller may leave the informational session result
empty. Quarantine can accept that missing cache only after fresh native terminal
proof authenticates the original release and accepted/integrated pool, and the
original runtime `result.json` digest matches its canonical accepted result.
The candidate must match that actual writer result. Any contradictory populated
session result, unaccepted result, substituted pool or altered runtime result
fails closed. The factory does not repair session bytes. If the session release
receipt is missing, first use supported `managed_host_bridge.observe` on the
original handle to reconcile the existing authentic release, then obtain fresh
native terminal proof; observation grants no replay or Git confirmation.
The original publication entry must remain exactly SUBMITTED, with original
expected and intended commits. Fresh target HEAD must be a descendant of the old
expected HEAD, advance beyond it, and contain the intended candidate. This readback
never proves the old CAS. Observation time comes from the actual completed
physical/readback observations. Supply a fresh CAS `at` after issuing the capability;
do not reuse the timestamp from before network/history reads.
The native publication journal stays unchanged.
Native lease intent admission permanently rejects the original operation/candidate.
Every sending `GitLaneIntegrationPublisher` requires
`native_handle={handle_root, handle_id}`. It loads the original session, authenticates
its issued runtime request and original canonical pool claim/ownership, and derives
the canonical source lease and publication journal. Supplied `quarantine_store`,
if present, must match that derived lease endpoint/ref. Missing original lease,
substituted empty custody, alternate source refs, journals, task IDs or operation
keys fail closed before preparation or transport. Session data cannot substitute
for the original issued descriptor and canonical ownership history.

The source remote/ref, lane/result, expected HEAD and operation digest must match
the original native session; the result must be the actual clean writer result.
Transport additionally requires actual current caller birth/boot, exact active
original lease and running pool authority, a successful original worker held for
release, and a fresh replay
check immediately before the one-use submission CAS. Publication must also pass
native `execution_lease_v2.check_record(action='product_write')`
with the actual native clock immediately before each SUBMITTED journal CAS and
again immediately before transport. Exact owner, generation and invocation,
active finalization, lease TTL, fresh observable heartbeat and absence of an
external guard are required. The publisher's journal clock cannot waive these
gates. A post-consumption denial leaves the original SUBMITTED marker unresolved;
it sends nothing, fabricates no confirmation and cannot replay. Existing guarded
SUBMITTED history remains observable through the original native custody.
The original controller
can send in its own exact birth. Supported same-handle native recovery may finish
a never-submitted publication after the original PID is physically absent, using
the existing genuine owned invocation and held supervisor. A live other caller,
reused original PID or original zombie blocks recovery. Recovery never rewrites
the issued original descriptor or manufactures a replacement terminal proof;
SUBMITTED and UNKNOWN attempts still cannot send again. Managed-host publication
supplies this binding automatically. Legacy read methods remain usable without
handles; matching HEAD without native custody is readback only and never upgrades
UNKNOWN or SUBMITTED journal entries to conditional authority. The original
SUBMITTED journal is not rewritten by quarantine. A distinct corrective candidate
requires a new issued native handle, ownership, canonical one-use journal and
genuine ancestor-only expected-head publication.


CDC 3.6.4 adds a separate unconsumed guardian bootstrap-failure branch. Use
`guardian_bootstrap_failure={schema: native-guardian-bootstrap-failure/v1,
stdout_sha256, stderr_sha256}` with the same six explicit `channels` pins.
It is mutually exclusive with `preconsume_exit`. Only the original nonce-derived
`.guardian.stdout` and `.guardian.stderr` are documentary custody: stdout is empty
and stderr is the original UTF-8 Python traceback ending in the fixed native
`ValueError: original guardian birth never persisted; no child launch` marker.
Pin actual original raw hashes independently. Neither stream asserts a wait,
controller birth or terminal outcome. Both require regular single-link protected
files, original controller UID/guardian group and mode 0600 or 0640. Opens are
nonblocking and reject FIFOs. Extra files and static pins cannot substitute for
these streams. This branch accepts the original `running` administrative row
only after the original creator and guardian are physically absent and all
canonical/native consumption and effect barriers above still pass.

When the original operation has a durable project-budget preparation, supply
`project_budget_store` as the actual original `GitProjectBudgetStore` to
`authenticate_prelaunch_intake`, and add
`preparation_budget={binding, registration_digest}` to the trusted contract.
The binding is the independently registered original project-budget binding;
the digest is the protected Root registration digest. The SDK authenticates the
queued Root predecessor, first reserved/prepared row, original eligible native
budget revision, exact one unresolved original reservation event and its real
receipt revision. Only the exact monotonic addition of that receipt and the
original prepared-to-submitting native readback transition are admitted. Receipt
removal, replacement, altered registration, foreign channels, outcomes or any
controller consumption fail closed. Observation reserves nothing and closes no
charge. `observe_prelaunch_intake_disposition` accepts the same optional typed
store or derives it from the archived original request and binding.

The tombstone schema remains `prelaunch-intake-disposition/v1`, with original
operation, task and budgets archived, `original_effect=UNKNOWN` and
`actual_wait=null`. The independently released 3.6.3 historical reader accepts
this canonical tombstone and continues to reject its original contract under a
new ID; its runtime need not be upgraded to mint or reinterpret this proof.


## Bounded legacy rejection-site diagnostic (3.6.13)

Original preconsume rejection stderr may contain the established marker and
closed rejection code followed by one `CDC_VPS_REJECTION_SITE=` JSON object.
Its only fields are `module`, `function`, `line` and `type`; all are bounded
and the integer line excludes booleans. This third line is documentary only.
Protected original bytes and their digests, independent Root/project channels,
identity and fresh absence barriers are still required. Retirement retains
UNKNOWN and reserved/spent history, never invents a wait or authorizes replay.


## Legacy guardian prehandle UNKNOWN (3.6.14)

The existing prehandle disposition accepts a separate legacy schema only for an
UNKNOWN row with its original guardian, no start_consumption, no controller
identity and no controllers key. The original protected exit-2 rejection and
all five artifact digests remain required. Optional protected wait is documentary.
Full ancestry, exact original/source heads, fresh Root physical quiescence and
one-use CAS remain mandatory. Reason is `legacy_guardian_prehandle_unknown`,
outcome UNKNOWN and no_send=false. No creator birth or consumption is invented.
Serialized receipts cannot authorize effects. Historical shape validation does
not depend on current PID absence; effect authentication requires fresh absence.
