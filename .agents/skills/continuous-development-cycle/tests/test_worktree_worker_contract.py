from pathlib import Path
import copy,hashlib,json,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from worktree_worker_contract import assess
from parallel_task_planner import canonical_plan_ref

class T(unittest.TestCase):
 def base(self):return json.loads((ROOT/"templates"/"worktree-worker-contract.json").read_text())
 def rebind(self,d):
  d["plan_ref"]=canonical_plan_ref(d["plan"]);return d
 def _write(self,path,data):
  Path(path).write_text(json.dumps(data,indent=2)+"\n")
  return "sha256:"+hashlib.sha256(Path(path).read_bytes()).hexdigest()
 def _wave_record(self,root,d,wave,total_waves,base_sha,integrated_head,writer_result_shas,previous_integration=None):
  writer_result_shas=sorted(writer_result_shas)
  result={"schema":"integration-gate-result/v1","change_id":d["change_id"],"wave":wave,
          "total_waves":total_waves,"final_wave":False,"next_wave":wave+1,"plan_ref":d["plan_ref"],
          "shared_branch":d["shared_branch"],"expected_shared_head":base_sha,"observed_shared_head":base_sha,
          "writer_result_shas":writer_result_shas,"action":"READY_FOR_INTEGRATOR","ready":True,"blockers":[],
          "integrator_id":d["integrator_id"],"next_gate":"integrate_wave_then_contract_next_wave_on_fresh_head",
          "authorizes_shared_branch_write":False,"authorizes_force_push":False,"authorizes_merge":False,
          "authorizes_release":False,"authorizes_scope_expansion":False}
  result_path=Path(root)/f"wave-{wave}-gate-result.json";result_digest=self._write(result_path,result)
  gate={"schema":"wave-integration-gate-evidence/v1","change_id":d["change_id"],"plan_ref":d["plan_ref"],
        "wave":wave,"base_sha":base_sha,"shared_branch":d["shared_branch"],"ready":True,
        "evidence_ref":f"integration-gate:wave-{wave}-green",
        "result_artifact_ref":{"path":result_path.name,"sha256":result_digest}}
  gate_path=Path(root)/f"wave-{wave}-gate.json";gate_digest=self._write(gate_path,gate)
  assembly={"schema":"wave-assembly-evidence/v1","change_id":d["change_id"],"plan_ref":d["plan_ref"],
            "wave":wave,"base_sha":base_sha,"integrated_head":integrated_head,"shared_branch":d["shared_branch"],
            "gate_sha256":gate_digest,"writer_result_shas":writer_result_shas,"assembled":True,
            "evidence_ref":f"assembly:wave-{wave}@{integrated_head}"}
  assembly_path=Path(root)/f"wave-{wave}-assembly.json";assembly_digest=self._write(assembly_path,assembly)
  record={"schema":"wave-integration-record/v1","change_id":d["change_id"],"plan_ref":d["plan_ref"],
          "wave":wave,"base_sha":base_sha,"integrated_head":integrated_head,"shared_branch":d["shared_branch"],
          "writer_result_shas":writer_result_shas,
          "gate_artifact_ref":{"path":gate_path.name,"sha256":gate_digest},
          "assembly_artifact_ref":{"path":assembly_path.name,"sha256":assembly_digest},
          "previous_integration":previous_integration}
  record_path=Path(root)/f"wave-{wave}-integration.json";record_digest=self._write(record_path,record)
  return {"path":record_path.name,"sha256":record_digest}
 def later_wave_case(self,root,integrated_head=None,plan_base=None,writer_result_shas=None):
  d=self.base()
  if plan_base is not None:
   d["plan"]["base_sha"]=plan_base;d["base_sha"]=plan_base
   for a in d["assignments"]:a["base_sha"]=plan_base
  d["plan"]["tasks"][1]["write_paths"]=["src/model/sub"];self.rebind(d)
  prior_base=d["plan"]["base_sha"];d["wave"]=2;d["base_sha"]=integrated_head or "2"*40
  writer_result_shas=sorted(writer_result_shas or ["3"*40])
  gate_result={"schema":"integration-gate-result/v1","change_id":d["change_id"],"wave":1,
               "total_waves":2,"final_wave":False,"next_wave":2,"plan_ref":d["plan_ref"],
               "shared_branch":d["shared_branch"],"expected_shared_head":prior_base,"observed_shared_head":prior_base,
               "writer_result_shas":writer_result_shas,"action":"READY_FOR_INTEGRATOR","ready":True,"blockers":[],"integrator_id":d["integrator_id"],
               "next_gate":"integrate_wave_then_contract_next_wave_on_fresh_head",
               "authorizes_shared_branch_write":False,"authorizes_force_push":False,"authorizes_merge":False,
               "authorizes_release":False,"authorizes_scope_expansion":False}
  gate_result_path=Path(root)/"wave-1-gate-result.json";gate_result_digest=self._write(gate_result_path,gate_result)
  gate={"schema":"wave-integration-gate-evidence/v1","change_id":d["change_id"],"plan_ref":d["plan_ref"],
        "wave":1,"base_sha":prior_base,"shared_branch":d["shared_branch"],"ready":True,
        "evidence_ref":"integration-gate:wave-1-green",
        "result_artifact_ref":{"path":"wave-1-gate-result.json","sha256":gate_result_digest}}
  gate_path=Path(root)/"wave-1-gate.json";gate_digest=self._write(gate_path,gate)
  assembly={"schema":"wave-assembly-evidence/v1","change_id":d["change_id"],"plan_ref":d["plan_ref"],
            "wave":1,"base_sha":prior_base,"integrated_head":d["base_sha"],"shared_branch":d["shared_branch"],
            "gate_sha256":gate_digest,"writer_result_shas":writer_result_shas,"assembled":True,"evidence_ref":"assembly:wave-1@"+d["base_sha"]}
  assembly_path=Path(root)/"wave-1-assembly.json";assembly_digest=self._write(assembly_path,assembly)
  record={"schema":"wave-integration-record/v1","change_id":d["change_id"],"plan_ref":d["plan_ref"],
          "wave":1,"base_sha":prior_base,"integrated_head":d["base_sha"],"shared_branch":d["shared_branch"],
          "writer_result_shas":writer_result_shas,"gate_artifact_ref":{"path":"wave-1-gate.json","sha256":gate_digest},
          "assembly_artifact_ref":{"path":"wave-1-assembly.json","sha256":assembly_digest},
          "previous_integration":None}
  path=Path(root)/"wave-1-integration.json";digest=self._write(path,record)
  d["prior_wave_integration"]={"wave":1,"integrated_head":d["base_sha"],
                               "artifact_path":"wave-1-integration.json","artifact_sha256":digest}
  a=copy.deepcopy(d["assignments"][1]);a["base_sha"]=d["base_sha"];a["write_paths"]=["src/model/sub"];d["assignments"]=[a]
  return d,path,gate_path,assembly_path

 def test_template_isolated_and_non_authoritative(self):
  r=assess(self.base());self.assertTrue(r["valid"]);self.assertEqual(r["assignment_count"],2);self.assertEqual(r["wave"],1)
  self.assertFalse(r["authorizes_worker_launch"]);self.assertFalse(r["authorizes_shared_branch_write"])
 def test_same_wave_overlap_rejected(self):
  d=self.base();d["assignments"][1]["write_paths"]=["src/model/sub"]
  with self.assertRaises(ValueError):assess(d)
 def test_worker_shared_branch_write_rejected(self):
  d=self.base();d["assignments"][0]["can_write_shared_branch"]=True
  with self.assertRaises(ValueError):assess(d)
 def test_worker_branch_cannot_equal_shared(self):
  d=self.base();d["assignments"][0]["branch"]=d["shared_branch"]
  with self.assertRaises(ValueError):assess(d)
 def test_worker_branch_alias_cannot_equal_shared(self):
  d=self.base();d["shared_branch"]="refs/heads/feature/integration";d["plan"]["shared_branch"]="refs/heads/feature/integration"
  d["assignments"][0]["branch"]="feature/integration";self.rebind(d)
  with self.assertRaises(ValueError):assess(d)
 def test_stale_assignment_base_rejected(self):
  d=self.base();d["assignments"][0]["base_sha"]="2"*40
  with self.assertRaises(ValueError):assess(d)
 def test_first_wave_contract_base_must_match_plan(self):
  d=self.base();d["base_sha"]="2"*40
  for a in d["assignments"]:a["base_sha"]=d["base_sha"]
  with self.assertRaises(ValueError):assess(d)
 def test_assignment_must_match_plan_contract(self):
  d=self.base();d["assignments"][0]["expected_evidence"]=["test:other"]
  with self.assertRaises(ValueError):assess(d)
  d=self.base();d["assignments"][0]["expected_outputs"]=["commit:other"]
  with self.assertRaises(ValueError):assess(d)
  d=self.base();d["assignments"][0]["role"]="review";d["assignments"][0]["write_paths"]=[]
  with self.assertRaises(ValueError):assess(d)
 def test_backslash_write_path_rejected(self):
  d=self.base();d["plan"]["tasks"][0]["write_paths"]=["src\\model"];d["assignments"][0]["write_paths"]=["src\\model"]
  with self.assertRaises(ValueError):assess(d)
 def test_unsafe_write_path_rejected_even_if_plan_and_assignment_match(self):
  d=self.base();d["plan"]["tasks"][0]["write_paths"]=["../escape"];d["assignments"][0]["write_paths"]=["../escape"]
  with self.assertRaises(ValueError):assess(d)
 def test_review_assignment_can_be_read_only_when_plan_says_review(self):
  d=self.base()
  d["plan"]["tasks"]=[{"id":"review","role":"review","dependencies":[],"write_paths":[],"expected_outputs":["review:report"],"expected_evidence":["review:green"],"estimated_seconds":10}]
  d["assignments"]=[{"worker_id":"reviewer","task_id":"review","role":"review","branch":"review/check","worktree_id":"wt-review","base_sha":d["base_sha"],"write_paths":[],"expected_outputs":["review:report"],"expected_evidence":["review:green"],"can_write_shared_branch":False}]
  self.rebind(d);self.assertTrue(assess(d)["valid"])
 def test_case_only_writer_overlap_rejected(self):
  d=self.base();d["plan"]["tasks"][0]["write_paths"]=["src/UI"];d["plan"]["tasks"][1]["write_paths"]=["src/ui/sub"];self.rebind(d)
  with self.assertRaises(ValueError):assess(d)

 def test_later_wave_binds_authenticated_gate_and_assembly(self):
  with tempfile.TemporaryDirectory() as td:
   d,_,_,_=self.later_wave_case(td)
   r=assess(d,evidence_root=td);self.assertTrue(r["valid"]);self.assertEqual(r["base_sha"],"2"*40)
 def test_later_wave_requires_resolvable_prior_integration(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,_,_=self.later_wave_case(td)
   with self.assertRaises(ValueError):assess(d)
   d["prior_wave_integration"]["artifact_sha256"]="sha256:"+"0"*64
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_prior_gate_must_be_green_and_content_addressed(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,gate_path,assembly_path=self.later_wave_case(td)
   gate=json.loads(gate_path.read_text());gate["ready"]=False
   gate_digest=self._write(gate_path,gate)
   record=json.loads(path.read_text());record["gate_artifact_ref"]["sha256"]=gate_digest
   assembly=json.loads(assembly_path.read_text());assembly["gate_sha256"]=gate_digest
   record["assembly_artifact_ref"]["sha256"]=self._write(assembly_path,assembly)
   d["prior_wave_integration"]["artifact_sha256"]=self._write(path,record)
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_gate_result_artifact_digest_must_match(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,gate_path,assembly_path=self.later_wave_case(td)
   gate=json.loads(gate_path.read_text());gate["result_artifact_ref"]["sha256"]="sha256:"+"0"*64
   gate_digest=self._write(gate_path,gate)
   record=json.loads(path.read_text());record["gate_artifact_ref"]["sha256"]=gate_digest
   assembly=json.loads(assembly_path.read_text());assembly["gate_sha256"]=gate_digest
   record["assembly_artifact_ref"]["sha256"]=self._write(assembly_path,assembly)
   d["prior_wave_integration"]["artifact_sha256"]=self._write(path,record)
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_gate_result_must_be_green(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,gate_path,assembly_path=self.later_wave_case(td)
   result_path=Path(td)/"wave-1-gate-result.json"
   result=json.loads(result_path.read_text());result["ready"]=False;result["action"]="RECONCILE_OR_REPLAN";result["blockers"]=["stale"]
   result_digest=self._write(result_path,result)
   gate=json.loads(gate_path.read_text());gate["result_artifact_ref"]["sha256"]=result_digest
   gate_digest=self._write(gate_path,gate)
   record=json.loads(path.read_text());record["gate_artifact_ref"]["sha256"]=gate_digest
   assembly=json.loads(assembly_path.read_text());assembly["gate_sha256"]=gate_digest
   record["assembly_artifact_ref"]["sha256"]=self._write(assembly_path,assembly)
   d["prior_wave_integration"]["artifact_sha256"]=self._write(path,record)
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_assembly_must_bind_resolved_gate(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,_,assembly_path=self.later_wave_case(td)
   assembly=json.loads(assembly_path.read_text());assembly["gate_sha256"]="sha256:"+"f"*64
   record=json.loads(path.read_text());record["assembly_artifact_ref"]["sha256"]=self._write(assembly_path,assembly)
   d["prior_wave_integration"]["artifact_sha256"]=self._write(path,record)
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_assembly_writer_results_must_match_gate(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,_,assembly_path=self.later_wave_case(td)
   assembly=json.loads(assembly_path.read_text());assembly["writer_result_shas"]=["4"*40]
   record=json.loads(path.read_text());record["assembly_artifact_ref"]["sha256"]=self._write(assembly_path,assembly)
   d["prior_wave_integration"]["artifact_sha256"]=self._write(path,record)
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_prior_integration_must_advance_head(self):
  with tempfile.TemporaryDirectory() as td:
   d,path,_,assembly_path=self.later_wave_case(td,integrated_head="1"*40)
   with self.assertRaises(ValueError):assess(d,evidence_root=td)
 def test_live_prior_integration_must_match_shared_branch_and_ancestry(self):
  with tempfile.TemporaryDirectory() as td:
   repo=Path(td)/"repo";repo.mkdir()
   subprocess.check_call(["git","init","-q",str(repo)])
   subprocess.check_call(["git","-C",str(repo),"config","user.email","test@example.invalid"])
   subprocess.check_call(["git","-C",str(repo),"config","user.name","CDC Test"])
   (repo/"base.txt").write_text("base\n");subprocess.check_call(["git","-C",str(repo),"add","."]);subprocess.check_call(["git","-C",str(repo),"commit","-q","-m","base"])
   base=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
   (repo/"worker.txt").write_text("worker\n");subprocess.check_call(["git","-C",str(repo),"add","."]);subprocess.check_call(["git","-C",str(repo),"commit","-q","-m","worker"])
   worker_result=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
   (repo/"integrated.txt").write_text("integrated\n");subprocess.check_call(["git","-C",str(repo),"add","."]);subprocess.check_call(["git","-C",str(repo),"commit","-q","-m","integrated"])
   integrated=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
   subprocess.check_call(["git","-C",str(repo),"branch","feature/integration",integrated])
   evidence=Path(td)/"evidence";evidence.mkdir()
   d,_,_,_=self.later_wave_case(evidence,integrated_head=integrated,plan_base=base,writer_result_shas=[worker_result])
   self.assertTrue(assess(d,evidence_root=evidence,git_worktree=repo)["valid"])
   base_tree=subprocess.check_output(["git","-C",str(repo),"rev-parse",base+"^{tree}"],text=True).strip()
   unrelated=subprocess.check_output(["git","-C",str(repo),"commit-tree",base_tree],input="unrelated\n",text=True).strip()
   bad_evidence=Path(td)/"bad-evidence";bad_evidence.mkdir()
   bad,_,_,_=self.later_wave_case(bad_evidence,integrated_head=integrated,plan_base=base,writer_result_shas=[unrelated])
   with self.assertRaises(ValueError):assess(bad,evidence_root=bad_evidence,git_worktree=repo)
   subprocess.check_call(["git","-C",str(repo),"branch","-f","feature/integration",base])
   with self.assertRaises(ValueError):assess(d,evidence_root=evidence,git_worktree=repo)

 def test_three_wave_recursive_chain_is_live_verified(self):
  with tempfile.TemporaryDirectory() as td:
   repo=Path(td)/"repo";repo.mkdir()
   subprocess.check_call(["git","init","-q",str(repo)])
   subprocess.check_call(["git","-C",str(repo),"config","user.email","test@example.invalid"])
   subprocess.check_call(["git","-C",str(repo),"config","user.name","CDC Test"])
   def commit(name):
    (repo/(name+".txt")).write_text(name+"\n")
    subprocess.check_call(["git","-C",str(repo),"add","."])
    subprocess.check_call(["git","-C",str(repo),"commit","-q","-m",name])
    return subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
   base=commit("base")
   wave1_writer=commit("wave1-writer");wave1_head=commit("wave1-integrated")
   wave2_writer=commit("wave2-writer");wave2_head=commit("wave2-integrated")
   subprocess.check_call(["git","-C",str(repo),"branch","feature/integration",wave2_head])
   d=self.base()
   d["plan"]["base_sha"]=base
   d["plan"]["tasks"][0]["dependencies"]=[]
   d["plan"]["tasks"][1]["dependencies"]=["task-model"]
   d["plan"]["tasks"].append({"id":"task-tail","role":"writer","dependencies":["task-ui"],"write_paths":["src/tail"],
                              "expected_outputs":["commit:tail"],"expected_evidence":["test:tail-green"],"estimated_seconds":30})
   self.rebind(d);d["wave"]=3;d["base_sha"]=wave2_head
   d["assignments"]=[{"worker_id":"worker-tail","task_id":"task-tail","role":"writer","branch":"worker/tail",
                      "worktree_id":"wt-tail","base_sha":wave2_head,"write_paths":["src/tail"],
                      "expected_outputs":["commit:tail"],"expected_evidence":["test:tail-green"],
                      "can_write_shared_branch":False}]
   evidence=Path(td)/"evidence";evidence.mkdir()
   wave1_ref=self._wave_record(evidence,d,1,3,base,wave1_head,[wave1_writer])
   wave2_ref=self._wave_record(evidence,d,2,3,wave1_head,wave2_head,[wave2_writer],wave1_ref)
   d["prior_wave_integration"]={"wave":2,"integrated_head":wave2_head,
                                "artifact_path":wave2_ref["path"],"artifact_sha256":wave2_ref["sha256"]}
   self.assertTrue(assess(d,evidence_root=evidence,git_worktree=repo)["valid"])
   base_tree=subprocess.check_output(["git","-C",str(repo),"rev-parse",base+"^{tree}"],text=True).strip()
   unrelated=subprocess.check_output(["git","-C",str(repo),"commit-tree",base_tree,"-p",base],
                                     input="unrelated-wave1-writer\n",text=True).strip()
   bad_evidence=Path(td)/"bad-evidence";bad_evidence.mkdir()
   bad_wave1_ref=self._wave_record(bad_evidence,d,1,3,base,wave1_head,[unrelated])
   bad_wave2_ref=self._wave_record(bad_evidence,d,2,3,wave1_head,wave2_head,[wave2_writer],bad_wave1_ref)
   bad=copy.deepcopy(d)
   bad["prior_wave_integration"]={"wave":2,"integrated_head":wave2_head,
                                  "artifact_path":bad_wave2_ref["path"],"artifact_sha256":bad_wave2_ref["sha256"]}
   with self.assertRaises(ValueError):assess(bad,evidence_root=bad_evidence,git_worktree=repo)

 def test_windows_reserved_or_drive_relative_path_rejected(self):
  for bad in ("C:temp","src/CON","src/com1.txt","src/name.","src/name "):
   d=self.base();d["plan"]["tasks"][0]["write_paths"]=[bad];d["assignments"][0]["write_paths"]=[bad]
   with self.subTest(path=bad):
    with self.assertRaises(ValueError):assess(d)
 def test_embedded_plan_must_match_plan_digest(self):
  d=self.base();d["plan"]["tasks"][0]["expected_outputs"]=["commit:tampered"];d["assignments"][0]["expected_outputs"]=["commit:tampered"]
  with self.assertRaises(ValueError):assess(d)
 def test_assignment_set_must_equal_planned_wave(self):
  d=self.base();d["assignments"]=d["assignments"][:1]
  with self.assertRaises(ValueError):assess(d)
if __name__=="__main__":unittest.main()
