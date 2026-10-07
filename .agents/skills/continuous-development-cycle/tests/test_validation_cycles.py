from pathlib import Path
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import quality_levels
from verification_gate import evaluate as verify

def cycle(number=1):
    return {'schema':'validation-cycle/v1','cycle_number':number,'max_validation_cycles':2,
            'changed_inputs':[],'risk_reason':'','prior_evidence_insufficient_reason':'',
            'strategy_revision_ref':None,
            'budget_observation':{'time_seconds':2,'tokens':None,'external_starts':0,
               'time_limit_seconds':60,'token_limit':None,'external_start_limit':1,
               'unknown_reason':'host does not expose token usage'}}

class Cycles(unittest.TestCase):
    def result(self,d):
        self.assertTrue(hasattr(quality_levels,'evaluate_cycle'),'cycle budget not implemented')
        return quality_levels.evaluate_cycle(d)
    def changed(self,n):
        d=cycle(n);d.update(changed_inputs=['src/a.py'],risk_reason='corrected failing behavior',
                           prior_evidence_insufficient_reason='old code failed');return d
    def test_first_cycle_allowed_without_authority(self):
        r=self.result(cycle());self.assertTrue(r['validation_recommended']);self.assertFalse(r['authorizes_external_start'])
    def test_external_start_limit_does_not_block_local_validation(self):
        for used in (0,1):
            with self.subTest(used=used):
                d=cycle();d['budget_observation'].update(external_starts=used,external_start_limit=used)
                r=self.result(d)
                self.assertTrue(r['validation_recommended'])
                self.assertEqual(r['action'],'VALIDATE')
                self.assertEqual(r['budget_observation'],d['budget_observation'])
                self.assertFalse(r['authorizes_external_start'])
    def test_unchanged_repeat_not_recommended(self):
        self.assertFalse(self.result(cycle(2))['validation_recommended'])
    def test_third_cycle_requires_strategy_revision(self):
        self.assertEqual(self.result(self.changed(3))['action'],'REPLAN_REQUIRED')
    def test_third_cycle_with_revision_and_reason_can_be_recommended(self):
        d=self.changed(3);d['strategy_revision_ref']='git:revised-strategy'
        self.assertTrue(self.result(d)['validation_recommended'])
    def test_exhausted_budget_cannot_be_reset_by_strategy_ref(self):
        d=self.changed(3);d['strategy_revision_ref']='git:revised'
        d['budget_observation']['time_seconds']=60
        self.assertFalse(self.result(d)['validation_recommended'])
    def test_unknown_usage_is_not_invented(self):
        r=self.result(cycle());self.assertIsNone(r['budget_observation']['tokens'])
    def test_negative_nonfinite_or_boolean_metrics_rejected(self):
        for value in [-1,float('nan'),True]:
            d=cycle();d['budget_observation']['time_seconds']=value
            self.assertTrue(hasattr(quality_levels,'evaluate_cycle'),'cycle budget not implemented')
            with self.assertRaises(ValueError):quality_levels.evaluate_cycle(d)
    def test_replan_does_not_make_unrun_required_check_green(self):
        self.assertEqual(self.result(self.changed(3))['action'],'REPLAN_REQUIRED')
        d=json.loads((ROOT/'templates/verification-gate.json').read_text());d['required_checks'][0]['state']='not_run'
        self.assertFalse(verify(d)['allowed'])

if __name__=='__main__':unittest.main()
