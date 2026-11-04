import unittest
from terminal_state_v2 import evaluate
HEAD="1"*40
def base(decision="CONTINUE"):
 return {"schema":"terminal-state/v2","invocation_id":"inv-1","scope_id":"scope-1","observed_head":HEAD,
         "decision":decision,"runnable_actions":[{"id":"a1","action":"apply next patch","authority_ref":"user:continue"}],
         "pending_external":None,"blocker":None,"meaningful_progress_refs":[],"completion_evidence_refs":[],
         "checkpoint_ref":"checkpoint:current","lease_released":True}
class Tests(unittest.TestCase):
 def test_no_idle_blocks_terminal_response(self):
  r=evaluate(base());self.assertTrue(r["allowed"]);self.assertFalse(r["final_response_allowed"]);self.assertEqual(r["reason"],"no_idle_runnable_work")
 def test_complete_rejects_runnable_work(self):
  s=base("COMPLETE");s["completion_evidence_refs"]=["test:green"]
  r=evaluate(s);self.assertFalse(r["allowed"]);self.assertEqual(r["reason"],"no_idle_invariant_runnable_work_exists")
 def test_complete_requires_evidence(self):
  s=base("COMPLETE");s["runnable_actions"]=[]
  self.assertFalse(evaluate(s)["allowed"])
 def test_complete_green(self):
  s=base("COMPLETE");s["runnable_actions"]=[];s["completion_evidence_refs"]=["tests:green","scope:closed"]
  r=evaluate(s);self.assertTrue(r["allowed"]);self.assertTrue(r["final_response_allowed"])
 def test_wait_external_requires_exact_binding(self):
  s=base("WAIT_EXTERNAL");s["runnable_actions"]=[];s["pending_external"]={"kind":"ci","id":"42","operation_key":"sha256:x","state":"running","recheck_action":"observe run 42"}
  r=evaluate(s);self.assertTrue(r["allowed"]);self.assertEqual(r["next_action"],"observe run 42")
 def test_blocked_requires_proof_and_trigger(self):
  s=base("BLOCKED");s["runnable_actions"]=[];s["blocker"]={"code":"permission","evidence_refs":["api:403"],"next_action":"retry after permission change","recheck_trigger":"permission-change"}
  self.assertTrue(evaluate(s)["allowed"])
if __name__=="__main__":unittest.main()
