import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import managed_executor_pool as m

FAKE_BASE="a"*40

def plan(base=FAKE_BASE):
 return {
  "schema":"managed-executor-pool-plan/v1","pool_id":"p","change_id":"c",
  "parent_invocation_id":"parent","base_sha":base,"integrator_id":"integrator",
  "coordination_ref":"refs/heads/cdc/pool-p",
  "coordination_store_id":"sha256:"+"1"*64,
  "max_parallel":2,"total_runtime_budget_seconds":1000,"total_cost_budget_units":100,
  "tasks":[
   {"id":"a","role":"writer","required":True,"dependencies":[],"executor_id":"exec-a",
    "branch":"worker-a","worktree":"worktrees/a","write_paths":["src/a"],
    "expected_outputs":["out:a"],"expected_evidence":["test:a"],"backend_preferences":["codex_compute"],
    "max_runtime_seconds":300,"max_cost_units":30},
   {"id":"b","role":"writer","required":True,"dependencies":[],"executor_id":"exec-b",
    "branch":"worker-b","worktree":"worktrees/b","write_paths":["src/b"],
    "expected_outputs":["out:b"],"expected_evidence":["test:b"],"backend_preferences":["codex_compute"],
    "max_runtime_seconds":300,"max_cost_units":30},
   {"id":"review","role":"review","required":True,"dependencies":["a","b"],"executor_id":"reviewer",
    "branch":None,"worktree":None,"write_paths":[],
    "expected_outputs":["out:review"],"expected_evidence":["review:green"],"backend_preferences":["codex_compute"],
    "max_runtime_seconds":200,"max_cost_units":20},
  ]}

class FakeCasStore:
 def __init__(self,state):
  self.revision="store-0";self.state=copy.deepcopy(state);self.counter=0
 def read(self):
  return self.revision,copy.deepcopy(self.state)
 def compare_and_swap(self,expected,new_state):
  if expected!=self.revision:raise ValueError("stale store revision")
  self.counter+=1;self.revision=f"store-{self.counter}";self.state=copy.deepcopy(new_state)
  return self.revision

class T(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.repo=Path(self.tmp.name)
  def git(*args):
   return subprocess.check_output(["git","-C",str(self.repo),*args],text=True).strip()
  self.git=git
  git("init","-q");git("config","user.email","cdc@example.invalid");git("config","user.name","CDC Test")
  (self.repo/"seed").write_text("base");git("add","seed");git("commit","-q","-m","base")
  self.base=git("rev-parse","HEAD")
  git("switch","-q","-c","worker-a")
  (self.repo/"src"/"a").mkdir(parents=True)
  (self.repo/"src"/"a"/"result.txt").write_text("a")
  git("add","src/a/result.txt");git("commit","-q","-m","a")
  self.result_a=git("rev-parse","HEAD")
  git("switch","-q","-c","worker-b",self.base)
  (self.repo/"src"/"b").mkdir(parents=True)
  (self.repo/"src"/"b"/"result.txt").write_text("b")
  git("add","src/b/result.txt");git("commit","-q","-m","b")
  self.result_b=git("rev-parse","HEAD")

 def tearDown(self):self.tmp.cleanup()

 def _task_state(self,s,task):
  return {x["id"]:x for x in s["tasks"]}[task]

 def _queue(self,p,s,task,attempt):
  token=f"reserve:{task}:{attempt}"
  return m.queue_task(p,s,task,attempt,expected_revision=s["revision"],reservation_token=token)

 def _run(self,p,s,task,attempt):
  token=self._task_state(s,task)["reservation_token"]
  return m.mark_running(p,s,task,attempt,expected_revision=s["revision"],reservation_token=token)

 def _fail(self,p,s,task,attempt,status):
  token=self._task_state(s,task)["reservation_token"]
  return m.fail_attempt(p,s,task,attempt,terminal_status=status,reservation_token=token,
                        expected_revision=s["revision"])

 def _accept(self,p,s,task,attempt,changed,outputs,evidence,runtime=10,cost=1,result_commit=None,
             executor_id=None):
  t={x["id"]:x for x in p["tasks"]}[task]
  if result_commit is None and t["role"]=="writer":result_commit=self.result_a if task=="a" else self.result_b
  token=self._task_state(s,task)["reservation_token"]
  return m.accept_result(
   p,s,task_id=task,attempt_id=attempt,result_ref=f"result:{task}:{attempt}",
   base_sha=p["base_sha"],executor_id=executor_id or t["executor_id"],
   parent_invocation_id=p["parent_invocation_id"],integrator_id=p["integrator_id"],
   branch=t["branch"],worktree=t["worktree"],reservation_token=token,result_commit=result_commit,
   changed_paths=changed,output_refs=outputs,evidence_refs=evidence,runtime_seconds=runtime,cost_units=cost,
   git_worktree=self.repo if t["role"]=="writer" else None,expected_revision=s["revision"])

 def _integrate(self,p,s,task,ref):
  return m.mark_integrated(p,s,task,ref,expected_revision=s["revision"])

 def test_parallel_dispatches_two_independent_writers_with_isolation_assignments(self):
  p=plan();s=m.initial_state(p,parallel_capable=True);r=m.dispatch(p,s)
  self.assertEqual(r["task_ids"],["a","b"])
  self.assertEqual([x["branch"] for x in r["assignments"]],["worker-a","worker-b"])
  self.assertEqual([x["worktree"] for x in r["assignments"]],["worktrees/a","worktrees/b"])
  self.assertEqual({x["base_sha"] for x in r["assignments"]},{FAKE_BASE})

 def test_sequential_fallback_dispatches_one_without_fabricating_parallel(self):
  p=plan();s=m.initial_state(p,parallel_capable=False);r=m.dispatch(p,s)
  self.assertEqual(r["task_ids"],["a"]);self.assertTrue(r["fallback_serialized"]);self.assertFalse(r["parallel_capable"])

 def test_overlapping_and_unicode_writer_paths_are_serialized(self):
  p=plan();p["tasks"][1]["write_paths"]=["src/A/sub"];s=m.initial_state(p,parallel_capable=True)
  self.assertEqual(m.dispatch(p,s)["task_ids"],["a"])
  p=plan();p["tasks"][0]["write_paths"]=["src/caf\u00e9"];p["tasks"][1]["write_paths"]=["src/cafe\u0301/x"]
  s=m.initial_state(p,parallel_capable=True);self.assertEqual(m.dispatch(p,s)["task_ids"],["a"])

 def test_dispatch_reserves_inflight_runtime_and_cost_budget(self):
  p=plan();p["total_runtime_budget_seconds"]=400;p["total_cost_budget_units"]=40
  s=m.initial_state(p,parallel_capable=True);r=m.dispatch(p,s)
  self.assertEqual(r["task_ids"],["a"]);self.assertEqual(r["reserved_runtime_seconds"],300);self.assertEqual(r["reserved_cost_units"],30)

 def test_queue_requires_current_state_revision_and_reservation(self):
  p=plan();s=m.initial_state(p,parallel_capable=True)
  s2=self._queue(p,s,"a","a1")
  self.assertEqual(s2["revision"],1);self.assertEqual(self._task_state(s2,"a")["reservation_token"],"reserve:a:a1")
  with self.assertRaisesRegex(ValueError,"stale pool state revision"):
   m.queue_task(p,s2,"b","b1",expected_revision=0,reservation_token="reserve:b:b1")

 def test_atomic_cas_rejects_two_queue_admissions_from_same_store_revision(self):
  p=plan();store=FakeCasStore(m.initial_state(p,parallel_capable=True))
  first=m.queue_task_cas(store,"store-0",p,"a","a1",reservation_token="ra")
  self.assertFalse(first["launch_allowed"])
  with self.assertRaisesRegex(ValueError,"stale expected pool-store revision"):
   m.queue_task_cas(store,"store-0",p,"a","a2",reservation_token="rb")
  _,live=store.read();self.assertEqual(self._task_state(live,"a")["attempt_ids"],["a1"])

 def test_queue_cannot_bypass_parallel_slot(self):
  p=plan();p["max_parallel"]=1;s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"eligible"):
   m.queue_task(p,s,"b","b1",expected_revision=s["revision"],reservation_token="rb")

 def test_review_waits_for_integrated_dependencies(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True)
  for task in ("a","b"):
   s=self._queue(p,s,task,task+"1");s=self._run(p,s,task,task+"1")
   s=self._accept(p,s,task,task+"1",[f"src/{task}/result.txt"],[f"out:{task}"],[f"test:{task}"])
  self.assertNotIn("review",m.ready_task_ids(p,s))
  s=self._integrate(p,s,"a","result:a:a1");s=self._integrate(p,s,"b","result:b:b1")
  self.assertIn("review",m.ready_task_ids(p,s))

 def test_result_identity_and_exact_assigned_branch_are_verified(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"assignment identity"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"],executor_id="other")
  with self.assertRaisesRegex(ValueError,"exact assigned branch head"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"],result_commit=self.result_b)

 def test_result_git_ancestry_is_live_verified(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  tree=self.git("rev-parse",f"{self.result_a}^{{tree}}")
  unrelated=self.git("commit-tree",tree,"-m","unrelated")
  subprocess.check_call(["git","-C",str(self.repo),"branch","-f","worker-a",unrelated],stdout=subprocess.DEVNULL)
  with self.assertRaisesRegex(ValueError,"does not descend"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"],result_commit=unrelated)

 def test_reported_changed_paths_must_equal_actual_git_diff(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"reported changed paths do not match exact Git diff"):
   self._accept(p,s,"a","a1",["src/a/fake.txt"],["out:a"],["test:a"])

 def test_actual_git_diff_cannot_hide_out_of_claim_change(self):
  self.git("switch","-q","worker-a")
  (self.repo/"ESCAPED").write_text("escape");self.git("add","ESCAPED");self.git("commit","-q","-m","escape")
  escaped=self.git("rev-parse","HEAD")
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"reported changed paths do not match exact Git diff"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"],result_commit=escaped)

 def test_unintegrated_required_success_blocks_terminal(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  s=self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"])
  r=m.assess(p,s);self.assertFalse(r["terminal_allowed"]);self.assertIn("a:unintegrated_success",r["blockers"])

 def test_unintegrated_optional_success_blocks_until_explicit_discard(self):
  p=plan(self.base);p["tasks"].append({"id":"opt","role":"review","required":False,"dependencies":[],"executor_id":"opt-review",
   "branch":None,"worktree":None,"write_paths":[],"expected_outputs":["out:opt"],"expected_evidence":["opt:green"],
   "backend_preferences":["local"],"max_runtime_seconds":50,"max_cost_units":5});p["max_parallel"]=3
  s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"opt","o1");s=self._run(p,s,"opt","o1")
  s=self._accept(p,s,"opt","o1",[],["out:opt"],["opt:green"],result_commit=None)
  self.assertIn("opt:unintegrated_success",m.assess(p,s)["blockers"])
  s=m.discard_optional_result(p,s,"opt","result:opt:o1",expected_revision=s["revision"])
  self.assertNotIn("opt:unintegrated_success",m.assess(p,s)["blockers"])
  self.assertTrue(self._task_state(s,"opt")["discarded"])

 def test_failed_worker_does_not_remove_unrelated_ready_task(self):
  p=plan();s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  s=self._fail(p,s,"a","a1","failed")
  self.assertIn("b",m.ready_task_ids(p,s));self.assertIn("b",m.dispatch(p,s)["task_ids"])

 def test_retry_preserves_attempt_history_and_revision(self):
  p=plan();s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._fail(p,s,"a","a1","stale")
  s=m.retry_task(p,s,"a",expected_revision=s["revision"]);s=self._queue(p,s,"a","a2")
  self.assertEqual(self._task_state(s,"a")["attempt_ids"],["a1","a2"]);self.assertEqual(s["revision"],4)

 def test_result_must_stay_in_portable_write_set(self):
  p=plan(self.base);p["tasks"][0]["write_paths"]=["src/other"];s=m.initial_state(p,parallel_capable=True)
  s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"escape declared write set"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"])

 def test_result_requires_expected_outputs_and_evidence(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"missing expected outputs"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["wrong"],["test:a"])
  with self.assertRaisesRegex(ValueError,"missing expected evidence"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["wrong"])

 def test_budgets_and_invalid_numeric_inputs_fail_closed(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"task budget"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"],runtime=301)
  for value in (True,float("nan"),float("inf"),0,-1):
   q=plan();q["tasks"][0]["max_runtime_seconds"]=value
   with self.assertRaises(ValueError):m.validate_plan(q)

 def test_duplicate_cyclic_and_missing_writer_isolation_rejected(self):
  p=plan();p["tasks"][1]["id"]="a"
  with self.assertRaisesRegex(ValueError,"duplicate"):m.validate_plan(p)
  p=plan();p["tasks"][0]["dependencies"]=["review"]
  with self.assertRaisesRegex(ValueError,"cyclic"):m.validate_plan(p)
  p=plan();p["tasks"][0]["branch"]=None
  with self.assertRaises(ValueError):m.validate_plan(p)

 def test_authority_is_false_and_full_completion_requires_integration(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True)
  for task in ("a","b"):
   s=self._queue(p,s,task,task+"1");s=self._run(p,s,task,task+"1")
   s=self._accept(p,s,task,task+"1",[f"src/{task}/result.txt"],[f"out:{task}"],[f"test:{task}"])
   s=self._integrate(p,s,task,f"result:{task}:{task}1")
  s=self._queue(p,s,"review","r1");s=self._run(p,s,"review","r1")
  s=self._accept(p,s,"review","r1",[],["out:review"],["review:green"],result_commit=None)
  self.assertFalse(m.assess(p,s)["complete"])
  s=self._integrate(p,s,"review","result:review:r1");r=m.assess(p,s)
  self.assertTrue(r["complete"]);self.assertTrue(r["terminal_allowed"])
  for name in m.AUTHORITY_FIELDS:self.assertFalse(r[name])

 def test_writer_branch_and_worktree_assignments_are_portable_unique(self):
  p=plan();p["tasks"][1]["branch"]="refs/heads/WORKER-A"
  with self.assertRaisesRegex(ValueError,"branches must be portable-unique"):m.validate_plan(p)
  p=plan();p["tasks"][1]["worktree"]="WORKTREES/A"
  with self.assertRaisesRegex(ValueError,"worktrees must be portable-unique"):m.validate_plan(p)


 def _plan_with_optional(self,base=FAKE_BASE):
  p=plan(base);p["tasks"].append({"id":"opt","role":"review","required":False,"dependencies":[],"executor_id":"opt-review",
   "branch":None,"worktree":None,"write_paths":[],"expected_outputs":["out:opt"],"expected_evidence":["opt:green"],
   "backend_preferences":["local"],"max_runtime_seconds":50,"max_cost_units":5});p["max_parallel"]=3
  return p

 def test_optional_planned_requires_explicit_omission(self):
  p=self._plan_with_optional();s=m.initial_state(p,parallel_capable=True)
  r=m.assess(p,s);self.assertIn("opt:optional_runnable",r["blockers"]);self.assertFalse(r["terminal_allowed"])
  s=m.omit_optional_task(p,s,"opt",expected_revision=s["revision"])
  self.assertEqual(self._task_state(s,"opt")["status"],"omitted")
  self.assertNotIn("opt",m.ready_task_ids(p,s))
  self.assertFalse(any(x.startswith("opt:") for x in m.assess(p,s)["blockers"]))

 def test_optional_recoverable_requires_retry_or_omission(self):
  p=self._plan_with_optional();s=m.initial_state(p,parallel_capable=True)
  s=self._queue(p,s,"opt","o1");s=self._run(p,s,"opt","o1")
  token=self._task_state(s,"opt")["reservation_token"]
  s=m.fail_attempt(p,s,"opt","o1",terminal_status="failed",reservation_token=token,
                   expected_revision=s["revision"],runtime_seconds=10,cost_units=1)
  self.assertIn("opt:optional_disposition_required",m.assess(p,s)["blockers"])
  s=m.omit_optional_task(p,s,"opt",expected_revision=s["revision"])
  self.assertEqual(self._task_state(s,"opt")["status"],"omitted")

 def test_optional_omission_rejects_required_active_and_successful_tasks(self):
  p=self._plan_with_optional();s=m.initial_state(p,parallel_capable=True)
  with self.assertRaisesRegex(ValueError,"optional task"):
   m.omit_optional_task(p,s,"a",expected_revision=s["revision"])
  s=self._queue(p,s,"opt","o1")
  with self.assertRaisesRegex(ValueError,"planned or recoverable"):
   m.omit_optional_task(p,s,"opt",expected_revision=s["revision"])
  s=self._run(p,s,"opt","o1")
  s=self._accept(p,s,"opt","o1",[],["out:opt"],["opt:green"],result_commit=None)
  with self.assertRaisesRegex(ValueError,"planned or recoverable"):
   m.omit_optional_task(p,s,"opt",expected_revision=s["revision"])

 def test_retry_reserves_only_remaining_runtime_and_cost(self):
  p=plan();p["total_runtime_budget_seconds"]=350;p["total_cost_budget_units"]=35
  s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  token=self._task_state(s,"a")["reservation_token"]
  s=m.fail_attempt(p,s,"a","a1",terminal_status="failed",reservation_token=token,
                   expected_revision=s["revision"],runtime_seconds=100,cost_units=10)
  s=m.retry_task(p,s,"a",expected_revision=s["revision"])
  r=m.dispatch(p,s)
  self.assertEqual(r["task_ids"],["a"])
  self.assertEqual(r["reserved_runtime_seconds"],200)
  self.assertEqual(r["reserved_cost_units"],20)
  self.assertEqual(s["runtime_consumed_seconds"],100)
  self.assertEqual(s["cost_consumed_units"],10)

 def test_exhausted_runtime_or_cost_cannot_retry_dispatch_or_launch(self):
  for runtime,cost in ((300,0),(0,30)):
   with self.subTest(runtime=runtime,cost=cost):
    p=plan();s=m.initial_state(p,parallel_capable=True)
    s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
    s=m.fail_attempt(p,s,"a","a1",terminal_status="failed",reservation_token=self._task_state(s,"a")["reservation_token"],
                    expected_revision=s["revision"],runtime_seconds=runtime,cost_units=cost)
    with self.assertRaisesRegex(ValueError,"budget exhausted"):
     m.retry_task(p,s,"a",expected_revision=s["revision"])
    # A persisted legacy retry must also fail admission, not depend on the new retry helper.
    self._task_state(s,"a")["status"]="planned"
    self.assertNotIn("a",m.dispatch(p,s)["task_ids"])
    with self.assertRaises(ValueError):self._queue(p,s,"a","a2")

 def test_successful_retry_enforces_cumulative_task_budget(self):
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True);s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  token=self._task_state(s,"a")["reservation_token"]
  s=m.fail_attempt(p,s,"a","a1",terminal_status="failed",reservation_token=token,
                   expected_revision=s["revision"],runtime_seconds=100,cost_units=10)
  s=m.retry_task(p,s,"a",expected_revision=s["revision"]);s=self._queue(p,s,"a","a2");s=self._run(p,s,"a","a2")
  with self.assertRaisesRegex(ValueError,"task budget"):
   self._accept(p,s,"a","a2",["src/a/result.txt"],["out:a"],["test:a"],runtime=201,cost=21)

 def test_durable_launch_claim_is_one_shot(self):
  p=plan();store=FakeCasStore(m.initial_state(p,parallel_capable=True))
  queued=m.queue_task_cas(store,"store-0",p,"a","a1",reservation_token="ra")
  self.assertFalse(queued["launch_allowed"])
  started=m.claim_launch_cas(store,queued["store_revision"],p,"a","a1",reservation_token="ra")
  self.assertTrue(started["launch_allowed"])
  with self.assertRaises(ValueError):
   m.claim_launch_cas(store,queued["store_revision"],p,"a","a1",reservation_token="ra")

 def test_required_task_cannot_depend_on_optional_direct_or_transitive(self):
  p=plan()
  p["tasks"].append({"id":"opt","role":"review","required":False,"dependencies":[],
   "executor_id":"opt","branch":None,"worktree":None,"write_paths":[],
   "expected_outputs":["out:opt"],"expected_evidence":["ev:opt"],
   "backend_preferences":["local"],"max_runtime_seconds":10,"max_cost_units":1})
  p["max_parallel"]=3
  p["tasks"][0]["dependencies"]=["opt"]
  with self.assertRaisesRegex(ValueError,"required task cannot depend on optional"):
   m.validate_plan(p)
  p=plan()
  p["tasks"].append({"id":"mid","role":"review","required":True,"dependencies":["opt"],
   "executor_id":"mid","branch":None,"worktree":None,"write_paths":[],
   "expected_outputs":["out:mid"],"expected_evidence":["ev:mid"],
   "backend_preferences":["local"],"max_runtime_seconds":10,"max_cost_units":1})
  p["tasks"].append({"id":"opt","role":"review","required":False,"dependencies":[],
   "executor_id":"opt","branch":None,"worktree":None,"write_paths":[],
   "expected_outputs":["out:opt"],"expected_evidence":["ev:opt"],
   "backend_preferences":["local"],"max_runtime_seconds":10,"max_cost_units":1})
  p["max_parallel"]=5
  p["tasks"][0]["dependencies"]=["mid"]
  with self.assertRaisesRegex(ValueError,"required task cannot depend on optional"):
   m.validate_plan(p)

 def test_worker_history_touch_then_restore_is_rejected(self):
  self.git("switch","-q","worker-a")
  (self.repo/"ESCAPED").write_text("temporary")
  self.git("add","ESCAPED");self.git("commit","-q","-m","touch escaped")
  (self.repo/"ESCAPED").unlink()
  self.git("add","-A");self.git("commit","-q","-m","restore escaped")
  (self.repo/"src"/"a"/"result.txt").write_text("final")
  self.git("add","src/a/result.txt");self.git("commit","-q","-m","final")
  result=self.git("rev-parse","HEAD")
  p=plan(self.base);s=m.initial_state(p,parallel_capable=True)
  s=self._queue(p,s,"a","a1");s=self._run(p,s,"a","a1")
  with self.assertRaisesRegex(ValueError,"history touched paths"):
   self._accept(p,s,"a","a1",["src/a/result.txt"],["out:a"],["test:a"],result_commit=result)

 def test_coordination_identity_is_required_and_bound_to_state(self):
  p=plan();s=m.initial_state(p,parallel_capable=True)
  self.assertEqual(s["coordination_ref"],p["coordination_ref"])
  self.assertEqual(s["coordination_store_id"],p["coordination_store_id"])
  q=copy.deepcopy(p);q["coordination_store_id"]="sha256:"+"2"*64
  with self.assertRaisesRegex(ValueError,"coordination_store_id"):
   m.validate_state(q,s)


if __name__=="__main__":unittest.main()
