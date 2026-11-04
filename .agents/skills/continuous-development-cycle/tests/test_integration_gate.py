from pathlib import Path
import copy,json,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from integration_gate import evaluate,resolve_git_diff,verify_git_diff_proofs,main
from parallel_task_planner import canonical_plan_ref

class T(unittest.TestCase):
 def base(self):return json.loads((ROOT/"templates"/"integration-gate.json").read_text())
 def rebind_plan(self,d):
  d["worker_contract"]["plan_ref"]=canonical_plan_ref(d["worker_contract"]["plan"]);return d
 def drop_proof(self,d,task_id):
  d["diff_proofs"]=[p for p in d["diff_proofs"] if p["task_id"]!=task_id]
 def proof(self,d,task_id):
  return next(p for p in d["diff_proofs"] if p["task_id"]==task_id)
 def result(self,d,task_id):
  return next(r for r in d["worker_results"] if r["task_id"]==task_id)
 def test_ready_without_granting_shared_write(self):
  r=evaluate(self.base());self.assertTrue(r["ready"]);self.assertEqual(r["action"],"READY_FOR_INTEGRATOR");self.assertEqual(r["wave"],1)
  self.assertEqual(r["writer_result_shas"],["2"*40,"3"*40])
  self.assertTrue(r["final_wave"]);self.assertEqual(r["total_waves"],1);self.assertIsNone(r["next_wave"])
  self.assertEqual(r["next_gate"],"cdc_2.10.1_review_branch_finish_then_2.10.0_verification")
  self.assertFalse(r["authorizes_shared_branch_write"]);self.assertFalse(r["authorizes_merge"])
 def test_nonfinal_wave_routes_to_new_fresh_base_contract(self):
  d=self.base();d["worker_contract"]["plan"]["tasks"][1]["write_paths"]=["src/model/sub"];self.rebind_plan(d)
  d["worker_contract"]["assignments"]=d["worker_contract"]["assignments"][:1]
  d["worker_results"]=d["worker_results"][:1];d["diff_proofs"]=d["diff_proofs"][:1]
  r=evaluate(d);self.assertTrue(r["ready"]);self.assertFalse(r["final_wave"]);self.assertEqual(r["next_wave"],2)
  self.assertEqual(r["writer_result_shas"],["2"*40])
  self.assertEqual(r["next_gate"],"integrate_wave_then_contract_next_wave_on_fresh_head")
 def test_moved_shared_head_requires_reconcile(self):
  d=self.base();d["observed_shared_head"]="5"*40
  self.assertIn("shared_head_moved_reconcile_required",evaluate(d)["blockers"])
 def test_failed_worker_blocks(self):
  d=self.base();r=self.result(d,"task-model");r["state"]="failed";self.drop_proof(d,"task-model")
  self.assertIn("worker_not_success:task-model",evaluate(d)["blockers"])
 def test_failed_worker_can_report_failure_without_success_outputs(self):
  d=self.base();r=self.result(d,"task-model");r["state"]="failed";r["output_refs"]=[];r["evidence_refs"]=["failure:worker-log"];self.drop_proof(d,"task-model")
  self.assertIn("worker_not_success:task-model",evaluate(d)["blockers"])
 def test_missing_worker_result_blocks(self):
  d=self.base();d["worker_results"]=d["worker_results"][:1];d["diff_proofs"]=d["diff_proofs"][:1]
  self.assertIn("missing_worker_result:task-ui",evaluate(d)["blockers"])
 def test_result_identity_must_match_contract(self):
  d=self.base();d["worker_results"][0]["worker_id"]="other-worker"
  with self.assertRaises(ValueError):evaluate(d)
 def test_result_base_must_match_assignment(self):
  d=self.base();d["worker_results"][0]["base_sha"]="6"*40
  with self.assertRaises(ValueError):evaluate(d)
 def test_changed_path_must_stay_inside_assigned_write_set(self):
  d=self.base();d["worker_results"][0]["changed_paths"]=["src/ui/foreign.py"]
  with self.assertRaises(ValueError):evaluate(d)
 def test_changed_path_traversal_rejected(self):
  d=self.base();d["worker_results"][0]["changed_paths"]=["src/model/../ui/escape.py"]
  with self.assertRaises(ValueError):evaluate(d)
 def test_changed_path_backslash_rejected(self):
  d=self.base();d["worker_results"][0]["changed_paths"]=["src\\model\\escape.py"]
  with self.assertRaises(ValueError):evaluate(d)
 def test_windows_reserved_terminal_path_rejected(self):
  d=self.base();d["worker_results"][0]["changed_paths"]=["src/model/CON"]
  with self.assertRaises(ValueError):evaluate(d)
 def test_casefold_write_set_membership_is_portable(self):
  d=self.base()
  a=d["worker_contract"]["assignments"][0];t=d["worker_contract"]["plan"]["tasks"][0]
  a["write_paths"]=["src/Model"];t["write_paths"]=["src/Model"];self.rebind_plan(d)
  d["worker_results"][0]["changed_paths"]=["src/model/model.py"]
  d["diff_proofs"][0]["changed_paths"]=["src/model/model.py"]
  self.assertTrue(evaluate(d)["ready"])
 def test_casefold_terminal_aliases_rejected(self):
  d=self.base()
  d["worker_results"][0]["changed_paths"]=["src/model/Foo.py","src/model/foo.py"]
  d["diff_proofs"][0]["changed_paths"]=["src/model/Foo.py","src/model/foo.py"]
  with self.assertRaises(ValueError): evaluate(d)
 def test_unicode_terminal_aliases_rejected(self):
  d=self.base()
  d["worker_results"][0]["changed_paths"]=["src/model/caf\u00e9.py","src/model/cafe\u0301.py"]
  d["diff_proofs"][0]["changed_paths"]=["src/model/caf\u00e9.py","src/model/cafe\u0301.py"]
  with self.assertRaises(ValueError): evaluate(d)
 def test_git_diff_resolver_rejects_portable_aliases(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);subprocess.check_call(["git","init","-q",str(root)]);subprocess.check_call(["git","-C",str(root),"config","user.email","test@example.invalid"]);subprocess.check_call(["git","-C",str(root),"config","user.name","CDC Test"])
   (root/"src/model").mkdir(parents=True);(root/"src/model/base.py").write_text("base\n")
   subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","base"])
   base=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   (root/"src/model/Foo.py").write_text("a\n");(root/"src/model/foo.py").write_text("b\n")
   subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","aliases"])
   result=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   with self.assertRaises(ValueError): resolve_git_diff(root,worker_id="w",task_id="t",base_sha=base,result_sha=result,evidence_ref="git-diff:aliases")
 def test_force_push_never_allowed(self):
  d=self.base();d["force_push_requested"]=True
  r=evaluate(d);self.assertIn("force_push_forbidden",r["blockers"]);self.assertFalse(r["authorizes_force_push"])
 def test_unresolved_conflict_blocks(self):
  d=self.base();d["unresolved_conflicts"]=["src/model/model.py"]
  self.assertIn("unresolved_conflicts",evaluate(d)["blockers"])
 def test_contract_change_mismatch_rejected(self):
  d=self.base();d["worker_contract"]["change_id"]="other-change"
  with self.assertRaises(ValueError):evaluate(d)
 def test_missing_expected_evidence_rejected(self):
  d=self.base();d["worker_results"][0]["evidence_refs"]=["test:other"]
  with self.assertRaises(ValueError):evaluate(d)
 def test_missing_expected_output_rejected(self):
  d=self.base();d["worker_results"][0]["output_refs"]=["commit:other"]
  with self.assertRaises(ValueError):evaluate(d)
 def test_successful_writer_requires_change_and_new_sha(self):
  d=self.base();d["worker_results"][0]["changed_paths"]=[]
  with self.assertRaises(ValueError):evaluate(d)
  d=self.base();d["worker_results"][0]["result_sha"]=d["worker_results"][0]["base_sha"]
  with self.assertRaises(ValueError):evaluate(d)
 def _review_only(self,d,result_sha,changed_paths):
  plan=d["worker_contract"]["plan"];plan["tasks"]=[{"id":"review","role":"review","dependencies":[],"write_paths":[],"expected_outputs":["review:report"],"expected_evidence":["review:green"],"estimated_seconds":10}]
  a={"worker_id":"reviewer","task_id":"review","role":"review","branch":"review/check","worktree_id":"wt-review","base_sha":d["expected_shared_head"],"write_paths":[],"expected_outputs":["review:report"],"expected_evidence":["review:green"],"can_write_shared_branch":False}
  d["worker_contract"]["assignments"]=[a];self.rebind_plan(d)
  d["worker_results"]=[{"worker_id":"reviewer","task_id":"review","role":"review","base_sha":d["expected_shared_head"],"result_sha":result_sha,"state":"success","changed_paths":changed_paths,"output_refs":["review:report"],"evidence_refs":["review:green"]}]
  d["diff_proofs"]=[]
 def test_non_writer_success_must_keep_base_sha(self):
  d=self.base();self._review_only(d,"4"*40,[])
  with self.assertRaises(ValueError):evaluate(d)
 def test_non_writer_result_cannot_mutate(self):
  d=self.base();self._review_only(d,d["expected_shared_head"],["src/fix.py"])
  with self.assertRaises(ValueError):evaluate(d)
 def test_successful_writer_requires_exact_diff_proof(self):
  d=self.base();self.drop_proof(d,"task-model")
  with self.assertRaises(ValueError):evaluate(d)
  d=self.base();self.proof(d,"task-model")["changed_paths"]=["src/model/other.py"]
  with self.assertRaises(ValueError):evaluate(d)
  d=self.base();self.proof(d,"task-model")["result_sha"]="9"*40
  with self.assertRaises(ValueError):evaluate(d)
 def test_cli_requires_live_git_proof_for_successful_writers(self):
  self.assertEqual(main([str(ROOT/"templates"/"integration-gate.json")]),2)
 def test_cli_rejects_stale_observed_shared_head(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);subprocess.check_call(["git","init","-q",str(root)]);subprocess.check_call(["git","-C",str(root),"config","user.email","test@example.invalid"]);subprocess.check_call(["git","-C",str(root),"config","user.name","CDC Test"])
   (root/"src/model").mkdir(parents=True);(root/"src/model/model.py").write_text("base\n")
   subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","base"])
   base=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   subprocess.check_call(["git","-C",str(root),"branch","feature/integration",base])
   subprocess.check_call(["git","-C",str(root),"checkout","-q","-b","worker/model",base])
   (root/"src/model/model.py").write_text("worker\n");subprocess.check_call(["git","-C",str(root),"commit","-qam","worker"])
   result=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   subprocess.check_call(["git","-C",str(root),"checkout","-q","feature/integration"])
   (root/"shared.txt").write_text("advanced\n");subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","advance shared"])
   live=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip();self.assertNotEqual(live,base)
   d=self.base();d["shared_branch"]="feature/integration";d["expected_shared_head"]=base;d["observed_shared_head"]=base
   wc=d["worker_contract"];wc["shared_branch"]="feature/integration";wc["base_sha"]=base;wc["plan"]["shared_branch"]="feature/integration";wc["plan"]["base_sha"]=base;wc["plan"]["tasks"]=wc["plan"]["tasks"][:1];self.rebind_plan(d);wc["assignments"]=wc["assignments"][:1];wc["assignments"][0]["base_sha"]=base
   r=d["worker_results"][0];d["worker_results"]=[r];r["base_sha"]=base;r["result_sha"]=result;r["changed_paths"]=["src/model/model.py"]
   d["diff_proofs"]=[resolve_git_diff(root,worker_id=r["worker_id"],task_id=r["task_id"],base_sha=base,result_sha=result,evidence_ref="git-diff:live-head")]
   p=root/"gate.json";p.write_text(json.dumps(d))
   self.assertEqual(main([str(p),"--git-worktree",str(root)]),2)
 def test_cli_review_only_wave_rejects_stale_live_shared_head(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);subprocess.check_call(["git","init","-q",str(root)]);subprocess.check_call(["git","-C",str(root),"config","user.email","test@example.invalid"]);subprocess.check_call(["git","-C",str(root),"config","user.name","CDC Test"])
   (root/"base.txt").write_text("base\n");subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","base"]);subprocess.check_call(["git","-C",str(root),"branch","-M","feature/integration"])
   base=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   d=self.base();d["shared_branch"]="feature/integration";d["expected_shared_head"]=base;d["observed_shared_head"]=base
   wc=d["worker_contract"];wc["shared_branch"]="feature/integration";wc["base_sha"]=base;wc["plan"]["shared_branch"]="feature/integration";wc["plan"]["base_sha"]=base
   self._review_only(d,base,[])
   (root/"advance.txt").write_text("advanced\n");subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","advance shared"])
   self.assertNotEqual(subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip(),base)
   p=root/"gate.json";p.write_text(json.dumps(d))
   self.assertEqual(main([str(p),"--git-worktree",str(root)]),2)
 def test_cli_proves_assigned_registered_worker_worktree(self):
  with tempfile.TemporaryDirectory() as td:
   parent=Path(td);root=parent/"repo";worker=parent/"wt-model"
   subprocess.check_call(["git","init","-q",str(root)]);subprocess.check_call(["git","-C",str(root),"config","user.email","test@example.invalid"]);subprocess.check_call(["git","-C",str(root),"config","user.name","CDC Test"])
   (root/"src/model").mkdir(parents=True);(root/"src/model/model.py").write_text("base\n")
   subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","base"]);subprocess.check_call(["git","-C",str(root),"branch","-M","feature/integration"])
   base=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   subprocess.check_call(["git","-C",str(root),"worktree","add","-q","-b","worker/model",str(worker),base])
   (worker/"src/model/model.py").write_text("worker\n");subprocess.check_call(["git","-C",str(worker),"commit","-qam","worker"])
   result=subprocess.check_output(["git","-C",str(worker),"rev-parse","HEAD"],text=True).strip()
   d=self.base();d["shared_branch"]="feature/integration";d["expected_shared_head"]=base;d["observed_shared_head"]=base
   wc=d["worker_contract"];wc["shared_branch"]="feature/integration";wc["base_sha"]=base;wc["plan"]["shared_branch"]="feature/integration";wc["plan"]["base_sha"]=base;wc["plan"]["tasks"]=wc["plan"]["tasks"][:1];self.rebind_plan(d);wc["assignments"]=wc["assignments"][:1]
   a=wc["assignments"][0];a["branch"]="worker/model";a["worktree_id"]="wt-model";a["base_sha"]=base
   r=d["worker_results"][0];d["worker_results"]=[r];r["base_sha"]=base;r["result_sha"]=result;r["changed_paths"]=["src/model/model.py"]
   d["diff_proofs"]=[resolve_git_diff(root,worker_id=r["worker_id"],task_id=r["task_id"],base_sha=base,result_sha=result,evidence_ref="git-diff:origin")]
   p=parent/"gate.json";p.write_text(json.dumps(d))
   self.assertEqual(main([str(p),"--git-worktree",str(root),"--worker-worktree",f"wt-model={worker}"]),0)
   self.assertEqual(main([str(p),"--git-worktree",str(root),"--worker-worktree",f"wt-model={root}"]),2)
 def test_git_diff_resolver_rejects_unrelated_result_history(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);subprocess.check_call(["git","init","-q",str(root)]);subprocess.check_call(["git","-C",str(root),"config","user.email","test@example.invalid"]);subprocess.check_call(["git","-C",str(root),"config","user.name","CDC Test"])
   (root/"base.txt").write_text("base\n");subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","base"])
   base=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   subprocess.check_call(["git","-C",str(root),"checkout","--orphan","other"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   subprocess.check_call(["git","-C",str(root),"rm","-rf","."],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   (root/"src").mkdir();(root/"src/result.py").write_text("x=1\n");subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","unrelated"])
   result=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   with self.assertRaises(ValueError):resolve_git_diff(root,worker_id="w",task_id="t",base_sha=base,result_sha=result,evidence_ref="git-diff:unrelated")
 def test_git_diff_resolver_observes_complete_diff(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);subprocess.check_call(["git","init","-q",str(root)]);subprocess.check_call(["git","-C",str(root),"config","user.email","test@example.invalid"]);subprocess.check_call(["git","-C",str(root),"config","user.name","CDC Test"])
   (root/"src/model").mkdir(parents=True);(root/"src/model/model.py").write_text("one\n")
   subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","base"])
   base=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   (root/"src/model/model.py").write_text("two\n");(root/"src/model/new.py").write_text("new\n")
   subprocess.check_call(["git","-C",str(root),"add","."]);subprocess.check_call(["git","-C",str(root),"commit","-q","-m","result"])
   result=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
   d=self.base();d["expected_shared_head"]=base;d["observed_shared_head"]=base;d["worker_contract"]["base_sha"]=base;d["worker_contract"]["plan"]["base_sha"]=base
   d["worker_contract"]["plan"]["tasks"]=d["worker_contract"]["plan"]["tasks"][:1];self.rebind_plan(d);d["worker_contract"]["assignments"]=d["worker_contract"]["assignments"][:1];d["worker_contract"]["assignments"][0]["base_sha"]=base
   r=d["worker_results"][0];d["worker_results"]=[r];r["base_sha"]=base;r["result_sha"]=result;r["changed_paths"]=["src/model/model.py","src/model/new.py"]
   d["diff_proofs"]=[resolve_git_diff(root,worker_id=r["worker_id"],task_id=r["task_id"],base_sha=base,result_sha=result,evidence_ref="git-diff:test")]
   self.assertTrue(verify_git_diff_proofs(d,root));self.assertTrue(evaluate(d)["ready"])
if __name__=="__main__":unittest.main()
