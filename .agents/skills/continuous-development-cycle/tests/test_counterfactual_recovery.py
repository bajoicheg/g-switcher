import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import counterfactual_recovery as m
class T(unittest.TestCase):
 def test_selects_new_information_gaining_strategy(self):
  d={"schema":"counterfactual-recovery/v1","failed_strategies":[{"strategy_id":"retry","failure_class":"provider","information_gain":0}],"candidate_strategies":[{"strategy_id":"retry","expected_information_gain":1,"compatible":True,"cost_rank":1},{"strategy_id":"alternate","expected_information_gain":2,"compatible":True,"cost_rank":2}]}
  r=m.choose(d);self.assertEqual(r["strategy_id"],"alternate");self.assertFalse(r["authorizes_external_start"])
 def test_no_new_strategy_blocks(self):
  d={"schema":"counterfactual-recovery/v1","failed_strategies":[{"strategy_id":"retry","failure_class":"provider","information_gain":0}],"candidate_strategies":[{"strategy_id":"retry","expected_information_gain":1,"compatible":True,"cost_rank":1}]}
  self.assertEqual(m.choose(d)["action"],"BLOCKED")
if __name__=="__main__":unittest.main()
