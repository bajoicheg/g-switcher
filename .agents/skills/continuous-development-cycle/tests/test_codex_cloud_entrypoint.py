"""Deterministic fixtures are simulated provider data, never live acceptance."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
 import codex_cloud_entrypoint as m
except ModuleNotFoundError:m=None
NOW='2026-10-09T02:00:00Z';KEY='sha256:'+'a'*64
D=lambda x:'sha256:'+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def fixtures():
 import codex_cloud_profile as profile
 env={mode:{'provider_namespace':ns,'id':('native-task' if mode=='native_runtime' else 'd'*32 if mode=='official_cli' else None),'url':None,'label':('test-env' if mode!='official_ui' else None)} for mode,ns in [('native_runtime','managed_cloud_runtime'),('official_ui','codex_cloud_ui'),('official_cli','codex_cloud_cli')]}
 p={'schema':'codex-cloud-project-profile/v1','repository':'test/project','source_ref':'refs/heads/cdc/candidate','environments':env,'control_host':{'kind':'native_cloud','provider_namespace':'managed_cloud_runtime','binding_ref':'fixture:actual-native-host'},'access_modes':{x:{'configured':x!='official_ui','capability_ref':'fixture:qualification:'+x if x!='official_ui' else None} for x in env},'toolchain':{'cli_executable':'codex','cli_version':'1.0'},'setup':{'fingerprint':'sha256:'+'1'*64,'commands':[['python','-c','print("Привет мир")']]},'policy_digest':'sha256:'+'2'*64,'provenance':[]}
 probe={'schema':'cloud-profile-probe/v1','observed_at_utc':NOW,'inventory_complete':False,'repository':p['repository'],'source_ref':p['source_ref'],'environments':copy.deepcopy(env),'setup_fingerprint':p['setup']['fingerprint'],'policy_digest':p['policy_digest'],'cli_version':p['toolchain']['cli_version'],'access_modes':{x:{'complete':True,'status':'ready' if x=='native_runtime' else 'unavailable','reason':'native authenticated' if x=='native_runtime' else 'CLI401','evidence_ref':'fixture:actual:'+x,'binding_digest':profile.profile_binding_digest(p,x),'observed_at_utc':NOW} for x in env}}
 domain={'complete':True,'evidence_ref':'fixture:fresh-read','binding_digest':'sha256:'+'3'*64}
 restored={'schema':'cloud-restored-operation/v1','mode':None,'operation_key':None,'journal_ref':None,'journal_digest':None,'journal_state':'NONE_VERIFIED','task_id':None,'task_url':None,'guard_ref':None,'intent_ref':None,'lookup':{'operation_key':None,'observed_at_utc':NOW,'complete':True,'journal_absence_verified':True,'evidence_ref':'fixture:exact-no-known-op'},'terminal_evidence_ref':None}
 bindings={'schema':'recovery-bindings/v1','repository':p['repository'],'environment_namespace':'managed_cloud_runtime','environment_id':'native-task','access_mode':'native_runtime','toolchain_fingerprint':'sha256:'+'4'*64,'policy_digest':p['policy_digest'],'input_digests':{}}
 c={'schema':'cloud-entry-context/v1','repository':p['repository'],'source_ref':p['source_ref'],'exact_sha':'c'*40,'task_id':'native-local-task','task_mode':'COMPUTE_ONLY','access_mode':'native_runtime','intent':None,'checks':[{'id':'suite','argv':['python','-c','print("Привет мир")'],'minimum_test_count':None}],'development':None,'restored':restored,'resume_capsule':None,'resume_probe':None,'live_recovery':{'schema':'cloud-live-recovery/v1','observed_at_utc':NOW,'source':copy.deepcopy(domain),'ownership':copy.deepcopy(domain),'provider':dict(domain,complete=False,evidence_ref=None,binding_digest=None)},'recovery':{'schema':'cloud-entry-recovery/v1','catalog_ref':None,'catalog':None,'diagnosis':None,'history_ref':None,'history':None,'bindings':bindings,'new_signal':None}}
 import test_cost_router as routing
 reg=copy.deepcopy(routing.REG);reg['observed_at_utc']=NOW
 return p,c,probe,reg,copy.deepcopy(routing.POL),copy.deepcopy(routing.CTX)
class EntrypointContracts(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(m,'Public entrypoint feature is absent')
 def prep(self,values=None):return m.prepare(*(values or fixtures()),NOW)
 def test_native_cli401_and_unknown_nested_inventory_continue_without_remote_authority(self):
  r=self.prep();self.assertEqual(r['action'],'CONTINUE_NATIVE');self.assertIsNone(r['request']);self.assertFalse(any(r['authorities'].values()))
 def test_known_effect_precedes_stale_setup_and_cli401(self):
  for state,action in [('submitting','OBSERVE_EXISTING'),('unknown','OBSERVE_EXISTING'),('running','OBSERVE_EXISTING'),('waiting_report','INTAKE_EXISTING'),('CORRUPT','RECONCILE_EXISTING'),('failed','RECONCILE_EXISTING')]:
   v=fixtures();v[1]['restored'].update(mode='COMPUTE_ONLY',operation_key=KEY,journal_state=state,journal_ref='fixture:exact-journal',journal_digest=D({'state':state}),intent_ref='fixture:intent',guard_ref='fixture:guard',task_id='task_e_'+'b'*32);v[0]['setup']['fingerprint']='sha256:'+'9'*64
   with self.subTest(state=state):r=self.prep(v);self.assertIn(r['action'],[action,'RECONCILE_EXISTING']);self.assertEqual(r['operation_key'],KEY);self.assertIsNone(r['request'])
 def test_conflicting_mode_and_missing_known_journal_require_reconciliation(self):
  v=fixtures();v[1]['restored'].update(mode='DEVELOPMENT',operation_key=KEY,journal_state='running',journal_ref=None,guard_ref='fixture:guard');self.assertEqual(self.prep(v)['action'],'RECONCILE_EXISTING')
 def test_incomplete_native_source_recovery_blocked(self):
  v=fixtures();v[1]['live_recovery']['source']['complete']=False;self.assertEqual(self.prep(v)['action'],'BLOCKED')
 def test_native_prepared_payload_is_deep_copy(self):
  v=fixtures();r=self.prep(v);v[1]['checks'][0]['argv'][2]='changed';self.assertEqual(r['context_projection']['checks'][0]['argv'][2],'print("Привет мир")')
 def test_wrong_namespace_cannot_be_cli_request(self):
  v=fixtures();v[1]['access_mode']='official_cli';v[0]['environments']['official_cli']['provider_namespace']='managed_cloud_runtime'
  with self.assertRaises(ValueError):self.prep(v)
 def test_context_unknown_keys_and_untrimmed_argv_rejected(self):
  for change in ['extra','argv']:
   v=fixtures()
   if change=='extra':v[1]['cached_lease']=True
   else:v[1]['checks'][0]['argv'][0]=' python '
   with self.subTest(change=change),self.assertRaises(ValueError):self.prep(v)
 def test_remote_without_existing_intent_never_ready(self):
  v=fixtures();v[1]['access_mode']='official_cli';v[2]['access_modes']['official_cli']['status']='ready';self.assertEqual(self.prep(v)['action'],'BLOCKED')
 def test_prepare_never_issues_transport_calls(self):self.assertFalse(self.prep()['authorities']['external_start'])
 def test_submit_rejects_native_and_mutation_before_callback(self):
  r=self.prep()
  class NoCalls:
   def submit(self,*a,**kw):raise AssertionError('transport called')
  with self.assertRaises(ValueError):m.submit(r,NoCalls(),read_preflight=lambda:None,launch_authorized=lambda:None,clock=lambda:NOW)
 def test_ui_never_delegates_to_cli_submission(self):
  v=fixtures();v[1]['access_mode']='official_ui';self.assertNotEqual(self.prep(v)['action'],'READY_FOR_SUBMIT')
if __name__=='__main__':unittest.main()
