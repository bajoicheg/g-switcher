import copy,json,hashlib,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import cost_router as m
import execution_channel_supervisor as supervisor
import test_cost_router as fixtures
NOW='2026-09-25T10:01:00Z'
def digest(x):return 'sha256:'+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def context(kind='codespace',action='create',consumption='compute_backend'):
 binding={'backend_id':'other','provider_namespace':'github_codespaces','provider_kind':kind,'environment_id':None if action=='create' else 'existing-space','configuration_digest':'sha256:'+'2'*64,'evidence_ref':'git:current-provider-binding','evidence_digest':'sha256:'+'7'*64}
 a={k:binding[k] for k in ['backend_id','provider_namespace','provider_kind','environment_id']};a.update(consumption=consumption,action=action,control_host_ref='evidence:active-owner-authorized-host' if consumption=='control_host' else None,compute_backend_ref='backend:other')
 return {'schema':'compute-cost-context/v2','base_context':copy.deepcopy(fixtures.CTX),'provider_bindings':{'schema':'backend-provider-bindings/v1','bindings':[binding]},'codespace_exception':None,'provider_action':a}
def exception(ctx,reason='required_capability'):
 a=ctx['provider_action'];b=ctx['provider_bindings']['bindings'][0]
 return {'schema':'codespace-exception/v1','reason':reason,'repository':'test/project','backend_id':a['backend_id'],'provider_namespace':a['provider_namespace'],'environment_id':a['environment_id'],'consumption':a['consumption'],'action':a['action'],'configuration_digest':b['configuration_digest'],'policy_digest':digest(fixtures.POL),'evidence_ref':'git:actual-required-platform-evidence','evidence_digest':'sha256:'+'8'*64,'observed_at_utc':'2026-09-25T10:00:00Z','max_age_seconds':300,'budget_ref':'refs/heads/cdc/existing-task-budget','budget_revision':'a'*40,'budget_reservation_id':'actual-reservation','budget_operation_key':'sha256:'+'b'*64,'budget_attempt_id':'exact-a1','request_plan_digest':'sha256:'+'c'*64}
class ProviderActionContracts(unittest.TestCase):
 def assess(self,ctx):return m.assess_provider_action(ctx['provider_action'],ctx,fixtures.POL,NOW)
 def test_codespace_missing_exception_denied_not_ordinary_other_compute(self):self.assertFalse(self.assess(context())['allowed_for_callback'])
 def test_outage_alone_is_not_codespace_exception(self):
  c=context();c['base_context'].update(provider_outage_confirmed=True,primary_failure_class='provider');c['codespace_exception']=exception(c,'confirmed_provider_outage');self.assertFalse(self.assess(c)['allowed_for_callback'])
 def test_positive_required_capability_bound_precondition_is_not_authority(self):
  c=context();c['base_context']['required_capability_gap_on_primary']=True;c['codespace_exception']=exception(c);r=self.assess(c);self.assertTrue(r['allowed_for_callback']);self.assertFalse(r['authorizes_external_start'])
 def test_reason_requires_actual_requirement_on_primary(self):
  c=context();c['codespace_exception']=exception(c);self.assertFalse(self.assess(c)['allowed_for_callback'])
 def test_expired_future_policy_wrong_action_or_identity_denied(self):
  for field,value in [('observed_at_utc','2026-09-25T09:00:00Z'),('observed_at_utc','2026-09-25T10:02:00Z'),('policy_digest','sha256:'+'9'*64),('action','resume'),('backend_id','different'),('environment_id','invented'),('configuration_digest','sha256:'+'9'*64)]:
   c=context();c['base_context']['required_capability_gap_on_primary']=True;c['codespace_exception']=exception(c);c['codespace_exception'][field]=value
   with self.subTest(field=field,value=value):self.assertFalse(self.assess(c)['allowed_for_callback'])
 def test_unknown_provider_cannot_create(self):self.assertFalse(self.assess(context(kind='unknown'))['allowed_for_callback'])
 def test_resume_requires_actual_environment_identity(self):
  c=context(action='resume');c['base_context']['required_capability_gap_on_primary']=True;c['codespace_exception']=exception(c);c['provider_action']['environment_id']=None;self.assertFalse(self.assess(c)['allowed_for_callback'])
 def test_other_provider_not_classified_from_backend_name(self):self.assertTrue(self.assess(context(kind='other'))['allowed_for_callback'])
 def test_control_host_exception_separate_from_compute_cloud(self):
  c=context(consumption='control_host');r=m.route(fixtures.REG,fixtures.REQ,fixtures.POL,c,NOW);self.assertNotEqual(r['action'],'route')
 def test_all_legacy_fallback_branches_filter_codespace_without_exception(self):
  for failure,gap,evidence in [('none',False,'portable'),('incompatible',True,'portable'),('provider',False,'portable'),('none',True,'platform')]:
   c=context();c['base_context'].update(primary_failure_class=failure,required_capability_gap_on_primary=gap,evidence_class=evidence,distinct_primary_recovery_attempts=2,provider_outage_confirmed=True,last_primary_failure_at_utc='2026-09-25T09:00:00Z');reg=copy.deepcopy(fixtures.REG);reg['backends']=reg['backends'][:2];reg['backends'][0]['state']='unavailable'
   with self.subTest(failure=failure):self.assertNotEqual(m.route(reg,fixtures.REQ,fixtures.POL,c,NOW)['backend_id'],'other')
 def test_supervisor_uses_same_provider_predicate(self):
  c=context();reg=copy.deepcopy(fixtures.REG);reg['backends']=reg['backends'][:2];reg['backends'][0]['state']='unavailable'
  r=supervisor.supervise(reg,fixtures.REQ,fixtures.POL,c,{'schema':'channel-supervision/v1','attempted_backend_ids':[],'failure_classes':{},'max_failovers':1},NOW);self.assertNotEqual(r['backend_id'],'other')
 def test_v1_strict_readable_and_v2_unknown_fields_rejected(self):
  self.assertEqual(m.validate_context(fixtures.CTX),fixtures.CTX)
  bad=context();bad['cached_authority']=True
  with self.assertRaises(ValueError):m.validate_context(bad)
if __name__=='__main__':unittest.main()
