from pathlib import Path
import copy
import hashlib
import json
import sys
import tempfile
import unittest
import subprocess

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from compact_evidence import project
from compact_evidence import runtime_identity
from execution_efficiency import evaluate, terminal_bundle
from suite_audit import audit


def low_request():
    return {'schema':'execution-efficiency/v1','quality':{'schema':'quality-assessment/v1',
        'project_level':'FAST','risk_level':'FAST','risk_categories':['documentation'],
        'risk_reason':'reversible backlog','mandatory_check_ids':[]},
        'change_kind':'text_layout','small_reversible':True,'independent_tasks':2,
        'observation':{'unchanged_probes':2,'probe_limit':2,'new_information_ref':None,
                       'parallel_benefit_ref':None},
        'unknown_effect':{'operation_key':'sha256:original','guard_ref':'git:original'},
        'independent_work_available':True}


class EfficiencyTests(unittest.TestCase):
    def test_actual_saved_runtime_overrides_stale_interface_and_rejects_changed_bytes(self):
        from active_package import _inventory
        from package_transport import _tree_oid
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runtime';root.mkdir();(root/'agents').mkdir()
            (root/'VERSION').write_text('3.4.0\n')
            (root/'manifest.json').write_text('{"version":"3.4.0"}')
            (root/'agents/openai.yaml').write_text('version: 3.4.0\n')
            (root/'SKILL.md').write_text('# Continuous Development Cycle v3.4.0\n')
            loader=Path(tmp)/'loader.md';loader.write_text('current saved loader')
            subprocess.run(['git','init','-q',tmp],check=True)
            subprocess.run(['git','-C',tmp,'add','loader.md'],check=True)
            subprocess.run(['git','-C',tmp,'-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','saved'],check=True)
            saved=subprocess.check_output(['git','-C',tmp,'rev-parse','HEAD'],text=True).strip()
            d={'schema':'runtime-identity/v1','runtime_root':str(root),'version':'3.4.0',
               'package_tree':_tree_oid(_inventory(root)[0].values()),'saved_commit':saved,
               'loader_path':str(loader),'saved_loader_sha256':hashlib.sha256(loader.read_bytes()).hexdigest(),
               'interface_loader_sha256':'b'*64,'acceptance_ref':'git:actual-saved-acceptance'}
            r=runtime_identity(d);self.assertTrue(r['verified']);self.assertTrue(r['load_actual_saved_loader'])
            wrong=copy.deepcopy(d);wrong['saved_commit']='0'*40
            self.assertFalse(runtime_identity(wrong)['verified'])
            (root/'VERSION').write_text('3.3.0\n')
            self.assertFalse(runtime_identity(d)['verified'])

    def test_low_risk_and_unchanged_investigation_do_not_multiply_work(self):
        r=evaluate(low_request())
        self.assertEqual((r['execution'],r['review']),('SINGLE','SELF'))
        self.assertFalse(r['new_tests_required']);self.assertFalse(r['repeat_probe_recommended'])
        self.assertEqual(r['observation_action'],'CONTINUE_INDEPENDENT')
        self.assertFalse(r['unknown_replay_allowed'])

    def test_critical_risk_never_uses_text_shortcut(self):
        d=low_request();d['quality']['risk_categories']=['executor_authority']
        d['quality']['risk_reason']='ownership gate'
        r=evaluate(d)
        self.assertEqual(r['review'],'ORDERED_INDEPENDENT')
        self.assertTrue(r['new_tests_required'])

    def test_actual_strategy_v2_does_not_delegate_trivial_disjoint_tasks(self):
        from test_execution_strategy import request, task
        from execution_strategy import evaluate as strategy
        d=request(task('a','docs/a'),task('b','docs/b'))
        d.update(schema='execution-strategy/v2',parallel_benefit_ref=None)
        self.assertEqual(strategy(d)['action'],'SINGLE')

    def test_unknown_overhead_stays_unknown_in_real_report_comparison(self):
        import operation_report
        root=Path(__file__).resolve().parents[1]
        d=json.loads((root/'templates/operation-observation.json').read_text())
        d['schema']='operation-observation/v2'
        d['overhead']={key:{'value':None,'unknown_reason':'provider has no bound counter'}
                       for key in operation_report.OVERHEAD}
        after=copy.deepcopy(d);after['overhead']['repeat_checks']={'value':0,'unknown_reason':None}
        r=operation_report.compare(d,after)
        self.assertIsNone(r['overhead']['repeat_checks']['delta'])
        self.assertIsNone(r['tokens']['delta'])

    def test_large_utf8_receipt_is_bound_and_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'receipt.json'
            raw=json.dumps({'status':'DONE','lease':'я'*100000,'a/b':{'~key':1}},ensure_ascii=False).encode()
            p.write_bytes(raw);r=project(p,['/status','/lease','/a~1b/~0key'],512)
            self.assertLessEqual(len(json.dumps(r,ensure_ascii=False,sort_keys=True).encode())+1,512)
            self.assertEqual(r['source_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(r['values']['/status'],'DONE')
            with self.assertRaises(ValueError):project(p,['/missing'])

    def test_duplicate_audit_requires_risk_review_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'test_pair.py';p.write_text('def test_a():\n assert 1\ndef test_b():\n assert 1\n')
            before=p.read_bytes();r=audit(root)
            self.assertEqual(len(r['duplicate_candidates']),1)
            self.assertFalse(r['automatic_deletion_allowed']);self.assertEqual(p.read_bytes(),before)

    def test_terminal_bundle_uses_original_gate_and_current_store_readback(self):
        from test_final_response_gate import T, continuity, receipt, OWNER, INV_ID
        lease=T().released()
        class Store:
            def read(self):return 'c'*40,copy.deepcopy(lease)
            def read_revision(self,revision):return copy.deepcopy(lease)
        req={'schema':'terminal-bundle/v1','invocation_id':INV_ID,
             'owned_lease':{'owner_id':OWNER,'generation':1},'release_receipt':receipt(lease),
             'continuity':continuity(True),'runtime':{'status':'succeeded','quiescent':True,'process_ids':[123],'evidence_ref':'actual:runtime'},
             'pool':{'accepted':True,'integrated':True,'evidence_ref':'actual:pool'},
             'physical':[{'pid':123,'absent':True,'observed_at_utc':'2026-01-01T10:02:00Z','evidence_ref':'actual:ps'}],
             'remaining_queue':['Windows gates pending']}
        with self.assertRaisesRegex(ValueError,'terminal bundle'):
            terminal_bundle(req,Store(),now_utc='2026-01-01T10:02:00Z')
        req['schema']='terminal-bundle/v2'
        req['runtime_binding']={'handle_root':'caller-labelled','handle_id':'caller-labelled'}
        with self.assertRaisesRegex(ValueError,'authentic canonical'):
            terminal_bundle(req,Store(),now_utc='2026-01-01T10:02:00Z')


if __name__=='__main__':unittest.main()
