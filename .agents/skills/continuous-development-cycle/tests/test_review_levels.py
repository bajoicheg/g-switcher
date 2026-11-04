from pathlib import Path
import copy,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from review_pipeline import evaluate
from test_quality_levels import assessment

def review(reviewer=None,seq=None):
    return {'state':'green' if reviewer else 'not_run','reviewer_ref':reviewer,
            'sequence':seq,'evidence_refs':['evidence:review'] if reviewer else [],'findings':[]}

def pipeline(level):
    d={'schema':'review-pipeline/v2','change_id':'change:1','implementer_ref':'executor:1',
       'assessment':assessment(level),'self_review':review(),'combined_review':dict(review(),covers=[]),
       'spec_compliance':review(),'code_quality':review()}
    if level=='FAST':d['self_review']=review('executor:1',1)
    if level=='MEDIUM':d['combined_review']=dict(review('reviewer:1',1),covers=['requirements','quality'])
    if level=='FULL':
        d['spec_compliance']=review('reviewer:spec',1);d['code_quality']=review('reviewer:quality',2)
    return d

class ReviewLevels(unittest.TestCase):
    def result(self,d):
        try:return evaluate(d)
        except ValueError as e:self.fail('new review contract unavailable: '+str(e))
    def test_three_levels_green(self):
        for level in ['FAST','MEDIUM','FULL']:
            with self.subTest(level=level):
                r=self.result(pipeline(level));self.assertTrue(r['review_green'])
                self.assertEqual(r['effective_level'],level);self.assertFalse(r['authorizes_merge'])
    def test_medium_rejects_author_review(self):
        d=pipeline('MEDIUM');d['combined_review']['reviewer_ref']='executor:1'
        self.assertFalse(self.result(d)['review_green'])
    def test_medium_requires_both_coverage_areas(self):
        d=pipeline('MEDIUM');d['combined_review']['covers']=['quality']
        self.assertFalse(self.result(d)['review_green'])
    def test_full_rejects_same_reviewers_or_reverse_order(self):
        for key,value in [('reviewer_ref','reviewer:spec'),('sequence',1),('reviewer_ref','executor:1')]:
            d=pipeline('FULL');d['code_quality'][key]=value
            self.assertFalse(self.result(d)['review_green'])
    def test_critical_risk_cannot_use_fast_review(self):
        d=pipeline('FAST');d['assessment']['risk_categories']=['ad_write']
        self.assertFalse(self.result(d)['review_green'])
    def test_open_finding_blocks_every_level(self):
        for level,key in [('FAST','self_review'),('MEDIUM','combined_review'),('FULL','code_quality')]:
            d=pipeline(level);d[key]['findings']=[{'id':'f','summary':'unsafe','state':'open','resolution_ref':None}]
            self.assertFalse(self.result(d)['review_green'])
    def test_unused_review_is_rejected(self):
        d=pipeline('FAST');d['spec_compliance']=review('extra',2)
        self.assertFalse(self.result(d)['review_green'])

if __name__=='__main__':unittest.main()
