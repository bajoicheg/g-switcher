from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from parallel_task_planner import plan

class T(unittest.TestCase):
 def base(self):return json.loads((ROOT/"templates"/"parallel-task-plan.json").read_text())
 def test_independent_writers_share_wave(self):
  r=plan(self.base())
  self.assertEqual(len(r["waves"]),1)
  self.assertEqual(r["waves"][0]["task_ids"],["task-model","task-ui"])
  self.assertLess(r["parallel_estimate_seconds"],r["sequential_estimate_seconds"])
  self.assertFalse(r["authorizes_worker_launch"]);self.assertFalse(r["authorizes_merge"])
 def test_overlapping_writers_serialize(self):
  d=self.base();d["tasks"][1]["write_paths"]=["src/model/sub"]
  r=plan(d)
  self.assertEqual(len(r["waves"]),2)
  self.assertEqual(r["waves"][0]["task_ids"],["task-model"])
  self.assertEqual(r["waves"][1]["task_ids"],["task-ui"])
 def test_case_only_writer_paths_serialize(self):
  d=self.base();d["tasks"][0]["write_paths"]=["src/UI"];d["tasks"][1]["write_paths"]=["src/ui/sub"]
  r=plan(d);self.assertEqual(len(r["waves"]),2)
 def test_unicode_equivalent_writer_paths_serialize(self):
  d=self.base();d["tasks"][0]["write_paths"]=["src/café"];d["tasks"][1]["write_paths"]=["src/café/sub"]
  r=plan(d);self.assertEqual(len(r["waves"]),2)
 def test_same_writer_portable_aliases_rejected(self):
  for paths in (["src/Foo","src/foo"],["src/café","src/café"]):
   d=self.base();d["tasks"][0]["write_paths"]=paths
   with self.subTest(paths=paths):
    with self.assertRaises(ValueError):plan(d)
 def test_nonfinite_estimate_rejected(self):
  for bad in (float("nan"),float("inf"),float("-inf")):
   d=self.base();d["tasks"][0]["estimated_seconds"]=bad
   with self.subTest(value=bad):
    with self.assertRaises(ValueError):plan(d)
 def test_cycle_rejected(self):
  d=self.base();d["tasks"][0]["dependencies"]=["task-ui"];d["tasks"][1]["dependencies"]=["task-model"]
  with self.assertRaises(ValueError):plan(d)
 def test_backslash_write_path_rejected(self):
  d=self.base();d["tasks"][0]["write_paths"]=["src\\model"]
  with self.assertRaises(ValueError):plan(d)
 def test_non_writer_cannot_claim_write_set(self):
  d=self.base();d["tasks"].append({"id":"task-review","role":"review","dependencies":[],"write_paths":["docs/review.md"],"expected_outputs":["review:x"],"expected_evidence":["review:green"],"estimated_seconds":10})
  with self.assertRaises(ValueError):plan(d)
if __name__=="__main__":unittest.main()
