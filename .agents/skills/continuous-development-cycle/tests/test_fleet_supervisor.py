import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import fleet_supervisor as m
R={"schema":"fleet-registry/v1","target":{"schema":"version-convergence-target/v1","target_version":"2.6.0","target_package_fingerprint":"git-tree:"+"a"*40,"checkpoint_schema":"development-work-status/v4","safe_boundary_required":True},"slo_policy":{"schema":"progress-slo-policy/v1","degraded_after_seconds":1200,"stalled_after_seconds":3600,"blocked_pauses_clock":True,"waiting_external_pauses_clock":True,"primitive_activity_is_progress":False},"assessment_max_age_seconds":900,"projects":[{"repository":"o/r","source_ref":"refs/heads/main","watchdog_id":"w1","required":True}]}
def snap():
 return {"schema":"fleet-project-snapshot/v1","repository":"o/r","source_ref":"refs/heads/main","observed_at_utc":"2026-01-01T00:10:00Z","product_head":"a"*40,"cdc_version":"2.6.0","package_fingerprint":"git-tree:"+"a"*40,"checkpoint_schema":"development-work-status/v4","policy_revision":"p","watchdog":{"enabled":True,"last_run_at_utc":"2026-01-01T00:09:00Z"},"coordination":{"lease_schema":"execution-lease/v2","generation":1,"owner_active":False,"guard_present":False},"progress":{"schema":"progress-observation/v1","observed_at_utc":"2026-01-01T00:10:00Z","last_meaningful_progress_at_utc":"2026-01-01T00:05:00Z","last_activity_at_utc":"2026-01-01T00:09:30Z","primitive_steps_since_progress":2,"blocker":False,"waiting_external":False,"phase":"implementation","evidence_refs":["git:x"]}}
class T(unittest.TestCase):
 def test_healthy(self):self.assertEqual(m.assess_fleet(R,[snap()],"2026-01-01T00:11:00Z")["overall"],"HEALTHY")
 def test_disabled_watchdog_requires_recovery(self):s=snap();s["watchdog"]["enabled"]=False;self.assertEqual(m.assess_fleet(R,[s],"2026-01-01T00:11:00Z")["overall"],"RECOVERY_REQUIRED")
 def test_lagging_active_waits_safe_boundary(self):s=snap();s["cdc_version"]="2.5.0";s["coordination"]["owner_active"]=True;r=m.assess_fleet(R,[s],"2026-01-01T00:11:00Z");self.assertIn("wait_safe_boundary",r["projects"][0]["recommended_actions"])
 def test_no_authority(self):r=m.assess_fleet(R,[snap()],"2026-01-01T00:11:00Z");self.assertFalse(r["authorizes_product_write"]);self.assertFalse(r["authorizes_takeover"])
if __name__=="__main__":unittest.main()
