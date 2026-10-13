from pathlib import Path
import hashlib,json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from parallel_benchmark import evaluate,evaluate_from_files,load_observations,load_plan_artifact,load_environment_artifact

class T(unittest.TestCase):
 def base(self):return json.loads((ROOT/"templates"/"parallel-benchmark.json").read_text())
 def fixture_obs(self,d=None):return load_observations(d or self.base(),ROOT)
 def release_case(self):
  d=self.base();d["evidence_class"]="release_observed";obs=self.fixture_obs(d)
  for x in obs:x["observed"]=True
  return d,obs
 def test_package_template_is_fixture_only(self):
  d=self.base();r=evaluate_from_files(d,ROOT)
  self.assertTrue(r["passed"]);self.assertEqual(r["evidence_class"],"fixture")
  self.assertFalse(r["release_evidence_eligible"])
  self.assertTrue(all(x["observed"] is False for x in self.fixture_obs(d)))
  self.assertFalse(r["authorizes_worker_launch"]);self.assertFalse(r["authorizes_release"])
 def test_release_observed_requires_resolved_plan_artifact(self):
  d,obs=self.release_case();r=evaluate(d,obs)
  self.assertTrue(r["passed"]);self.assertFalse(r["release_evidence_eligible"]);self.assertFalse(r["plan_artifact_verified"]);self.assertFalse(r["environment_artifact_verified"])
  plan=load_plan_artifact(d,ROOT);r=evaluate(d,obs,plan_artifact=plan)
  self.assertTrue(r["passed"]);self.assertFalse(r["release_evidence_eligible"]);self.assertTrue(r["plan_artifact_verified"]);self.assertFalse(r["environment_artifact_verified"])
  environment=load_environment_artifact(d,ROOT);r=evaluate(d,obs,plan_artifact=plan,environment_artifact=environment)
  self.assertTrue(r["passed"]);self.assertTrue(r["release_evidence_eligible"]);self.assertTrue(r["environment_artifact_verified"])
 def test_invalid_evidence_class_rejected(self):
  d=self.base();d["evidence_class"]="pretend"
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_fixture_cannot_claim_observed(self):
  d=self.base();obs=self.fixture_obs(d);obs[0]["observed"]=True
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_release_evidence_must_be_observed(self):
  d,obs=self.release_case();obs[0]["observed"]=False
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_candidate_sha_required(self):
  d=self.base();d["candidate_sha"]="not-a-sha"
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_observation_digest_mismatch_rejected(self):
  d=self.base();d["observation_refs"][0]["sha256"]="sha256:"+"0"*64
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_missing_or_unsafe_observation_path_rejected(self):
  d=self.base();d["observation_refs"][0]["path"]="templates/missing.json"
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
  d=self.base();d["observation_refs"][0]["path"]="../escape.json"
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_benchmark_plan_ref_requires_digest(self):
  d=self.base();d["plan_ref"]="unbound-plan"
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_plan_artifact_bytes_must_match_plan_ref(self):
  d=self.base();fake="sha256:"+"2"*64;d["plan_ref"]=fake;d["plan_artifact_ref"]["sha256"]=fake
  for x in d["observation_refs"]: pass
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_environment_artifact_digest_mismatch_rejected(self):
  d=self.base();d["environment_artifact_ref"]["sha256"]="sha256:"+"0"*64
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_missing_or_unsafe_environment_artifact_rejected(self):
  d=self.base();d["environment_ref"]="templates/missing-environment.json";d["environment_artifact_ref"]["path"]=d["environment_ref"]
  for x in d["observation_refs"]:x["environment_ref"]=d["environment_ref"]
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
  d=self.base();d["environment_ref"]="../escape.json";d["environment_artifact_ref"]["path"]=d["environment_ref"]
  for x in d["observation_refs"]:x["environment_ref"]=d["environment_ref"]
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_environment_candidate_must_match_benchmark_target(self):
  d=self.base()
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);path=root/d["environment_ref"];path.parent.mkdir(parents=True)
   env=json.loads((ROOT/d["environment_ref"]).read_text());env["candidate_source_commit"]="3"*40
   payload=json.dumps(env,indent=2)+"\n";path.write_text(payload);d["environment_artifact_ref"]["sha256"]="sha256:"+hashlib.sha256(payload.encode()).hexdigest()
   with self.assertRaises(ValueError):load_environment_artifact(d,root)
 def test_environment_package_tree_must_match_benchmark_target(self):
  d=self.base()
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);path=root/d["environment_ref"];path.parent.mkdir(parents=True)
   env=json.loads((ROOT/d["environment_ref"]).read_text());env["package_tree"]="3"*40
   payload=json.dumps(env,indent=2)+"\n";path.write_text(payload);d["environment_artifact_ref"]["sha256"]="sha256:"+hashlib.sha256(payload.encode()).hexdigest()
   with self.assertRaises(ValueError):load_environment_artifact(d,root)
 def test_environment_runtime_fields_are_fail_closed(self):
  for field,bad in (("reported_processing_units",0),("timer","time.time()")):
   d=self.base()
   with tempfile.TemporaryDirectory() as td:
    root=Path(td);path=root/d["environment_ref"];path.parent.mkdir(parents=True)
    env=json.loads((ROOT/d["environment_ref"]).read_text());env[field]=bad
    payload=json.dumps(env,indent=2)+"\n";path.write_text(payload);d["environment_artifact_ref"]["sha256"]="sha256:"+hashlib.sha256(payload.encode()).hexdigest()
    with self.subTest(field=field):
     with self.assertRaises(ValueError):load_environment_artifact(d,root)
 def test_observation_plan_ref_requires_digest(self):
  d,obs=self.release_case();obs[0]["plan_ref"]="unbound-plan"
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_plan_candidate_must_match_benchmark_target(self):
  d=self.base();d["candidate_sha"]="3"*40
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_plan_package_tree_must_match_benchmark_target(self):
  d=self.base();d["package_tree"]="3"*40
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_plan_representative_task_must_match(self):
  d=self.base();d["representative_task_ref"]="other-task"
  with self.assertRaises(ValueError):evaluate_from_files(d,ROOT)
 def test_observation_candidate_must_match(self):
  d,obs=self.release_case();obs[0]["candidate_sha"]="2"*40
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_observation_environment_must_match(self):
  d,obs=self.release_case();obs[0]["environment_ref"]="other:env"
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_observation_plan_must_match(self):
  d,obs=self.release_case();obs[0]["plan_ref"]="sha256:"+"2"*64
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_workload_fingerprint_must_match(self):
  d,obs=self.release_case();obs[1]["workload_fingerprint"]="sha256:"+"2"*64
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_duplicate_evidence_ref_rejected(self):
  d,obs=self.release_case();obs[1]["evidence_ref"]=obs[0]["evidence_ref"]
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_both_modes_required(self):
  d,obs=self.release_case();obs[1]["mode"]="sequential"
  with self.assertRaises(ValueError):evaluate(d,obs)
 def test_nonfinite_timing_rejected(self):
  for bad in (float("nan"),float("inf"),float("-inf")):
   d,obs=self.release_case();obs[0]["elapsed_seconds"]=bad
   with self.subTest(value=bad):
    with self.assertRaises(ValueError):evaluate(d,obs)
 def test_slower_parallel_run_fails(self):
  d,obs=self.release_case();obs[1]["elapsed_seconds"]=obs[0]["elapsed_seconds"]
  self.assertIn("no_wall_clock_improvement",evaluate(d,obs)["blockers"])
 def test_conflict_regression_fails(self):
  d,obs=self.release_case();obs[1]["unresolved_conflicts"]=obs[0]["unresolved_conflicts"]+1
  self.assertIn("conflict_rate_regressed",evaluate(d,obs)["blockers"])
 def test_rollback_regression_fails(self):
  d,obs=self.release_case();obs[1]["rollbacks"]=obs[0]["rollbacks"]+1
  self.assertIn("rollback_rate_regressed",evaluate(d,obs)["blockers"])
 def test_observation_outcome_counts_must_be_non_negative_integers(self):
  for field in ("unresolved_conflicts","rollbacks"):
   for bad in (-1,1.5,True,"1",None):
    d,obs=self.release_case();obs[1][field]=bad
    with self.subTest(field=field,value=bad):
     with self.assertRaises(ValueError):evaluate(d,obs)
if __name__=="__main__":unittest.main()
