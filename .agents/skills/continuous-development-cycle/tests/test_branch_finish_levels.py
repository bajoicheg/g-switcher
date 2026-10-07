import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from branch_finish import evaluate
from test_review_levels import pipeline
from test_evidence_reuse import evidence

class FinishLevels(unittest.TestCase):
    def base(self,level='MEDIUM'):
        d=json.loads((ROOT/'templates/branch-finish.json').read_text())
        d['schema']='branch-finish/v2';d.pop('spec_compliance_green');d.pop('code_quality_green')
        d.update(review_pipeline=pipeline(level),review_candidate_sha=d['candidate_sha'],reused_checks=[])
        d['review_pipeline']['assessment']['mandatory_check_ids']=['unit'];return d
    def result(self,d):
        try:return evaluate(d)
        except ValueError as e:self.fail('level-aware finishing not implemented: '+str(e))
    def test_medium_finishes_with_one_combined_review(self):
        self.assertTrue(self.result(self.base())['ready'])
    def test_invalid_review_or_moved_review_head_blocks(self):
        d=self.base();d['review_pipeline']['combined_review']['reviewer_ref']='executor:1'
        self.assertFalse(self.result(d)['ready'])
        d=self.base();d['review_candidate_sha']='9'*40
        self.assertFalse(self.result(d)['ready'])
    def test_mandatory_check_cannot_be_omitted(self):
        d=self.base();d['required_checks']=[];self.assertFalse(self.result(d)['ready'])
    def test_explicit_reuse_can_cover_mandatory_check(self):
        d=self.base();d['required_checks']=[];e=evidence();e['check_id']='unit';e['target_candidate_sha']=d['candidate_sha']
        d['reused_checks']=[e];self.assertTrue(self.result(d)['ready'])
        e['current_inputs']['environment_fingerprint']='d'*64
        self.assertFalse(self.result(d)['ready'])

if __name__=='__main__':unittest.main()
