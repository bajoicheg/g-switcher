from pathlib import Path
import copy,sys,unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fleet_supervisor_control as m

A="33333333-3333-4333-8333-333333333333";B="44444444-4444-4444-8444-444444444444"
HEAD="a"*40;CAP=object()
def inv(name):return {"invocation_id":name,"automation_id":None,"conversation_id":None,"execution_surface":"managed","started_at_utc":"2026-01-01T10:00:00Z"}

class Store:
 def __init__(self):self.rev=None;self.doc=None;self.n=0
 def read(self):return self.rev,copy.deepcopy(self.doc)
 def compare_and_swap(self,expected,doc):
  if self.rev!=expected:raise ValueError("stale expected document revision")
  self.n+=1;self.rev=f"{self.n:040x}";self.doc=copy.deepcopy(doc);return self.rev

def continuity(invocation_id,checkpoint):
 return {
  "schema":"execution-continuity/v1","invocation_id":invocation_id,"current_state":"COMPLETE",
  "requested_terminal_outcome":"scope_complete","runnable_next_action":False,
  "meaningful_progress_refs":["fleet:done"],"primitive_steps":[],"external_binding":None,"blocker":None,
  "checkpoint_ref":checkpoint,"next_action":None,"lease_release_required":False,"lease_released":False,
  "terminal_state":{"schema":"terminal-state/v2","invocation_id":invocation_id,"scope_id":"fleet",
   "observed_head":"a"*40,"decision":"COMPLETE","runnable_actions":[],"pending_external":None,"blocker":None,
   "meaningful_progress_refs":["fleet:done"],"completion_evidence_refs":["fleet:verified"],
   "checkpoint_ref":checkpoint,"lease_released":False}
 }

class T(unittest.TestCase):
 def setUp(self):
  patcher=mock.patch.object(m.leasev2.terminal_capability_api,"validate_verified",return_value={})
  patcher.start();self.addCleanup(patcher.stop)
 def acquire_record(self,*args,**kwargs):
  return m.acquire_record(*args,terminal_capability=CAP,**kwargs)
 def acquire_cas(self,*args,**kwargs):
  return m.acquire_cas(*args,terminal_capability=CAP,**kwargs)
 def effect_id(self,s):
  self.assertEqual(len(s["effects"]),1);return s["effects"][0]["effect_id"]
 def leader(self):
  s=m.initialize("o/fleet","refs/heads/cdc/fleet")
  return self.acquire_record(s,A,"2026-01-01T10:00:00Z",inv("a"))
 def req(self,intent=None):
  return {"kind":"project_wake","target":"o/project","observed_fleet_head":HEAD,"intent":intent or {"reason":"stalled"}}
 def test_leader_transactional_release_returns_revision_receipt(self):
  store=Store()
  acq=self.acquire_cas(store,None,"o/fleet","refs/heads/cdc/fleet",A,"2026-01-01T10:00:00Z",inv("a"))
  r=m.begin_finalization_cas(store,acq["revision"],A,1,"a","2026-01-01T10:01:00Z")
  r=m.record_checkpoint_cas(store,r["revision"],A,1,"a","2026-01-01T10:01:01Z",checkpoint_ref="fleet:checkpoint")
  r=m.reconcile_finalization_cas(store,r["revision"],A,1,"a","2026-01-01T10:01:02Z")
  r=m.mark_ready_cas(store,r["revision"],A,1,"a","2026-01-01T10:01:03Z",continuity_state=continuity("a","fleet:checkpoint"))
  r=m.release_leader_cas(store,r["revision"],A,1,"a","2026-01-01T10:01:04Z")
  self.assertIsNone(r["state"]["lease"]["owner_id"])
  self.assertEqual(r["release_receipt"]["lease_revision"],r["revision"])
  self.assertEqual(r["release_receipt"]["release"]["generation"],1)
 def test_unresolved_effect_blocks_leader_reconcile_and_release(self):
  store=Store()
  acq=self.acquire_cas(store,None,"o/fleet","refs/heads/cdc/fleet",A,"2026-01-01T10:00:00Z",inv("a"))
  s,d=m.claim_effect_record(acq["state"],A,1,"a","2026-01-01T10:00:30Z",HEAD,self.req())
  rev=store.compare_and_swap(acq["revision"],s)
  r=m.begin_finalization_cas(store,rev,A,1,"a","2026-01-01T10:01:00Z")
  r=m.record_checkpoint_cas(store,r["revision"],A,1,"a","2026-01-01T10:01:01Z",checkpoint_ref="fleet:checkpoint")
  with self.assertRaisesRegex(ValueError,"unresolved side effects"):
   m.reconcile_finalization_cas(store,r["revision"],A,1,"a","2026-01-01T10:01:02Z")

 def test_cas_allows_only_one_subscription_to_become_leader(self):
  store=Store()
  a=self.acquire_cas(store,None,"o/fleet","refs/heads/cdc/fleet",A,"2026-01-01T10:00:00Z",inv("a"))
  self.assertEqual(a["generation"],1)
  with self.assertRaisesRegex(ValueError,"stale"):self.acquire_cas(store,None,"o/fleet","refs/heads/cdc/fleet",B,"2026-01-01T10:00:00Z",inv("b"))
 def test_nonleader_cannot_claim_fleet_effect(self):
  s=self.leader()
  with self.assertRaisesRegex(ValueError,"not fleet leader"):m.claim_effect_record(s,B,1,"b","2026-01-01T10:01:00Z",HEAD,self.req())
 def test_same_effect_id_is_one_shot(self):
  s,d=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  self.assertTrue(d["authorizes_effect"]);self.assertEqual(len(s["effects"]),1)
  s2,d2=m.claim_effect_record(s,A,1,"a","2026-01-01T10:02:00Z",HEAD,self.req())
  self.assertFalse(d2["authorizes_effect"]);self.assertEqual(d2["action"],"OBSERVE_EXISTING");self.assertEqual(len(s2["effects"]),1)
 def test_same_semantic_effect_derives_same_id_independent_of_caller(self):
  s,d=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  eid=d["effect"]["effect_id"]
  self.assertTrue(eid.startswith("sha256:"))
  s2,d2=m.claim_effect_record(s,A,1,"a","2026-01-01T10:02:00Z",HEAD,self.req())
  self.assertEqual(d2["effect"]["effect_id"],eid);self.assertEqual(d2["action"],"OBSERVE_EXISTING")
 def test_caller_cannot_supply_alternate_effect_id(self):
  bad=self.req();bad["effect_id"]="caller-chosen"
  with self.assertRaisesRegex(ValueError,"effect request invalid"):
   m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,bad)
 def test_persisted_effect_identity_must_be_content_addressed(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  bad=copy.deepcopy(s);bad["effects"][0]["effect_id"]="caller"
  with self.assertRaisesRegex(ValueError,"effect_id must be sha256"):m.validate(bad)
  bad=copy.deepcopy(s);bad["effects"][0]["intent_digest"]="sha256:bad"
  with self.assertRaisesRegex(ValueError,"intent_digest must be sha256"):m.validate(bad)
 def test_unresolved_semantic_effect_blocks_new_id_after_fleet_head_change(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  eid=self.effect_id(s)
  s=m.update_effect_record(s,A,1,"a","2026-01-01T10:02:00Z",eid,"unknown","scheduler:request-1")
  req=self.req(intent={"reason":"stalled-again"});req["observed_fleet_head"]="b"*40
  s2,d=m.claim_effect_record(s,A,1,"a","2026-01-01T10:03:00Z","b"*40,req)
  self.assertEqual(d["action"],"OBSERVE_PENDING_CONFLICT");self.assertFalse(d["authorizes_effect"])
  self.assertEqual(d["effect"]["effect_id"],eid);self.assertEqual(len(s2["effects"]),1)
 def test_changed_fleet_head_replans_before_claim(self):
  s,d=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z","b"*40,self.req())
  self.assertEqual(d["action"],"REPLAN_FLEET_HEAD");self.assertFalse(d["authorizes_effect"]);self.assertEqual(s["effects"],[])
 def test_unknown_effect_blocks_leader_replacement(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  s=m.update_effect_record(s,A,1,"a","2026-01-01T10:02:00Z",self.effect_id(s),"unknown","scheduler:request-1")
  self.assertEqual(m.assess_takeover(s)["action"],"BLOCK_PENDING_EFFECTS")
  q={"owner_id":A,"generation":1,"repository":"o/fleet","source_ref":"refs/heads/cdc/fleet","invocation_id":"a","kind":"executor_stopped","reference":"runtime:a:stopped","pending_shared_writes":False,"external_effects_state":"preserved_unknown"}
  with self.assertRaisesRegex(ValueError,"unresolved side effects"):self.acquire_record(s,B,"2026-01-01T10:03:00Z",inv("b"),quiescence=q)
 def observation(self,s,eid=None,state="terminal",receipt="scheduler:run-1",outcome="success",lookup=True):
  if eid is None:eid=self.effect_id(s)
  e=next(x for x in s["effects"] if x["effect_id"]==eid)
  return {"schema":"fleet-effect-observation/v1","effect_id":eid,"intent_digest":e["intent_digest"],"lookup_complete":lookup,
          "observed_at_utc":"2026-01-01T10:03:00Z","state":state,"receipt_ref":receipt,"outcome":outcome,"evidence_ref":"provider:lookup-1"}
 def test_standby_can_reconcile_unknown_effect_without_replay_authority(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  s=m.update_effect_record(s,A,1,"a","2026-01-01T10:02:00Z",self.effect_id(s),"unknown","scheduler:request-1")
  s,d=m.reconcile_effect_record(s,self.effect_id(s),self.observation(s))
  self.assertEqual(d["action"],"TERMINAL_RECONCILED");self.assertTrue(d["resolved"]);self.assertFalse(d["authorizes_effect"])
  self.assertEqual(m.assess_takeover(s)["action"],"REQUIRE_EXECUTOR_STOPPED_EVIDENCE")
  q={"owner_id":A,"generation":1,"repository":"o/fleet","source_ref":"refs/heads/cdc/fleet","invocation_id":"a","kind":"executor_stopped","reference":"runtime:a:stopped","pending_shared_writes":False,"external_effects_state":"reconciled"}
  s=self.acquire_record(s,B,"2026-01-01T10:04:00Z",inv("b"),quiescence=q)
  self.assertEqual(s["lease"]["owner_id"],B);self.assertEqual(s["lease"]["generation"],2)
 def test_running_reconciliation_keeps_takeover_blocked(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  s,d=m.reconcile_effect_record(s,self.effect_id(s),self.observation(s,state="running",outcome=None))
  self.assertEqual(d["action"],"WAIT_EFFECT");self.assertFalse(d["authorizes_effect"])
  self.assertEqual(m.assess_takeover(s)["action"],"BLOCK_PENDING_EFFECTS")
 def test_complete_not_found_lookup_can_close_pre_submit_claim(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  o=self.observation(s,state="not_found",receipt=None,outcome=None,lookup=True)
  s,d=m.reconcile_effect_record(s,self.effect_id(s),o)
  self.assertTrue(d["resolved"]);self.assertEqual(s["effects"][0]["outcome"],"not_submitted_observed")
 def test_incomplete_or_mismatched_observation_cannot_clear_effect(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  o=self.observation(s,state="unknown",receipt=None,outcome=None,lookup=False)
  s2,d=m.reconcile_effect_record(s,self.effect_id(s),o);self.assertEqual(s2,s);self.assertFalse(d["resolved"])
  o=self.observation(s);o["intent_digest"]="sha256:"+"0"*64
  with self.assertRaisesRegex(ValueError,"intent mismatch"):m.reconcile_effect_record(s,self.effect_id(s),o)
 def test_terminal_effect_allows_quiescence_based_replacement(self):
  s,_=m.claim_effect_record(self.leader(),A,1,"a","2026-01-01T10:01:00Z",HEAD,self.req())
  s=m.update_effect_record(s,A,1,"a","2026-01-01T10:02:00Z",self.effect_id(s),"terminal","scheduler:run-1","success")
  q={"owner_id":A,"generation":1,"repository":"o/fleet","source_ref":"refs/heads/cdc/fleet","invocation_id":"a","kind":"executor_stopped","reference":"runtime:a:stopped","pending_shared_writes":False,"external_effects_state":"reconciled"}
  s=self.acquire_record(s,B,"2026-01-01T10:03:00Z",inv("b"),quiescence=q)
  self.assertEqual(s["lease"]["owner_id"],B);self.assertEqual(s["lease"]["generation"],2)

if __name__=="__main__":unittest.main()
