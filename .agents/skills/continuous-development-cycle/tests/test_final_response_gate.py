from pathlib import Path
import copy,sys,unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import execution_lease_v2 as leasev2
from final_response_gate import evaluate

OWNER="22222222-2222-4222-8222-222222222222";INV_ID="chat-final"
INV={"invocation_id":INV_ID,"automation_id":None,"conversation_id":None,"execution_surface":"managed","started_at_utc":"2026-01-01T10:00:00Z"}
CP="https://example.test/checkpoint"
HEAD="a"*40

def continuity(released):
 return {
  "schema":"execution-continuity/v1","invocation_id":INV_ID,"current_state":"COMPLETE","requested_terminal_outcome":"scope_complete",
  "runnable_next_action":False,"meaningful_progress_refs":["git:"+HEAD],"primitive_steps":[],"external_binding":None,"blocker":None,
  "checkpoint_ref":CP,"next_action":None,"lease_release_required":released,"lease_released":released,
  "terminal_state":{"schema":"terminal-state/v2","invocation_id":INV_ID,"scope_id":"scope","observed_head":HEAD,"decision":"COMPLETE",
    "runnable_actions":[],"pending_external":None,"blocker":None,"meaningful_progress_refs":["git:"+HEAD],
    "completion_evidence_refs":["evidence:scope-complete"],"checkpoint_ref":CP,"lease_released":released}
 }

def receipt(lease,revision="b"*40):
 return {"schema":"execution-release-receipt/v1","lease_revision":revision,"release":copy.deepcopy(lease["last_release"])}

class T(unittest.TestCase):
 def admit(self,record,owner,at,inv):
  with mock.patch.object(leasev2.terminal_capability_api,"validate_verified",return_value={}):
   return leasev2.acquire(record,owner,at,invocation=inv,terminal_capability=object(),ttl=1200)
 def owned(self):
  return self.admit(leasev2.initialize("o/r","refs/heads/main"),OWNER,"2026-01-01T10:00:00Z",INV)
 def released(self):
  r=self.owned()
  r=leasev2.begin_finalization(r,OWNER,1,INV_ID,"2026-01-01T10:01:00Z",pending_shared_writes=False)
  r=leasev2.record_checkpoint(r,OWNER,1,INV_ID,"2026-01-01T10:01:01Z",checkpoint_ref=CP,pending_shared_writes=False)
  r=leasev2.reconcile_finalization(r,OWNER,1,INV_ID,"2026-01-01T10:01:02Z",external_reconciliation="none")
  r=leasev2.mark_ready(r,OWNER,1,INV_ID,"2026-01-01T10:01:03Z",continuity_state=continuity(False))
  return leasev2.release(r,OWNER,1,INV_ID,"2026-01-01T10:01:04Z")
 def test_spoofed_managed_label_without_capability_cannot_enter_owned_terminal_path(self):
  with self.assertRaisesRegex(ValueError,"capability proof"):
   leasev2.acquire(leasev2.initialize("o/r","refs/heads/main"),OWNER,"2026-01-01T10:00:00Z",invocation=INV,ttl=1200)
 def test_ordinary_chat_cannot_enter_owned_terminal_path(self):
  chat=dict(INV,execution_surface="chat")
  with self.assertRaisesRegex(ValueError,"observer/orchestrator only"):
   leasev2.acquire(leasev2.initialize("o/r","refs/heads/main"),OWNER,"2026-01-01T10:00:00Z",invocation=chat,ttl=1200)
 def test_owned_invocation_cannot_final_respond(self):
  r=evaluate(INV_ID,self.owned(),continuity(False),{"owner_id":OWNER,"generation":1},None,None,"2026-01-01T10:02:00Z")
  self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"invocation_still_owns_exact_generation")
 def test_exact_released_generation_can_final_respond(self):
  lease=self.released();r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},receipt(lease),lease,"2026-01-01T10:02:00Z")
  self.assertTrue(r["allowed"]);self.assertTrue(r["final_response_allowed"])
 def test_different_release_does_not_satisfy_owned_generation(self):
  lease=self.released();bad_receipt=receipt(lease);bad_receipt["release"]["generation"]=0
  r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},bad_receipt,lease,"2026-01-01T10:02:00Z")
  self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"release_receipt_revision_mismatch")
 def test_pre_release_continuity_never_substitutes_for_release(self):
  lease=self.released()
  r=evaluate(INV_ID,lease,continuity(False),{"owner_id":OWNER,"generation":1},receipt(lease),lease,"2026-01-01T10:02:00Z")
  self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"continuity_does_not_record_post_release_state")
 def test_successor_owner_does_not_reopen_released_invocation(self):
  lease=self.released()
  other="55555555-5555-4555-8555-555555555555"
  inv2={"invocation_id":"chat-next","automation_id":None,"conversation_id":None,"execution_surface":"managed","started_at_utc":"2026-01-01T10:02:00Z"}
  first_record=copy.deepcopy(lease);first_receipt=receipt(first_record)
  lease=self.admit(lease,other,"2026-01-01T10:02:00Z",inv2)
  r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},first_receipt,first_record,"2026-01-01T10:03:00Z")
  self.assertTrue(r["allowed"])
 def test_successor_release_cannot_erase_prior_release_proof(self):
  lease=self.released();first_record=copy.deepcopy(lease);first_receipt=receipt(first_record)
  other="55555555-5555-4555-8555-555555555555"
  inv2={"invocation_id":"chat-next","automation_id":None,"conversation_id":None,"execution_surface":"managed","started_at_utc":"2026-01-01T10:02:00Z"}
  lease=self.admit(lease,other,"2026-01-01T10:02:00Z",inv2)
  lease=leasev2.begin_finalization(lease,other,2,"chat-next","2026-01-01T10:03:00Z",pending_shared_writes=False)
  lease=leasev2.record_checkpoint(lease,other,2,"chat-next","2026-01-01T10:03:01Z",checkpoint_ref=CP,pending_shared_writes=False)
  lease=leasev2.reconcile_finalization(lease,other,2,"chat-next","2026-01-01T10:03:02Z",external_reconciliation="none")
  c2=copy.deepcopy(continuity(False));c2["invocation_id"]="chat-next";c2["terminal_state"]["invocation_id"]="chat-next"
  lease=leasev2.mark_ready(lease,other,2,"chat-next","2026-01-01T10:03:03Z",continuity_state=c2)
  lease=leasev2.release(lease,other,2,"chat-next","2026-01-01T10:03:04Z")
  self.assertEqual(lease["last_release"]["generation"],2)
  r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},first_receipt,first_record,"2026-01-01T10:04:00Z")
  self.assertTrue(r["allowed"])
 def test_receipt_requires_authoritative_revision_record(self):
  lease=self.released();proof=receipt(lease)
  r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},proof,None,"2026-01-01T10:02:00Z")
  self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"authoritative_release_revision_readback_required")
  forged=copy.deepcopy(lease);forged["last_release"]["invocation_id"]="other"
  r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},proof,forged,"2026-01-01T10:02:00Z")
  self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"release_receipt_revision_mismatch")
 def test_owned_generation_requires_durable_release_receipt(self):
  lease=self.released()
  r=evaluate(INV_ID,lease,continuity(True),{"owner_id":OWNER,"generation":1},None,None,"2026-01-01T10:02:00Z")
  self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"durable_release_receipt_required")

if __name__=="__main__":unittest.main()
