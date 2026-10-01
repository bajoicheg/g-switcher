from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from ci_evidence_classifier import classify
BASE={"schema":"ci-execution-observation/v1","provider":"example-ci","run_id":"run-1","run_status":"completed","conclusion":"success","job_started":True,"executable_steps":2,"setup_steps_started":1,"product_steps_started":1,"product_failures":0}
class T(unittest.TestCase):
 def test_terminal_success(self):
  r=classify(copy.deepcopy(BASE));self.assertEqual(r["class"],"terminal_success");self.assertFalse(r["source_change_allowed"])
 def test_zero_step_is_infrastructure_not_product_red(self):
  d=copy.deepcopy(BASE);d.update(conclusion="startup_failure",job_started=False,executable_steps=0,setup_steps_started=0,product_steps_started=0)
  r=classify(d);self.assertEqual(r["class"],"pre_run_infrastructure");self.assertFalse(r["product_execution_proven"]);self.assertFalse(r["source_change_allowed"])
 def test_setup_failure_does_not_allow_source_change(self):
  d=copy.deepcopy(BASE);d.update(conclusion="failure",executable_steps=1,setup_steps_started=1,product_steps_started=0)
  r=classify(d);self.assertEqual(r["class"],"setup");self.assertFalse(r["source_change_allowed"])
 def test_executed_product_failure_can_route_to_product_correction(self):
  d=copy.deepcopy(BASE);d.update(conclusion="failure",product_failures=1)
  r=classify(d);self.assertEqual(r["class"],"product_test");self.assertTrue(r["source_change_allowed"])
if __name__=="__main__":unittest.main()
