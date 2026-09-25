import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import cost_router as m

REG={"schema":"backend-capability-registry/v1","observed_at_utc":"2026-09-25T10:00:00Z","backends":[
 {"backend_id":"codex","kind":"codex_compute","enabled":True,"state":"ready","rank":10,"capabilities":["os:linux","python:3","git"],"configuration_digest":"sha256:"+"1"*64,"last_verified_at_utc":"2026-09-25T09:59:00Z","evidence_refs":["env:codex"]},
 {"backend_id":"other","kind":"other_compute","enabled":True,"state":"ready","rank":20,"capabilities":["os:linux","python:3","git"],"configuration_digest":"sha256:"+"2"*64,"last_verified_at_utc":"2026-09-25T09:59:00Z","evidence_refs":["env:other"]},
 {"backend_id":"gha","kind":"github_actions","enabled":True,"state":"ready","rank":50,"capabilities":["os:linux","python:3","git","feature:emulator"],"configuration_digest":"sha256:"+"3"*64,"last_verified_at_utc":"2026-09-25T09:59:00Z","evidence_refs":["workflow:gha"]}]}
REQ={"schema":"capability-request/v1","task_id":"t","candidate_sha":"a"*40,"required_capabilities":["os:linux","python:3"],"preferred_kinds":["codex_compute","local","other_compute","github_actions"],"forbidden_backend_ids":[],"required_backend_id":None,"max_registry_age_seconds":3600}
POL={"schema":"compute-cost-policy/v1","primary_kind":"codex_compute","kind_cost_weights":{"codex_compute":1,"local":1,"other_compute":5,"github_actions":100},"expensive_kinds":["github_actions"],"transient_failure_classes":["setup","network","provider","runtime"],"product_failure_classes":["product"],"bounded_primary_recovery_attempts":2,"probe_cooldown_seconds":900,"provider_outage_confirmation_required":True,"expensive_fallback_reasons":["required_capability","final_platform","artifact","release_attestation","confirmed_provider_outage"],"portable_wait_instead_of_expensive_fallback":True,"github_actions_requires_reason":True,"public_github_actions_unmetered":True,"public_github_actions_cost_weight":0}
CTX={"schema":"compute-cost-context/v1","evidence_class":"portable","primary_failure_class":"none","distinct_primary_recovery_attempts":0,"provider_outage_confirmed":False,"required_capability_gap_on_primary":False,"last_primary_failure_at_utc":None,"repository_visibility":"private"}

class T(unittest.TestCase):
 def route(self,reg=REG,req=REQ,ctx=CTX,now="2026-09-25T10:01:00Z"):return m.route(reg,req,POL,ctx,now)
 def test_codex_wins_over_expensive_actions(self):
  r=self.route();self.assertEqual(r["backend_id"],"codex");self.assertFalse(r["expensive_fallback"])
 def test_other_cheap_compute_wins_when_codex_degraded(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="degraded"
  r=self.route(reg=reg);self.assertEqual(r["backend_id"],"other");self.assertEqual(r["backend_kind"],"other_compute")
 def test_transient_codex_failure_does_not_fall_straight_to_actions(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="degraded";reg["backends"][1]["state"]="unavailable"
  ctx=copy.deepcopy(CTX);ctx.update(primary_failure_class="provider",last_primary_failure_at_utc="2026-09-25T09:40:00Z")
  r=self.route(reg=reg,ctx=ctx);self.assertEqual(r["action"],"probe_primary");self.assertEqual(r["backend_id"],"codex")
 def test_cooldown_waits_instead_of_spending_actions(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="degraded";reg["backends"][1]["state"]="unavailable"
  ctx=copy.deepcopy(CTX);ctx.update(primary_failure_class="setup",last_primary_failure_at_utc="2026-09-25T09:58:00Z")
  r=self.route(reg=reg,ctx=ctx);self.assertEqual(r["action"],"waiting_compute");self.assertEqual(r["reason"],"primary_probe_cooldown")
 def test_exhausted_recovery_without_confirmed_outage_waits(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="unavailable";reg["backends"][1]["state"]="unavailable"
  ctx=copy.deepcopy(CTX);ctx.update(primary_failure_class="provider",distinct_primary_recovery_attempts=2,last_primary_failure_at_utc="2026-09-25T09:40:00Z")
  r=self.route(reg=reg,ctx=ctx);self.assertEqual(r["action"],"waiting_compute");self.assertFalse(r["expensive_fallback"])
 def test_confirmed_provider_outage_can_use_actions(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="unavailable";reg["backends"][1]["state"]="unavailable"
  ctx=copy.deepcopy(CTX);ctx.update(primary_failure_class="provider",distinct_primary_recovery_attempts=2,provider_outage_confirmed=True,last_primary_failure_at_utc="2026-09-25T09:40:00Z")
  r=self.route(reg=reg,ctx=ctx);self.assertEqual(r["backend_id"],"gha");self.assertEqual(r["expensive_reason"],"confirmed_provider_outage")
 def test_required_platform_capability_can_use_actions(self):
  req=copy.deepcopy(REQ);req["required_capabilities"].append("feature:emulator")
  ctx=copy.deepcopy(CTX);ctx.update(evidence_class="platform",required_capability_gap_on_primary=True,primary_failure_class="incompatible")
  r=self.route(req=req,ctx=ctx);self.assertEqual(r["backend_id"],"gha");self.assertEqual(r["expensive_reason"],"final_platform")
 def test_product_failure_does_not_buy_second_opinion(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="degraded";reg["backends"][1]["state"]="unavailable"
  ctx=copy.deepcopy(CTX);ctx["primary_failure_class"]="product"
  r=self.route(reg=reg,ctx=ctx);self.assertEqual(r["reason"],"product_failure_requires_fix_before_more_compute");self.assertIsNone(r["backend_id"])
 def test_product_failure_blocks_even_when_all_backends_ready(self):
  ctx=copy.deepcopy(CTX);ctx["primary_failure_class"]="product"
  r=self.route(ctx=ctx);self.assertEqual(r["action"],"blocked");self.assertIsNone(r["backend_id"]);self.assertFalse(r["expensive_fallback"])
 def test_public_repo_actions_are_unmetered_and_can_win(self):
  ctx=copy.deepcopy(CTX);ctx["repository_visibility"]="public"
  r=self.route(ctx=ctx);self.assertEqual(r["backend_id"],"gha");self.assertFalse(r["expensive_fallback"]);self.assertIsNone(r["expensive_reason"])
 def test_public_repo_transient_codex_failure_uses_ready_actions_without_outage_proof(self):
  reg=copy.deepcopy(REG);reg["backends"][0]["state"]="degraded";reg["backends"][1]["state"]="unavailable"
  ctx=copy.deepcopy(CTX);ctx.update(repository_visibility="public",primary_failure_class="provider",last_primary_failure_at_utc="2026-09-25T09:58:00Z")
  r=self.route(reg=reg,ctx=ctx);self.assertEqual(r["backend_id"],"gha");self.assertFalse(r["expensive_fallback"])
 def test_invalid_visibility_is_rejected(self):
  ctx=copy.deepcopy(CTX);ctx["repository_visibility"]="secret"
  with self.assertRaises(ValueError): m.validate_context(ctx)
 def test_never_grants_authority(self):
  r=self.route()
  for k in ("authorizes_external_start","authorizes_product_write","authorizes_takeover","authorizes_scheduler_mutation"):self.assertFalse(r[k])

if __name__=="__main__":unittest.main()
