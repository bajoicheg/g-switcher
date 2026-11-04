from pathlib import Path
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
try:import evidence_reuse as reuse
except ModuleNotFoundError:reuse=None
from verification_gate import evaluate as gate

def evidence():
    inputs={'dependency_fingerprints':{'src/a.py':'a'*64},'argv':['python','test.py'],
            'parameters':{},'environment_fingerprint':'b'*64,'check_definition_fingerprint':'c'*64}
    return {'schema':'evidence-reuse/v1','check_id':'package','source_candidate_sha':'1'*40,
            'target_candidate_sha':'2'*40,'source_evidence_ref':'git:original-run',
            'source_state':'success','original_inputs':inputs,'current_inputs':copy.deepcopy(inputs),
            'coverage_refs':['review:dependency-coverage'],'exact_candidate_required':False}

class ReuseTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(reuse,'evidence reuse feature is not implemented')
    def test_unchanged_inputs_allow_reuse_between_shas(self):
        r=reuse.evaluate(evidence());self.assertTrue(r['reusable'])
        self.assertEqual(r['source_candidate_sha'],'1'*40);self.assertEqual(r['target_candidate_sha'],'2'*40)
        self.assertFalse(r['authorizes_release'])
    def test_empty_and_whitespace_arguments_allow_reuse_without_normalization(self):
        for argv in [[''],[' \t\n'],['python','test.py','',' \t\n',' value ']]:
            with self.subTest(argv=argv):
                d=evidence()
                d['original_inputs']['argv']=list(argv);d['current_inputs']['argv']=list(argv)
                before=copy.deepcopy(d)
                try:r=reuse.evaluate(d)
                except ValueError as exc:self.fail('valid string argv rejected: '+str(exc))
                self.assertTrue(r['reusable']);self.assertEqual(r['blockers'],[])
                self.assertEqual(d,before)
                self.assertEqual(r['source_evidence_ref'],'git:original-run')
                for key in ['authorizes_product_write','authorizes_release','authorizes_external_start']:
                    self.assertFalse(r[key])
    def test_empty_and_whitespace_argument_changes_invalidate_reuse(self):
        for original,current in [('', ' '),(' ', ''),(' \t', '\t '),(' value ','value')]:
            with self.subTest(original=original,current=current):
                d=evidence()
                d['original_inputs']['argv']=['python','test.py',original]
                d['current_inputs']['argv']=['python','test.py',current]
                try:r=reuse.evaluate(d)
                except ValueError as exc:self.fail('valid string argv rejected: '+str(exc))
                self.assertFalse(r['reusable']);self.assertEqual(r['blockers'],['inputs_changed:argv'])
    def test_nonstring_arguments_rejected_in_original_or_current_inputs(self):
        for key in ['original_inputs','current_inputs']:
            for arg in [None,False,0,1.5,[],{}]:
                with self.subTest(inputs=key,arg=arg):
                    d=evidence();d[key]['argv']=['python',arg]
                    with self.assertRaises(ValueError):reuse.evaluate(d)
    def test_argv_must_be_nonempty_list_in_original_or_current_inputs(self):
        for key in ['original_inputs','current_inputs']:
            for argv in [[],None,'python',('python',),{}]:
                with self.subTest(inputs=key,argv=argv):
                    d=evidence();d[key]['argv']=argv
                    with self.assertRaises(ValueError):reuse.evaluate(d)
    def test_changed_dependency_parameters_environment_or_command_invalidates(self):
        for key,value in [('dependency_fingerprints',{'src/a.py':'d'*64}),('parameters',{'x':1}),
                          ('environment_fingerprint','e'*64),('argv',['test.py','python']),
                          ('check_definition_fingerprint','f'*64)]:
            d=evidence();d['current_inputs'][key]=value
            r=reuse.evaluate(d);self.assertFalse(r['reusable']);self.assertIn('inputs_changed:'+key,r['blockers'])
    def test_exact_candidate_gate_rejects_cross_sha(self):
        d=evidence();d['exact_candidate_required']=True
        self.assertIn('exact_candidate_required',reuse.evaluate(d)['blockers'])
    def test_failed_source_cannot_be_reused(self):
        d=evidence();d['source_state']='failed';self.assertFalse(reuse.evaluate(d)['reusable'])
    def test_missing_coverage_or_dependencies_rejected(self):
        for key in ['coverage_refs','dependency_fingerprints']:
            d=evidence()
            if key=='coverage_refs':d[key]=[]
            else:d['original_inputs'][key]={}
            with self.assertRaises(ValueError):reuse.evaluate(d)
    def test_non_json_parameters_rejected(self):
        d=evidence();d['current_inputs']['parameters']={'bad':float('nan')}
        with self.assertRaises(ValueError):reuse.evaluate(d)

class GateReuseTests(unittest.TestCase):
    def base(self):
        d=json.loads((ROOT/'templates/verification-gate.json').read_text())
        d['schema']='verification-gate/v2';d['required_checks']=[]
        e=evidence();e['target_candidate_sha']=d['expected_head'];d['reused_checks']=[e]
        return d
    def result(self,d):
        try:return gate(d)
        except ValueError as exc:self.fail('reuse gate not implemented: '+str(exc))
    def test_reuse_gate_accepts_explicit_equivalence(self):
        r=self.result(self.base());self.assertTrue(r['allowed']);self.assertEqual(r['schema'],'verification-gate-result/v2')
    def test_reuse_cannot_bypass_fresh_source_or_ownership(self):
        d=self.base();d['authoritative_source_fresh']=False;d['ownership']['lease_state']='active'
        r=self.result(d);self.assertFalse(r['allowed']);self.assertIn('lease_not_released',r['blockers'])
    def test_changed_environment_blocks_terminal_claim(self):
        d=self.base();d['reused_checks'][0]['current_inputs']['environment_fingerprint']='d'*64
        self.assertFalse(self.result(d)['allowed'])
    def test_wrong_target_blocks(self):
        d=self.base();d['reused_checks'][0]['target_candidate_sha']='9'*40
        self.assertFalse(self.result(d)['allowed'])
    def test_duplicate_check_ids_rejected(self):
        d=self.base();d['reused_checks'].append(copy.deepcopy(d['reused_checks'][0]))
        with self.assertRaises(ValueError):gate(d)
    def test_overlap_with_direct_checks_rejected(self):
        d=self.base();d['required_checks']=[{'id':'package','state':'success','candidate_sha':d['expected_head'],'evidence_ref':'run:2'}]
        with self.assertRaises(ValueError):gate(d)

if __name__=='__main__':unittest.main()
