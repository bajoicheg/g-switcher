"""Pure synthetic handoff contracts; no authority or provider effects."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_cloud_entrypoint as m
import test_codex_cloud_entrypoint as entry
D='sha256:'+'a'*64
K='sha256:'+'b'*64
def handoff():
 p,c,*rest=entry.fixtures();prepared=m.prepare(p,c,*rest,entry.NOW)
 return {'schema':'cloud-entrypoint-handoff/v1','repository':c['repository'],'source_ref':c['source_ref'],'exact_sha':c['exact_sha'],'profile_ref':'git:profile','profile_digest':m._hash(p),'operation_key':None,'task_mode':c['task_mode'],'access_mode':c['access_mode'],'restore_ref':'git:restore','restore_digest':prepared['restore_digest'],'recovery_history_ref':None,'task':{'id':c['task_id'],'url':None,'mode':c['task_mode']},'phase':'native-check','journal_ref':None,'guard_ref':None,'budget_ref':'git:budget','recipe_ref':None,'next_action':prepared['next_action']}
class Handoff(unittest.TestCase):
 def reject(self,mutate):
  h=handoff();mutate(h)
  with self.assertRaises(ValueError):m.validate_handoff(h)
 def test_complete_handoff_preserved_and_deep_copied(self):
  h=handoff();r=m.validate_handoff(h);self.assertEqual(r,h);r['next_action']['parameters']['argv'].append('changed');self.assertNotEqual(r,h)
 def test_six_fields_required(self):
  for key in ['operation_key','task_mode','access_mode','restore_ref','restore_digest','recovery_history_ref']:
   self.reject(lambda h:h.pop(key))
 def test_invalid_typed_fields(self):
  for key,value in [('operation_key','unknown'),('task_mode','COMPUTE'),('access_mode','cloud'),('restore_digest','a'*64),('recovery_history_ref',4)]:self.reject(lambda h,k=key,v=value:h.update({k:v}))
 def test_task_mode_consistency(self):self.reject(lambda h:h['task'].update(mode='DEVELOPMENT'))
 def test_restore_pair_required(self):self.reject(lambda h:h.update(restore_ref=None))
 def test_verification_key_and_sha_consistency(self):
  self.reject(lambda h:h['next_action']['verification'].update(expected_operation_key=K))
  self.reject(lambda h:h['next_action']['verification'].update(exact_sha='f'*40))
 def test_no_unknown_verification_fields(self):self.reject(lambda h:h['next_action']['verification'].update(authority=True))
 def test_native_parameters_strict_and_argv_not_trimmed(self):
  self.reject(lambda h:h['next_action']['parameters'].update(shell='run'))
  self.reject(lambda h:h['next_action']['parameters'].update(argv=[' python ']))
 def test_native_handler_not_remote_mode(self):self.reject(lambda h:h.update(access_mode='official_cli'))
 def operation(self,handler):
  h=handoff();h.update(operation_key=K,journal_ref='git:journal',access_mode='official_cli');h['next_action']={'handler':handler,'parameters':{'operation_key':K,'task_mode':h['task_mode'],'journal_ref':'git:journal'},'required_scope_ref':None,'verification':{'expected_operation_key':K,'exact_sha':h['exact_sha']}};return h
 def test_each_existing_operation_handler_exact_binding(self):
  for handler in ['observe_existing_operation','reconcile_existing_operation','intake_existing_result']:
   h=self.operation(handler);self.assertEqual(m.validate_handoff(h),h)
   for key,value in [('operation_key',D),('task_mode','DEVELOPMENT'),('journal_ref','git:other')]:
    changed=copy.deepcopy(h);changed['next_action']['parameters'][key]=value
    with self.assertRaises(ValueError):m.validate_handoff(changed)
 def test_submit_requires_cli_and_exact_routing_verification(self):
  h=self.operation('submit_existing_transport');h['next_action']['parameters'].pop('journal_ref');h['next_action']['verification'].update(routing_policy_digest=D,routing_context_digest=D,registry_digest=D);self.assertEqual(m.validate_handoff(h),h)
  h['access_mode']='native_runtime'
  with self.assertRaises(ValueError):m.validate_handoff(h)
 def test_unknown_recovery_decision_parameters_rejected(self):
  h=handoff();h['next_action']['handler']='execute_existing_recovery_plan';h['next_action']['parameters']={'decision':{'arbitrary_shell':'run'}}
  with self.assertRaises(ValueError):m.validate_handoff(h)
 def test_nullable_unadmitted_refs_valid(self):
  h=handoff();h.update(restore_ref=None,restore_digest=None);self.assertEqual(m.validate_handoff(h),h)
 def recovery(self):
  from test_recovery_recipes_v2 import selection,DIAG,B,H,PARAMS
  import recovery_recipes as recipes
  h=handoff();sel=selection();plan=recipes.action_plan(sel,DIAG,B,H,PARAMS)
  h['recovery_history_ref']='git:history'
  h['next_action'].update(handler='execute_existing_recovery_plan',parameters={'decision':{'status':'PLANNED','reason':sel['reason'],'selection':sel,'action_plan':plan,'history_ref':'git:history','history_digest':m._hash(H),'new_signal_ref':None,'completed_correction_ref':None}})
  return h
 def test_allowlisted_recovery_handoff_valid(self):
  h=self.recovery();self.assertEqual(m.validate_handoff(h),h)
 def test_recovery_history_and_typed_parameters_preserved(self):
  for mutate in [lambda d:d.update(history_ref='git:other'),lambda d:d['action_plan']['parameters'].update(shell='arbitrary'),lambda d:d['action_plan']['authorities'].update(product_write=True)]:
   h=self.recovery();mutate(h['next_action']['parameters']['decision'])
   with self.assertRaises(ValueError):m.validate_handoff(h)
 def test_recovery_selection_reason_and_signal_consistency(self):
  for mutate in [lambda d:d.update(reason='unrelated'),lambda d:d.update(new_signal_ref='git:forged')]:
   h=self.recovery();mutate(h['next_action']['parameters']['decision'])
   with self.assertRaises(ValueError):m.validate_handoff(h)
 def test_blocked_selection_cannot_carry_diagnostic_plan(self):
  h=self.recovery();d=h['next_action']['parameters']['decision'];d['status']='BLOCKED';d['selection']['action']='blocked'
  with self.assertRaises(ValueError):m.validate_handoff(h)
 def test_ready_intent_key_matches_action_and_handoff(self):
  from test_cloud_entry_review_regressions import remote_values
  p,c,q,registry,policy,route=remote_values()
  prepared=m.prepare(p,c,q,registry,policy,route,entry.NOW);self.assertEqual(prepared['action'],'READY_FOR_SUBMIT')
  self.assertEqual(prepared['operation_key'],entry.KEY);self.assertEqual(prepared['next_action']['parameters']['operation_key'],entry.KEY)
  self.assertEqual(prepared['next_action']['verification']['expected_operation_key'],entry.KEY)
  h=handoff();h.update(operation_key=entry.KEY,access_mode='official_cli',next_action=prepared['next_action']);self.assertEqual(m.validate_handoff(h),h)
if __name__=='__main__':unittest.main()
