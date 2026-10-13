# Compatible managed finish controller recovery

CDC 2.11.7 corrects the fixed launch activity reference used by 2.11.6 finish retries. A successful finish admission re-observes the exact held supervisor, verifies the clean assigned result and scope, and durably records that validation before package-owned renewal. Polling and rejected results do not refresh ownership.

A verified immutable 2.11.7 package may serve as controller for an unchanged 2.11.6 managed-host-handle/v1 session, only after these checks:

1. Verify the old full package against immutable release/v2.11.6, commit b3b517fb70e2deea4006e265f708f29881377885, tree 79257a06c40de6f514f9b059be05d610885a50e7, all 329 files.
2. Verify the complete corrected package against its immutable release commit/tree, including VERSION, manifest and SKILL.md. Load it in a separate controller directory outside the active consumer subtree.
3. Read the unchanged opaque handle, session, request and journal. Require the same owner, generation, invocation and live supervisor, awaiting_release, quiescent=false and pending_terminal_status=succeeded. Require a clean assigned branch/result, unchanged source precondition and no unresolved writer guard.
4. Invoke the canonical corrected finish command with the original handle root/id and valid original output/evidence/checkpoint references. Only the controller validates, renews, reconciles publication and releases. The observer must not renew or rewrite lease/session/capability/receipt data.
5. Verify exact publication or read-only result, the same-owner release receipt and supervisor quiescence. Repeated released finish is idempotent.

Never launch a replacement worker, create a replacement invocation, or replace the active consumer package while its owner is held. Unknown ownership, changed supervisor/source, invalid result and unresolved guard remain fail-closed. Failed/cancelled/timed-out workers retain existing no-publication finalization. Ordinary atomic adoption follows release/quiescence separately.

Acceptance uses independently verified old full package to launch an actual worker/supervisor in isolated Git, injects a pre-publication transient failure, and lets the corrected controller finish the same handle after 601 seconds. It checks identity, supervisor, historical claims, exact publication/release/quiescence and repeated-finish idempotency. Same-version unit tests alone are insufficient.
