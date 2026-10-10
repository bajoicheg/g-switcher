import unittest
from execution_channel_supervisor import supervise
NOW="2026-01-01T00:00:01Z"
REG={"schema":"backend-capability-registry/v1","observed_at_utc":"2026-01-01T00:00:00Z","backends":[
 {"backend_id":"codex","kind":"codex_compute","enabled":True,"state":"ready","rank":10,"capabilities":["os:linux"],"configuration_digest":"sha256:"+"1"*64,"last_verified_at_utc":"2026-01-01T00:00:00Z","evidence_refs":["env:codex"]},
 {"backend_id":"actions","kind":"github_actions","enabled":True,"state":"ready","rank":20,"capabilities":["os:linux"],"configuration_digest":"sha256:"+"2"*64,"last_verified_at_utc":"2026-01-01T00:00:00Z","evidence_refs":["workflow:ci"]}]}
REQ={"schema":"capability-request/v1","task_id":"t","candidate_sha":"a"*40,"required_capabilities":["os:linux"],"preferred_kinds":["codex_compute","github_actions"],"forbidden_backend_ids":[],"required_backend_id":None,"max_registry_age_seconds":900}
POL={"schema":"compute-cost-policy/v1","primary_kind":"codex_compute","kind_cost_weights":{"codex_compute":1,"local":2,"other_compute":3,"github_actions":5},"expensive_kinds":["github_actions"],"transient_failure_classes":["setup","network","provider","runtime"],"product_failure_classes":["product"],"bounded_primary_recovery_attempts":2,"probe_cooldown_seconds":60,"provider_outage_confirmation_required":True,"expensive_fallback_reasons":["required_capability","final_platform","artifact","release_attestation","confirmed_provider_outage"],"portable_wait_instead_of_expensive_fallback":True,"github_actions_requires_reason":True,"public_github_actions_unmetered":True,"public_github_actions_cost_weight":0}
CTX={"schema":"compute-cost-context/v1","evidence_class":"portable","primary_failure_class":"none","distinct_primary_recovery_attempts":0,"provider_outage_confirmed":False,"required_capability_gap_on_primary":False,"last_primary_failure_at_utc":None,"repository_visibility":"public"}
class Tests(unittest.TestCase):
 def test_routes_fresh_backend(self):
  s={"schema":"channel-supervision/v1","attempted_backend_ids":[],"failure_classes":{},"max_failovers":3}
  r=supervise(REG,REQ,POL,CTX,s,NOW);self.assertEqual(r["action"],"ROUTE")
 def test_failed_primary_fails_over_same_invocation(self):
  s={"schema":"channel-supervision/v1","attempted_backend_ids":["codex"],"failure_classes":{"codex":"provider"},"max_failovers":3}
  r=supervise(REG,REQ,POL,CTX,s,NOW);self.assertEqual(r["backend_id"],"actions")
 def test_product_failure_does_not_buy_second_opinion(self):
  s={"schema":"channel-supervision/v1","attempted_backend_ids":["codex"],"failure_classes":{"codex":"product"},"max_failovers":3}
  r=supervise(REG,REQ,POL,CTX,s,NOW);self.assertEqual(r["reason"],"product_failure_requires_fix")
 def test_failover_budget_is_bounded(self):
  s={"schema":"channel-supervision/v1","attempted_backend_ids":["codex","actions"],"failure_classes":{"codex":"provider","actions":"runtime"},"max_failovers":1}
  self.assertEqual(supervise(REG,REQ,POL,CTX,s,NOW)["reason"],"failover_budget_exhausted")
if __name__=="__main__":unittest.main()
