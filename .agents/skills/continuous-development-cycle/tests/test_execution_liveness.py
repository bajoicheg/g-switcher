from pathlib import Path
import copy,json,sys,unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import execution_lease_v2 as leasev2
import operation_intent as op
from execution_liveness import classify
ROOT=Path(__file__).resolve().parents[1]

OWNER="11111111-1111-4111-8111-111111111111"
INV={"invocation_id":"chat-a","automation_id":None,"conversation_id":None,"execution_surface":"managed","started_at_utc":"2026-01-01T10:00:00Z"}

class Store:
 def __init__(self,record):
  self.revision="r0";self.record=copy.deepcopy(record);self.n=0
 def read(self):return self.revision,copy.deepcopy(self.record)
 def compare_and_swap(self,expected,record):
  if expected!=self.revision:raise ValueError("stale")
  self.n+=1;self.revision="r"+str(self.n);self.record=copy.deepcopy(record);return self.revision

class T(unittest.TestCase):
 def owned(self):
  r=leasev2.initialize("o/r","refs/heads/main")
  with mock.patch.object(leasev2.terminal_capability_api,"validate_verified",return_value={}):
   return leasev2.acquire(r,OWNER,"2026-01-01T10:00:00Z",invocation=INV,terminal_capability=object(),ttl=1200)
 def runtime(self,state="running",inv="chat-a"):
  return {"schema":"runtime-observation/v1","invocation_id":inv,"state":state,"observed_at_utc":"2026-01-01T10:05:00Z","evidence_ref":"runtime:test"}
 def test_owner_record_without_runtime_is_not_active(self):
  self.assertEqual(classify(self.owned(),None,"2026-01-01T10:05:00Z")["state"],"unknown")
 def test_exact_running_runtime_plus_fresh_lease_is_active(self):
  self.assertEqual(classify(self.owned(),self.runtime(),"2026-01-01T10:05:00Z")["state"],"active")
 def test_stopped_clean_owner_is_orphaned_recoverable(self):
  r=classify(self.owned(),self.runtime("stopped"),"2026-01-01T10:05:00Z")
  self.assertEqual(r["state"],"orphaned_recoverable");self.assertTrue(r["quiescence_candidate"]);self.assertFalse(r["authorizes_takeover"])
 def test_stopped_with_guard_is_blocked_unknown_effects(self):
  r=self.owned();r["external_guard"]={"intent":{"state":"submitting"}}
  with self.assertRaises(ValueError): leasev2.validate(r)
 def test_stopped_with_pending_shared_write_is_blocked(self):
  r=self.owned();r["finalization"]["pending_shared_writes"]=True
  self.assertEqual(classify(r,self.runtime("stopped"),"2026-01-01T10:05:00Z")["state"],"blocked_unknown_effects")
 def test_mismatched_runtime_never_proves_active_or_stopped(self):
  self.assertEqual(classify(self.owned(),self.runtime("stopped","other"),"2026-01-01T10:05:00Z")["state"],"unknown")
 def test_expired_lease_plus_running_claim_is_unknown_not_active(self):
  self.assertEqual(classify(self.owned(),self.runtime(),"2026-01-01T10:25:00Z")["state"],"unknown")
 def test_released_is_released_without_runtime(self):
  r=leasev2.initialize("o/r","refs/heads/main")
  self.assertEqual(classify(r,None,"2026-01-01T10:05:00Z")["state"],"released")
 def test_old_running_observation_is_unknown_even_when_lease_was_renewed(self):
  r=self.owned()
  r=leasev2.renew(r,OWNER,1,"chat-a","2026-01-01T10:09:00Z",activity_ref="git:new",ttl=1200)
  self.assertEqual(classify(r,self.runtime("running"),"2026-01-01T10:10:30Z")["state"],"unknown")

 def terminal_reconciled_claim(self,checkpointed=False):
  r=self.owned()
  intent=op._load(ROOT/"templates"/"operation-intent.json")
  intent["created_at_utc"]="2026-01-01T10:00:00Z";intent["updated_at_utc"]="2026-01-01T10:00:00Z"
  intent["binding"]["repository"]="o/r";intent["source_ref"]="refs/heads/main"
  intent["operation_key"]=op.operation_key(intent["binding"])
  receipt=op.verify_readback(intent,copy.deepcopy(intent),"store:intent/1",intent["updated_at_utc"])
  intent=op.transition(intent,"submitting",intent["updated_at_utc"],receipt=receipt)
  r=leasev2.set_guard(r,OWNER,1,"chat-a","2026-01-01T10:01:00Z",intent,"store:intent/submitting")
  store=Store(r)
  claim=leasev2.claim_submission(store,"r0","o/r","refs/heads/main",OWNER,1,"chat-a",
                                 "2026-01-01T10:01:01Z",intent_digest=r["external_guard"]["intent_digest"])
  r=store.read()[1]
  task={"task_id":"task-1","task_url":"https://example.invalid/task/1",
        "operation_key":intent["operation_key"],"attempt_id":intent["attempt_id"],
        "binding":copy.deepcopy(intent["binding"]),"state":"terminal",
        "conclusion":"succeeded","evidence_refs":["provider:log/1"]}
  observation={"schema":"operation-observation/v1","operation_key":intent["operation_key"],
               "observed_at_utc":"2026-01-01T10:02:00Z","lookup_complete":True,"tasks":[task]}
  r=leasev2.clear_guard(r,OWNER,1,"chat-a","2026-01-01T10:02:00Z",observation,"provider:terminal/1")
  self.assertEqual(len(r["submission_claims"]),1)
  self.assertEqual(len(r["submission_resolutions"]),1)
  self.assertEqual(r["submission_resolutions"][0]["grant_id"],claim["grant"]["grant_id"])
  if checkpointed:
   r=leasev2.begin_finalization(r,OWNER,1,"chat-a","2026-01-01T10:02:01Z",pending_shared_writes=False)
   r=leasev2.record_checkpoint(r,OWNER,1,"chat-a","2026-01-01T10:02:02Z",
                               checkpoint_ref="checkpoint:g-pc-health-check",pending_shared_writes=False)
  return r
 def test_terminal_reconciled_current_generation_claim_is_not_pending(self):
  r=self.terminal_reconciled_claim()
  a=classify(r,self.runtime("stopped"),"2026-01-01T10:05:00Z")
  self.assertEqual(a["state"],"orphaned_recoverable");self.assertTrue(a["quiescence_candidate"])
  self.assertFalse(a["authorizes_takeover"])
 def test_unreconciled_claim_remains_blocked(self):
  r=self.owned()
  intent=op._load(ROOT/"templates"/"operation-intent.json")
  intent["created_at_utc"]="2026-01-01T10:00:00Z";intent["updated_at_utc"]="2026-01-01T10:00:00Z"
  intent["binding"]["repository"]="o/r";intent["source_ref"]="refs/heads/main";intent["operation_key"]=op.operation_key(intent["binding"])
  receipt=op.verify_readback(intent,copy.deepcopy(intent),"store:intent/2",intent["updated_at_utc"])
  intent=op.transition(intent,"submitting",intent["updated_at_utc"],receipt=receipt)
  r=leasev2.set_guard(r,OWNER,1,"chat-a","2026-01-01T10:01:00Z",intent,"store:intent/submitting")
  store=Store(r);leasev2.claim_submission(store,"r0","o/r","refs/heads/main",OWNER,1,"chat-a",
                                         "2026-01-01T10:01:01Z",intent_digest=r["external_guard"]["intent_digest"])
  r=store.read()[1]
  self.assertEqual(classify(r,self.runtime("stopped"),"2026-01-01T10:05:00Z")["state"],"blocked_unknown_effects")
 def test_checkpointed_terminal_provider_matches_g_pc_health_check_orphan(self):
  r=self.terminal_reconciled_claim(checkpointed=True)
  a=classify(r,self.runtime("stopped"),"2026-01-01T10:05:00Z")
  self.assertEqual(r["finalization"]["state"],"checkpointed")
  self.assertEqual(a["state"],"orphaned_recoverable")

if __name__=="__main__":unittest.main()
