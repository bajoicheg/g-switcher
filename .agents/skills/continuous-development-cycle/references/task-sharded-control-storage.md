# Opt-in original control task storage

CDC 3.6.17 adds `task_shards=True` only on the exact native `GitDocumentStore`
class. Keep the default `False` for existing stores and staged installations.
The original `cdc-vps-control/v1` logical document, task IDs, rows, UNKNOWN,
original claims/guards/reservations, budgets/spent and complete native ancestry
are preserved. TaskStore and recovery authenticate the reconstructed original
logical documents; this storage representation supplies no native capability.

The physical root contains exactly the regular canonical `document.json`
manifest and a `tasks` tree. The manifest has only `schema`, `document`,
`task_count` and `logical_sha256`; schema is `git-document-task-shards/v1`.
`document` retains every original top-level field except `tasks`. The digest is
SHA-256 of the complete original canonical UTF-8 JSON plus LF. Each regular task
blob has only `task_id` and `row`; its filename is the SHA-256 hex of the UTF-8
original task ID followed by `.json`. The filename, wrapper ID and `row.task.id`
must agree. Missing, extra, duplicate, substituted or noncanonical entries fail.

Module `canonical()` and legacy blobs keep their 4 MiB limit. Every manifest
and task blob also keeps 4 MiB, the task index tree 4 MiB and count 16,384. Logical
canonical bytes and aggregate manifest plus task blob bytes are separately
bounded at 128 MiB. Git headers are checked before body materialization, in
batches of at most 16 task objects. `store.canonical(document)` supplies the
matching bounded logical comparison; callers must not replace native validation
with a storage digest. Unchanged rows reuse their immutable task blobs.

`read`, `read_revision` and internal historical reads support mixed old/new
commits when opted in. The original remote identity, full linear graph, fresh
head checks, typed native transition/capability checks and one-use proposal
binding remain mandatory. CAS prepares all objects locally and publishes one
nonce-bearing commit with exactly the expected parent through the original
nonforce ref update. Lost push/readback replies are observed without retrying
an UNKNOWN write. No secondary authoritative ref or external archive is added.

Stage a new runtime in legacy mode. An old 3.6.16 reader rejects the extra task
tree and cannot silently overwrite it, but an already launched old controller
or provider may continue its effect and then fail metadata finalization. Enable
opt-in only after the existing genuine native completion/quiet/disposition
boundary establishes that no old pinned actor can still act. Preserve original
IDs and terminal_pending/UNKNOWN until their supported native mechanism settles
them; never retire a task merely to obtain storage capacity. Only the control
store context should opt in; unrelated publication, inventory and watchdog
stores keep their original defaults.

Under the authorized original controller identity and expected head, migration
is one ordinary CAS with exactly the same logical document followed by native
readback and history validation. Reads never migrate. The first opted-in write
also changes physical format, so its activation needs the same boundary.
After migration, do not rewind the ref or resume an incompatible old runtime.
Any forward legacy conversion needs genuine current native CAS and a logical
document that still fits 4 MiB. Canonical release, installed immutable runtime,
Source/role/provider permission and actual consumer adoption remain distinct.


## Already released success with oversized pending completion

A confirmed original SUCCEEDED writer can remain terminal_pending when its
unchanged completion metadata would exceed legacy capacity. The existing
`migrate_intake_registry_cas(..., terminal_reconciliations={task_id: proof})`
accepts a live package-owned same-boot `VerifiedTerminalProof` for this narrow
case. The task must be the exact v2 writer with no CI admission, released native
session and successful finish. Original start/source/plan/handle/attempt,
reservation, lease/release and owner/generation must agree. The original Source
publication must retain its confirmed conditional-update journal and exact
recorded evidence; verification never sends or recovers that publication.
Fresh ordinary proof revalidation authenticates original accepted/integrated
pool result and physical absence of the original controller and every process.
A serialized proof, foreign boot, reused/live PID, altered publication, missing
owner custody or unrelated active attempt is denied. The existing explicit
FAILED cross-boot route remains separate and unchanged.

This proof authorizes only the sealed registry-digest migration. It does not
mark the task completed, settle reservations, clear UNKNOWN, change the queue,
restart the worker or publish Source. Native CAS revalidates the same proof and
permits only registry_digest to differ. After its single physical sharding and
pin migration, the original supported completion path may write original success
metadata through the new runtime. An ambiguous migration reply remains UNKNOWN
and is reconciled through the original head/proposal without resending it.
