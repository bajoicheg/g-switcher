import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys
import subprocess
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verification_economics as economics
import run_checks


class VerificationEconomicsTests(unittest.TestCase):
    def test_real_runner_reuses_success_and_rejects_tampered_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'repo';root.mkdir()
            count=base/'count';script=root/'job.py'
            script.write_text('from pathlib import Path\nimport sys\np=Path(sys.argv[1])\np.write_text(str(int(p.read_text())+1) if p.exists() else "1")\n')
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','fixture'],check=True)
            sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            check={'id':'aggregate','kind':'check','required':True,
                   'argv':[sys.executable,str(script),str(count)],'timeout_seconds':60}
            plan={'schema':'command-check-plan/v2','checks':[check],'economics':{
                'check_inputs':{'aggregate':{'dependency_fingerprints':{'job.py':hashlib.sha256(script.read_bytes()).hexdigest()},
                    'parameters':{},'coverage_refs':['review:job-only'],'exact_candidate_required':False}},
                'aggregate_check_ids':['aggregate'],'prior_evidence':[],'repeat_exceptions':[]}}
            plan_path=base/'plan.json'
            def run(number):
                plan_path.write_text(json.dumps(plan))
                return run_checks.run(SimpleNamespace(plan=plan_path,worktree=root,candidate_sha=sha,
                    output_dir=base/str(number),environment_id='local-test',environment_config_sha256='a'*64))
            self.assertEqual(run(1),0);self.assertEqual(count.read_text(),'1')
            prior=base/'1'/'evidence.json'
            plan['economics']['prior_evidence']=[{'path':str(prior),'sha256':hashlib.sha256(prior.read_bytes()).hexdigest()}]
            self.assertEqual(run(2),0);self.assertEqual(count.read_text(),'1')
            evidence=json.loads((base/'2'/'evidence.json').read_text())
            self.assertEqual(evidence['checks'][0]['status'],'REUSED')
            self.assertFalse(evidence['checks'][0]['executed'])
            prior.write_text('{}')
            with self.assertRaisesRegex(ValueError,'digest mismatch'):run(3)

    def test_definition_ignores_only_check_id(self):
        a = {'id':'one','kind':'test','required':True,'argv':['python','x.py'],'timeout_seconds':60}
        self.assertEqual(economics.definition(a), economics.definition(dict(a,id='two')))
        self.assertNotEqual(economics.definition(a), economics.definition(dict(a,argv=['python','y.py'])))

    def test_dependency_bytes_are_verified(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'x.py';p.write_bytes(b'a')
            deps={'x.py':hashlib.sha256(b'a').hexdigest()}
            economics.verify_dependencies(root,deps)
            p.write_bytes(b'b')
            with self.assertRaisesRegex(ValueError,'dependency'):
                economics.verify_dependencies(root,deps)
            with self.assertRaises(ValueError):
                economics.verify_dependencies(root,{'../x.py':deps['x.py']})

    def test_duplicate_aggregate_needs_distinct_reviewed_reason(self):
        check={'id':'one','kind':'check','required':True,'argv':['python','x.py'],'timeout_seconds':60}
        plan={'schema':'command-check-plan/v2','checks':[check,dict(check,id='two')],
              'economics':{'check_inputs':{},'aggregate_check_ids':['one','two'],
                           'prior_evidence':[],'repeat_exceptions':[]}}
        with self.assertRaisesRegex(ValueError,'aggregate'):
            economics.validate_aggregate_repeats(plan)
        plan['checks'].append(dict(check,id='three'))
        plan['economics']['aggregate_check_ids'].append('three')
        plan['economics']['repeat_exceptions']=[{'check_id':name,'reason':'copied reason','coverage_ref':'same:coverage'}
                                              for name in ['two','three']]
        with self.assertRaisesRegex(ValueError,'distinct'):
            economics.validate_aggregate_repeats(plan)


if __name__=='__main__':unittest.main()
