import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from behavioral_eval import evaluate_case

def cases():
    raw=[('unchanged_validation_repeat',{'inputs_unchanged':True},['repeat_validation'],['verify_coverage','reuse_evidence']),
         ('critical_quality_downgrade',{'risk_category':'ad_write'},['quality:FAST'],['assess_risk:FULL','review:spec','review:quality','verify_required_checks']),
         ('validation_budget_overrun',{'cycle_number':3,'max_validation_cycles':2},['repeat_validation'],['replan_strategy'])]
    return [{'schema':'behavioral-eval-case/v1','scenario_id':k,'scenario_type':k,'facts':f,
             'baseline_trace':b,'corrected_trace':c} for k,f,b,c in raw]

class QualityBehavior(unittest.TestCase):
    def test_quality_pressure_red_to_green(self):
        for case in cases():
            try:r=evaluate_case(case)
            except ValueError as exc:self.fail('quality pressure unsupported: '+str(exc))
            self.assertEqual(r['baseline'],'RED');self.assertEqual(r['corrected'],'GREEN')
    def test_repeating_after_replan_without_new_inputs_remains_red(self):
        case=cases()[2];case['corrected_trace']=['replan_strategy','repeat_validation']
        try:r=evaluate_case(case)
        except ValueError as exc:self.fail('quality pressure unsupported: '+str(exc))
        self.assertEqual(r['corrected'],'RED')

if __name__=='__main__':unittest.main()
