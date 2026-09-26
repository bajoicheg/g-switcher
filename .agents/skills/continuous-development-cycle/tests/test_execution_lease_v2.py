import json, sys, unittest, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import execution_lease_v2 as m

T0="2026-01-01T10:00:00Z"; T1="2026-01-01T10:00:01Z"
OWNER=str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
INV={"invocation_id":"wake-1","automation_id":"auto-1","conversation_id":"chat-1","execution_surface":"watchdog","started_at_utc":T0}
def boundary(progress=True):
    return {"schema":"execution-continuity/v1","invocation_id":"wake-1","current_state":"CHECKPOINT",
            "requested_terminal_outcome":"progress","runnable_next_action":True,
            "meaningful_progress_refs":["git:abc"] if progress else [],
            "primitive_steps":["status_read"],"external_binding":None,"blocker":None,
            "checkpoint_ref":"checkpoint:1","next_action":"continue",
            "lease_release_required":False,"lease_released":False}

class Tests(unittest.TestCase):
    def owned(self):
        return m.acquire(m.initialize("example/project","refs/heads/main"),OWNER,T1,invocation=INV)
    def test_wrong_invocation_cannot_renew(self):
        with self.assertRaisesRegex(ValueError,"invocation binding"):
            m.renew(self.owned(),OWNER,1,"wake-other","2026-01-01T10:00:02Z",activity_ref="git:x")
    def test_release_requires_transactional_finalization(self):
        with self.assertRaisesRegex(ValueError,"transactional finalization"):
            m.release(self.owned(),OWNER,1,"wake-1","2026-01-01T10:00:02Z")
    def test_full_finalization_releases(self):
        r=self.owned()
        r=m.begin_finalization(r,OWNER,1,"wake-1","2026-01-01T10:00:02Z",pending_shared_writes=False)
        r=m.record_checkpoint(r,OWNER,1,"wake-1","2026-01-01T10:00:03Z",checkpoint_ref="checkpoint:1",pending_shared_writes=False)
        r=m.reconcile_finalization(r,OWNER,1,"wake-1","2026-01-01T10:00:04Z",external_reconciliation="none")
        r=m.mark_ready(r,OWNER,1,"wake-1","2026-01-01T10:00:05Z",continuity_state=boundary())
        r=m.release(r,OWNER,1,"wake-1","2026-01-01T10:00:06Z")
        self.assertIsNone(r["owner_id"]); self.assertEqual(r["last_release"]["invocation_id"],"wake-1")
    def test_primitive_boundary_cannot_mark_ready(self):
        r=self.owned()
        r=m.begin_finalization(r,OWNER,1,"wake-1","2026-01-01T10:00:02Z",pending_shared_writes=False)
        r=m.record_checkpoint(r,OWNER,1,"wake-1","2026-01-01T10:00:03Z",checkpoint_ref="checkpoint:1",pending_shared_writes=False)
        r=m.reconcile_finalization(r,OWNER,1,"wake-1","2026-01-01T10:00:04Z",external_reconciliation="none")
        with self.assertRaisesRegex(ValueError,"hard execution-continuity"):
            m.mark_ready(r,OWNER,1,"wake-1","2026-01-01T10:00:05Z",continuity_state=boundary(False))
    def test_failed_finalization_can_restart_transaction(self):
        r=self.owned()
        r=m.fail_finalization(r,OWNER,1,"wake-1","2026-01-01T10:00:02Z",failure="checkpoint write failed")
        r=m.begin_finalization(r,OWNER,1,"wake-1","2026-01-01T10:00:03Z",pending_shared_writes=False)
        self.assertEqual(r["finalization"]["state"],"draining")
        self.assertIsNone(r["finalization"]["failure"])
    def test_migration_preserves_attested_noncanonical_legacy_history(self):
        old=json.loads((ROOT/"templates/execution-lease.json").read_text())
        old=m.legacy.acquire(old,OWNER,T1)
        old=m.legacy.release(old,OWNER,1,"2026-01-01T10:00:02Z")
        claim={"grant_id":"22222222-2222-4222-8222-222222222222","owner_id":"legacy-owner",
               "generation":1,"operation_key":"sha256:"+"a"*64,"attempt_id":"legacy-attempt",
               "intent_digest":"sha256:"+"b"*64,"claimed_at_utc":"2026-01-01T10:00:01Z"}
        old["submission_claims"].append(claim)
        old["takeover_evidence"]={"owner_id":OWNER,"generation":1,"repository":"example/project",
                                  "source_ref":"refs/heads/main","kind":"explicit_release","reference":"legacy:release"}
        migrated=m.migrate_v1(old,"2026-01-01T10:00:03Z")
        self.assertEqual(migrated["legacy_migration"]["migrated_generation"],1)
        self.assertEqual(len(migrated["legacy_migration"]["noncanonical_claim_digests"]),1)
        m.validate(migrated)
    def test_v1_migration_only_when_released(self):
        old=json.loads((ROOT/"templates/execution-lease.json").read_text())
        self.assertEqual(m.migrate_v1(old,"2026-01-01T10:00:02Z")["schema"],"execution-lease/v2")
        owned=m.legacy.acquire(old,OWNER,T1)
        with self.assertRaisesRegex(ValueError,"owned v1 lease"):
            m.migrate_v1(owned,"2026-01-01T10:00:02Z")

if __name__=="__main__": unittest.main()
