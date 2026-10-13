"""Bounded simulated recovery fixtures; no provider effects or release certification."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import recovery_recipes as m

D = 'sha256:' + 'a' * 64
E = 'sha256:' + 'b' * 64
NOW = '2026-10-09T02:15:00Z'
B = {'schema': 'recovery-bindings/v1', 'repository': 'owner/project',
     'environment_namespace': 'managed_cloud_runtime', 'environment_id': 'native-1',
     'access_mode': 'native_runtime', 'toolchain_fingerprint': D,
     'policy_digest': D, 'input_digests': {'qualification': D, 'error': E}}
DIAG = {'schema': 'recovery-diagnosis/v1', 'code': 'unknown_error',
        'facts': [], 'reference': 'evidence:error'}
H = {'schema': 'recovery-observation-history/v1', 'repository': B['repository'],
     'revision': 0, 'events': []}
PARAMS = {'invocation_ref': 'invocation:original', 'error_evidence_ref': 'evidence:error',
          'approved_read_argv': ['python', '-c', 'print("two words")'], 'diagnostic_limit': 1}
R = {'id': 'known', 'diagnosis_code': 'known_failure', 'priority': 1,
     'requires_all': [], 'forbids': [], 'actions': ['inspect_exact_invocation'], 'outcome': 'reconcile',
     'scope': {'repository': B['repository'], 'environment_id': B['environment_id'],
               'mode': B['access_mode'], 'toolchain_fingerprint': D, 'policy_digest': D},
     'provenance': {'evidence_ref': 'evidence:qualification', 'evidence_sha256': D,
                    'verified_at_utc': '2026-10-09T02:14:00Z'}, 'max_age_seconds': 300,
     'verification': {'required_facts': ['exit:0'], 'success_next_action': 'resume_next_action',
                      'failure_next_action': 'record_blocker'}}
C = {'schema': 'recovery-recipe-catalog/v2', 'recipes': [R]}

def selection(c=C, d=DIAG, b=B, h=H, signal=None, now=NOW):
    return m.select(copy.deepcopy(c), copy.deepcopy(d), bindings=copy.deepcopy(b),
                    now_utc=now, history=copy.deepcopy(h), new_signal=copy.deepcopy(signal))

def event(plan, state='terminal', outcome='failed', event_id='first', attempt='attempt:1'):
    return {'event_id': event_id, 'at_utc': NOW,
            'subject': dict(failure_signature=DIAG['code'], **{k: B[k] for k in
                ('repository','environment_namespace','environment_id','access_mode','toolchain_fingerprint','policy_digest')}),
            'action_fingerprint': plan['action_fingerprint'], 'attempt_id': attempt,
            'operation_key': None, 'state': state, 'evidence_ref': 'evidence:result',
            'evidence_digest': E, 'new_signal_ref': None, 'completed_correction_ref': None,
            'outcome': outcome}

class RecoveryV2(unittest.TestCase):
    def test_v1_output_and_strict_fields_survive_new_arguments(self):
        v1 = {'schema': 'recovery-recipe-catalog/v1', 'recipes': [{k: R[k] for k in
            ('id','diagnosis_code','priority','requires_all','forbids','actions','outcome')}]}
        d = dict(DIAG, code='known_failure')
        old = m.select(v1, d)
        self.assertEqual(m.select(v1, d, bindings={'invalid': True}, history={'bad': 1}), old)
        self.assertNotIn('recipe', old)
        v1['recipes'][0]['scope'] = R['scope']
        with self.assertRaises(ValueError): m.validate_catalog(v1)

    def test_explicit_v2_requires_bindings_time_and_history(self):
        with self.assertRaises(ValueError): m.select(C, DIAG)
        self.assertEqual(m.validate_catalog(C), C)

    def test_recipe_selection_detaches_and_never_grants_authority(self):
        c = copy.deepcopy(C)
        s = m.select(c, dict(DIAG, code='known_failure'), bindings=B, now_utc=NOW, history=H)
        self.assertEqual(s['recipe_id'], 'known')
        s['recipe']['verification']['required_facts'].append('mutated')
        s['steps'].append('record_blocker')
        self.assertEqual(c, C)
        self.assertTrue(all(s[k] is False for k in s if k.startswith('authorizes_')))

    def test_stale_future_or_scope_mismatch_use_only_bounded_diagnostic(self):
        for change in ('stale','future','repository','policy'):
            c = copy.deepcopy(C)
            if change == 'stale': c['recipes'][0]['provenance']['verified_at_utc'] = '2026-10-09T01:00:00Z'
            if change == 'future': c['recipes'][0]['provenance']['verified_at_utc'] = '2026-10-09T02:16:00Z'
            if change == 'repository': c['recipes'][0]['scope']['repository'] = 'other/project'
            if change == 'policy': c['recipes'][0]['scope']['policy_digest'] = E
            s = selection(c=c, d=dict(DIAG,code='known_failure'))
            self.assertIsNone(s['recipe'])
            self.assertEqual(s['steps'], ['inspect_exact_invocation'])

    def test_generic_recipe_needs_local_provenance_digest(self):
        c = copy.deepcopy(C); c['recipes'][0]['scope']['repository'] = None
        self.assertEqual(selection(c=c,d=dict(DIAG,code='known_failure'))['recipe_id'], 'known')
        b = copy.deepcopy(B); b['input_digests'] = {'error': E}
        self.assertIsNone(selection(c=c,b=b,d=dict(DIAG,code='known_failure'))['recipe'])

    def test_history_append_is_deep_copy_revision_and_duplicate_safe(self):
        p = m.action_plan(selection(), DIAG, B, H, PARAMS)
        e = event(p); h = m.append_history(H, e)
        self.assertEqual(h['revision'], 1); self.assertEqual(H['events'], [])
        e['subject']['repository'] = 'mutation'; self.assertEqual(h['events'][0]['subject']['repository'], B['repository'])
        with self.assertRaises(ValueError): m.append_history(h, h['events'][0])

    def test_strict_history_and_binding_validation(self):
        p = m.action_plan(selection(), DIAG, B, H, PARAMS)
        for obj, validate in ((dict(B,token='secret'),m.validate_bindings),
                               (dict(H,extra=True),m.validate_history),
                               (dict(B,policy_digest='bad'),m.validate_bindings)):
            with self.assertRaises(ValueError): validate(obj)
        for k,v in [('state','running'),('outcome','GREEN'),('at_utc','tomorrow'),('action_fingerprint','bad')]:
            h=copy.deepcopy(H);h['events']=[dict(event(p),**{k:v})]
            with self.assertRaises(ValueError): m.validate_history(h)

    def test_unknown_same_subject_outranks_recipe_and_signal(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS)
        h=m.append_history(H,event(p,state='unknown',outcome=None))
        signal={'reference':'signal:1','digest':D,'changed_inputs':{'error':D},'completed_correction_ref':None}
        s=selection(h=h,signal=signal)
        self.assertEqual(s['action'],'reconcile');self.assertEqual(s['steps'],['reconcile_external'])
        with self.assertRaises(ValueError): m.action_plan(s,DIAG,B,h,dict(PARAMS))

    def test_same_attempt_terminal_resolves_unknown_without_erasing_it(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS)
        h=m.append_history(H,event(p,state='unknown',outcome=None))
        h=m.append_history(h,event(p,event_id='resolved'))
        self.assertEqual(len(h['events']),2)
        self.assertEqual(selection(h=h)['steps'],['record_blocker'])

    def test_two_context_loads_preserve_consumed_diagnostic(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS)
        h=m.append_history(H,event(p))
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'history.json';path.write_text(json.dumps(h))
            first=json.loads(path.read_text()); second=json.loads(path.read_text())
            s=selection(h=first)
            self.assertEqual(s['steps'],['record_blocker'])
            d=dict(DIAG,reference='new-chat:error')
            self.assertEqual(selection(h=second,d=d,now='2026-10-09T03:15:00Z')['steps'],['record_blocker'])
            self.assertEqual(json.loads(path.read_text()),h)

    def test_noop_or_unbound_signal_cannot_reset_consumed_diagnostic(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        for changed in ({},{'chat':D},{'error':E},{'error':D}):
            signal={'reference':'signal:new','digest':D,'changed_inputs':changed,'completed_correction_ref':None}
            self.assertEqual(selection(h=h,signal=signal)['steps'],['record_blocker'])

    def test_bound_efficacy_change_enables_one_retry_and_signal_is_consumed(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        b=copy.deepcopy(B);b['input_digests']['error']=D;b['input_digests']['signal:new']=D
        signal={'reference':'signal:new','digest':D,'changed_inputs':{'error':D},'completed_correction_ref':None}
        s=selection(h=h,b=b,signal=signal);self.assertEqual(s['steps'],['inspect_exact_invocation'])
        p2=m.action_plan(s,DIAG,b,h,PARAMS)
        e=event(p2,event_id='retry',attempt='attempt:2');e['new_signal_ref']='signal:new'
        h=m.append_history(h,e)
        self.assertEqual(selection(h=h,b=b,signal=signal)['steps'],['record_blocker'])

    def test_action_plan_exact_parameters_and_verification_bind_fingerprint(self):
        s=selection();p=m.action_plan(s,DIAG,B,H,PARAMS)
        self.assertEqual(set(p),{'schema','handler','parameters','action_fingerprint','verification','next_on_success','next_on_failure','authorities'})
        self.assertEqual(p['handler'],'inspect_exact_invocation');self.assertEqual(p['parameters']['approved_read_argv'],PARAMS['approved_read_argv'])
        self.assertTrue(all(v is False for v in p['authorities'].values()))
        q=copy.deepcopy(PARAMS);q['approved_read_argv'][-1]='print("different")'
        self.assertNotEqual(p['action_fingerprint'],m.action_plan(s,DIAG,B,H,q)['action_fingerprint'])
        self.assertEqual(p['action_fingerprint'],m.action_plan(s,dict(DIAG,reference='chat:new'),B,H,PARAMS)['action_fingerprint'])
        b=copy.deepcopy(B);b['input_digests'].update(chat=D,wake=E,timestamp=D,candidate_sha=E)
        self.assertEqual(p['action_fingerprint'],m.action_plan(s,DIAG,b,H,PARAMS)['action_fingerprint'])
        p['parameters']['approved_read_argv'].append('changed');self.assertEqual(len(PARAMS['approved_read_argv']),3)

    def test_action_plan_rejects_arbitrary_commands_unknown_keys_and_forged_selection(self):
        s=selection()
        for params in (dict(PARAMS,shell='pip install all'),dict(PARAMS,diagnostic_limit=2),dict(PARAMS,approved_read_argv=[' sh '])):
            with self.assertRaises(ValueError): m.action_plan(s,DIAG,B,H,params)
        bad=dict(s,steps=['shell'])
        with self.assertRaises(ValueError):m.action_plan(bad,DIAG,B,H,PARAMS)
        bad=dict(s,authorizes_external_start=True)
        with self.assertRaises(ValueError):m.action_plan(bad,DIAG,B,H,PARAMS)

    def test_recipe_verification_is_part_of_action_fingerprint(self):
        d=dict(DIAG,code='known_failure');s=selection(d=d)
        p=m.action_plan(s,d,B,H,PARAMS)
        c=copy.deepcopy(C);c['recipes'][0]['verification']['required_facts'].append('result:bound')
        q=m.action_plan(selection(c=c,d=d),d,B,H,PARAMS)
        self.assertNotEqual(p['action_fingerprint'],q['action_fingerprint'])
        self.assertEqual(p['verification'],R['verification'])

    def test_dependency_present_reuses_evidence_without_setup_plan(self):
        c=copy.deepcopy(C);r=c['recipes'][0];r['diagnosis_code']='dependencies';r['requires_all']=['dependency:present'];r['actions']=['resume_next_action']
        d=dict(DIAG,code='dependencies',facts=['dependency:present'])
        s=selection(c=c,d=d)
        params={'dependency_ids':['module_a'],'required_by_check':'check:1','installed_evidence_ref':'evidence:imports','approved_missing_only_setup_argv':[]}
        b=copy.deepcopy(B);b['input_digests']['evidence:imports']=D
        p=m.action_plan(s,d,b,H,params)
        self.assertEqual(p['handler'],'resume_next_action');self.assertEqual(p['parameters']['approved_missing_only_setup_argv'],[])
        with self.assertRaises(ValueError):m.action_plan(s,d,B,H,dict(params,approved_missing_only_setup_argv=['pip','install','module_a']))

    def test_reconcile_plan_preserves_original_operation_key(self):
        c=copy.deepcopy(C);c['recipes'][0]['actions']=['reconcile_external'];d=dict(DIAG,code='known_failure')
        params={'operation_key':D,'journal_ref':'journal:original','task_id':'task:original','task_mode':'COMPUTE_ONLY'}
        p=m.action_plan(selection(c=c,d=d),d,B,H,params)
        self.assertEqual(p['parameters'],params)
        with self.assertRaises(ValueError):m.action_plan(selection(c=c,d=d),d,B,H,dict(params,task_mode='NEW'))

    def test_catalog_rejects_unsafe_actions_invalid_utc_and_v2_unknown_keys(self):
        for field,value in [('actions',['shell']),('max_age_seconds',True),('scope',dict(R['scope'],extra=True)),
                            ('verification',dict(R['verification'],success_next_action='shell')),
                            ('provenance',dict(R['provenance'],verified_at_utc='2026-10-09T02:14:00'))]:
            c=copy.deepcopy(C);c['recipes'][0][field]=value
            with self.assertRaises(ValueError):m.validate_catalog(c)

    def test_signal_needs_local_reference_digest_proof(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        b=copy.deepcopy(B);b['input_digests']['error']=D
        signal={'reference':'signal:new','digest':D,'changed_inputs':{'error':D},'completed_correction_ref':None}
        self.assertEqual(selection(h=h,b=b,signal=signal)['steps'],['record_blocker'])

    def test_forged_selection_cannot_replay_consumed_exact_fingerprint(self):
        s=selection();p=m.action_plan(s,DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        with self.assertRaises(ValueError):m.action_plan(s,DIAG,B,h,PARAMS)

    def test_unknown_operation_reconcile_retains_key_and_rejects_replacement(self):
        s=selection();p=m.action_plan(s,DIAG,B,H,PARAMS)
        e=event(p,state='unknown',outcome=None);e['operation_key']=D
        h=m.append_history(H,e);s=selection(h=h)
        params={'operation_key':D,'journal_ref':'journal:original','task_id':'task:original','task_mode':'COMPUTE_ONLY'}
        self.assertEqual(m.action_plan(s,DIAG,B,h,params)['parameters']['operation_key'],D)
        with self.assertRaises(ValueError):m.action_plan(s,DIAG,B,h,dict(params,operation_key=E))

    def test_verified_qualified_recipe_reuses_result_without_new_probe(self):
        d=dict(DIAG,code='known_failure');p=m.action_plan(selection(d=d),d,B,H,PARAMS)
        e=event(p,outcome='verified');e['subject']['failure_signature']='known_failure';e['evidence_digest']=D
        h=m.append_history(H,e)
        s=selection(d=d,h=h)
        self.assertEqual(s['steps'],['resume_next_action']);self.assertEqual(s['reason'],'verified_evidence_reused')
        params={'next_action_ref':'check:next','evidence_ref':'evidence:result'}
        self.assertEqual(m.action_plan(s,d,B,h,params)['handler'],'resume_next_action')

    def test_completed_correction_requires_verified_evidence_and_is_consumed(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        signal={'reference':'signal:correction','digest':D,'changed_inputs':{},'completed_correction_ref':'correction:actual'}
        self.assertEqual(selection(h=h,signal=signal)['steps'],['record_blocker'])
        e=event(p,outcome='verified',event_id='correction',attempt='correction:attempt')
        e['action_fingerprint']=E;e['evidence_ref']='correction:actual';e['evidence_digest']=D
        h=m.append_history(h,e)
        s=selection(h=h,signal=signal);self.assertEqual(s['steps'],['inspect_exact_invocation'])
        q=m.action_plan(s,DIAG,B,h,PARAMS)
        e=event(q,event_id='retry-correction',attempt='retry:correction');e['new_signal_ref']=signal['reference'];e['completed_correction_ref']='correction:actual'
        h=m.append_history(h,e)
        self.assertEqual(selection(h=h,signal=signal)['steps'],['record_blocker'])

    def test_untyped_symbolic_handler_fails_closed(self):
        c=copy.deepcopy(C);c['recipes'][0]['actions']=['repair_scheduler_if_authorized']
        d=dict(DIAG,code='known_failure')
        with self.assertRaises(ValueError):m.action_plan(selection(c=c,d=d),d,B,H,{'scheduler':'anything'})

    def test_discovery_and_route_inspection_have_exact_typed_params(self):
        d=dict(DIAG,code='known_failure');c=copy.deepcopy(C);c['recipes'][0]['actions']=['refresh_capability_registry']
        params={'executable':'codex','expected_version':None,'profile_binding':D,'evidence_ref':'evidence:official'}
        p=m.action_plan(selection(c=c,d=d),d,B,H,params)
        self.assertEqual(p['handler'],'refresh_capability_registry')
        params={'invocation_ref':'invocation:actual','error_evidence_ref':'evidence:actual','bound_route_ref':'route:approved','approved_read_argv':['codex','--version']}
        p=m.action_plan(selection(d=d),d,B,H,params)
        self.assertEqual(p['parameters']['approved_read_argv'],['codex','--version'])

    def test_malformed_scalar_types_raise_value_error(self):
        for obj,fn in [(dict(C,schema=[]),m.validate_catalog),(dict(B,access_mode=[]),m.validate_bindings)]:
            with self.assertRaises(ValueError):fn(obj)
        c=copy.deepcopy(C);c['recipes'][0]['outcome']=[]
        with self.assertRaises(ValueError):m.validate_catalog(c)
        h=copy.deepcopy(H);p=m.action_plan(selection(),DIAG,B,H,PARAMS);h['events']=[dict(event(p),outcome=[])]
        with self.assertRaises(ValueError):m.validate_history(h)

    def test_recipe_provenance_scope_and_parameter_maps_are_not_mutated(self):
        c=copy.deepcopy(C);d=dict(DIAG,code='known_failure');b=copy.deepcopy(B);h=copy.deepcopy(H);params=copy.deepcopy(PARAMS)
        before=copy.deepcopy((c,d,b,h,params))
        s=m.select(c,d,bindings=b,now_utc=NOW,history=h)
        m.action_plan(s,d,b,h,params)
        self.assertEqual((c,d,b,h,params),before)

    def test_dependency_reuse_requires_bound_installed_proof(self):
        c=copy.deepcopy(C);c['recipes'][0]['actions']=['resume_next_action'];d=dict(DIAG,code='known_failure')
        params={'dependency_ids':['module_a'],'required_by_check':'check:1','installed_evidence_ref':'evidence:unbound','approved_missing_only_setup_argv':[]}
        with self.assertRaises(ValueError):m.action_plan(selection(c=c,d=d),d,B,H,params)

    def test_unknown_history_with_non_object_parameters_fails_value_error(self):
        p=m.action_plan(selection(),DIAG,B,H,PARAMS);e=event(p,state='unknown',outcome=None);e['operation_key']=D
        h=m.append_history(H,e)
        with self.assertRaises(ValueError):m.action_plan(selection(h=h),DIAG,B,h,[])

    def test_signal_attestation_or_unrelated_input_never_changes_action_identity(self):
        s=selection();p=m.action_plan(s,DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        b=copy.deepcopy(B);b['input_digests']['proof:new-signal']=D;b['input_digests']['unrelated']=D
        signal={'reference':'proof:new-signal','digest':D,'changed_inputs':{'error':E},'completed_correction_ref':None}
        self.assertEqual(m.action_plan(s,DIAG,b,H,PARAMS)['action_fingerprint'],p['action_fingerprint'])
        proposed=selection(h=h,b=b,signal=signal)
        if proposed['steps']==['inspect_exact_invocation']:
            with self.assertRaises(ValueError):m.action_plan(proposed,DIAG,b,h,PARAMS)
        else:self.assertEqual(proposed['steps'],['record_blocker'])

    def test_changed_real_read_input_changes_action_identity(self):
        s=selection();p=m.action_plan(s,DIAG,B,H,PARAMS);h=m.append_history(H,event(p))
        b=copy.deepcopy(B);b['input_digests']['error']=D;b['input_digests']['proof:new-signal']=D
        signal={'reference':'proof:new-signal','digest':D,'changed_inputs':{'error':D},'completed_correction_ref':None}
        proposed=selection(h=h,b=b,signal=signal)
        q=m.action_plan(proposed,DIAG,b,h,PARAMS)
        self.assertNotEqual(q['action_fingerprint'],p['action_fingerprint'])

if __name__=='__main__':unittest.main()
