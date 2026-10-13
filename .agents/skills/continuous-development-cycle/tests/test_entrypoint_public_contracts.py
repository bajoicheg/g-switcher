"""Typed entrypoint caller/public invocation contracts; provider fixtures simulated."""
import copy,io,json,sys,tempfile,unittest
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_cloud_entrypoint as m
import recovery_recipes as r
from test_codex_cloud_entrypoint import fixtures,NOW
from test_recovery_recipes_v2 import B,H,C,DIAG,PARAMS,event,D

class PublicCallerContracts(unittest.TestCase):
 def test_verified_recipe_reuses_bound_evidence_and_typed_exact_next_check(self):
  p,c,q,reg,policy,route=fixtures();b=copy.deepcopy(B);b.update(repository=c['repository'],environment_id=p['environments']['native_runtime']['id'],toolchain_fingerprint=c['recovery']['bindings']['toolchain_fingerprint'],policy_digest=p['policy_digest']);history=copy.deepcopy(H);history['repository']=c['repository'];catalog=copy.deepcopy(C);recipe=catalog['recipes'][0]
  b['input_digests']['cloud-profile:native_runtime']=m.profile_api.profile_binding_digest(p,'native_runtime')
  recipe['scope'].update(repository=b['repository'],environment_id=b['environment_id'],toolchain_fingerprint=b['toolchain_fingerprint'],policy_digest=b['policy_digest']);recipe['provenance']['verified_at_utc']=NOW
  diag=dict(DIAG,code='known_failure');selected=r.select(catalog,diag,bindings=b,now_utc=NOW,history=history,new_signal=None);plan=r.action_plan(selected,diag,b,history,PARAMS)
  ev=event(plan,outcome='verified');ev.update(at_utc=NOW,subject=r._subject(diag,b),evidence_ref='evidence:actual-bound-verified-result',evidence_digest=recipe['provenance']['evidence_sha256']);history=r.append_history(history,ev)
  c['recovery'].update(catalog_ref='git:catalog',catalog=catalog,diagnosis=diag,history_ref='git:history',history=history,bindings=b)
  result=m.prepare(p,c,q,reg,policy,route,NOW);decision=result['recovery_decision'];self.assertEqual(decision['status'],'PLANNED');self.assertEqual(decision['selection']['reason'],'verified_evidence_reused');params=decision['action_plan']['parameters'];self.assertEqual(set(params),{'next_action_ref','evidence_ref'});self.assertEqual(params['evidence_ref'],ev['evidence_ref']);self.assertEqual(params['next_action_ref'],'cloud-entry-check:'+m._hash({'repository':c['repository'],'source_ref':c['source_ref'],'exact_sha':c['exact_sha'],'check':c['checks'][0]}));self.assertFalse(any(decision['action_plan']['authorities'].values()))
 def test_documented_expanded_policy_flag_runs_real_loader_without_provider_calls(self):
  values=fixtures();names=('profile',*m.INPUT_NAMES)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   for name,value in zip(names,values):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False))
   args=['prepare','--project-root',str(root),'--profile','profile.json','--now',NOW]
   for name in m.INPUT_NAMES:args+=['--policy' if name=='routing_policy' else '--'+name.replace('_','-'),name+'.json']
   stdout=io.StringIO();stderr=io.StringIO()
   with redirect_stdout(stdout),redirect_stderr(stderr):exit_code=m.main(args)
   self.assertEqual(exit_code,0);result=json.loads(stdout.getvalue());self.assertEqual(result['action'],'CONTINUE_NATIVE');self.assertFalse(any(result['authorities'].values()));self.assertIn('FIXTURE CLOCK',stderr.getvalue());self.assertEqual(result['context_projection']['checks'][0]['argv'],values[1]['checks'][0]['argv'])
if __name__=='__main__':unittest.main()
