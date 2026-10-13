"""Actual isolated local Git/loader contracts; provider observations simulated."""
import copy,hashlib,json,subprocess,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_cloud_entrypoint as m
import test_codex_cloud_entrypoint as entry
from test_recovery_recipes_v2 import H,event,selection,DIAG,B,PARAMS,C
import recovery_recipes as recipes
from git_document_store import GitDocumentStore
from git_remote_identity import remote_identity

class IOHistoryContracts(unittest.TestCase):
    def materialize(self,root):
        values=entry.fixtures();names=('profile','context','probe','registry','routing_policy','routing_context');refs={}
        for name,value in zip(names,values):
            raw=json.dumps(value,ensure_ascii=False).encode();(root/(name+'.json')).write_bytes(raw)
            if name!='profile':refs[name]={'path':name+'.json','sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}
        document={'schema':'cloud-entry-inputs/v1',**refs};(root/'inputs.json').write_text(json.dumps(document));return document

    def test_load_inputs_hash_bound_detached_and_no_outside_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);document=self.materialize(root);loaded=m.load_inputs(root/'inputs.json',project_root=root)
            self.assertEqual(loaded['context']['checks'][0]['argv'][2],'print("Привет мир")')
            document['context']['path']='../outside.json';(root/'inputs.json').write_text(json.dumps(document))
            with self.assertRaises(ValueError):m.load_inputs(root/'inputs.json',project_root=root)

    def test_load_rejects_hash_mismatch_symlink_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);document=self.materialize(root);(root/'context.json').write_text('{}')
            with self.assertRaises(ValueError):m.load_inputs(root/'inputs.json',project_root=root)
            self.materialize(root);(root/'context-link.json').symlink_to(root/'context.json');document['context']['path']='context-link.json';(root/'inputs.json').write_text(json.dumps(document))
            with self.assertRaises(ValueError):m.load_inputs(root/'inputs.json',project_root=root)
            (root/'inputs.json').write_text('{"schema":"cloud-entry-inputs/v1","schema":"cloud-entry-inputs/v1"}')
            with self.assertRaises(ValueError):m.load_inputs(root/'inputs.json',project_root=root)

    def test_handoff_has_single_bound_next_action_and_no_authority(self):
        p,c,*rest=entry.fixtures();prepared=m.prepare(p,c,*rest,entry.NOW)
        h={'schema':'cloud-entrypoint-handoff/v1','repository':c['repository'],'source_ref':c['source_ref'],'exact_sha':c['exact_sha'],'profile_ref':'git:profile','profile_digest':m._hash(p),'operation_key':prepared['operation_key'],'task_mode':c['task_mode'],'access_mode':c['access_mode'],'restore_ref':'git:restore','restore_digest':prepared['restore_digest'],'recovery_history_ref':c['recovery']['history_ref'],'task':{'id':c['task_id'],'url':None,'mode':c['task_mode']},'phase':'native-check','journal_ref':None,'guard_ref':None,'budget_ref':'git:budget','recipe_ref':None,'next_action':prepared['next_action']}
        self.assertEqual(m.validate_handoff(h),h)
        h['next_action']=[prepared['next_action'],prepared['next_action']]
        with self.assertRaises(ValueError):m.validate_handoff(h)

    def test_history_real_git_cas_requires_callback_and_preserves_terminal_event(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);repo=root/'repo';bare=root/'remote.git'
            def git(*args):return subprocess.run(['git',*args],check=True,capture_output=True,text=True).stdout.strip()
            git('init','--bare',str(bare));git('init',str(repo));git('-C',str(repo),'remote','add','origin',str(bare))
            store=GitDocumentStore(repo,'origin','refs/heads/cdc/history',remote_identity(repo,'origin'))
            rev=store.compare_and_swap(None,H);plan=recipes.action_plan(selection(),DIAG,B,H,PARAMS);ev=event(plan)
            with self.assertRaises(ValueError):m.record_history(store,rev,ev,read_authorization=None)
            self.assertEqual(store.read()[0],rev)
            def rejected():raise ValueError('actual test callback rejects')
            with self.assertRaises(ValueError):m.record_history(store,rev,ev,read_authorization=rejected)
            self.assertEqual(store.read()[0],rev)
            observed=[]
            new=m.record_history(store,rev,ev,read_authorization=lambda:observed.append('checked'))
            self.assertEqual(observed,['checked']);self.assertEqual(new['history']['events'],[ev]);self.assertEqual(store.read(),(new['revision'],new['history']))
            with self.assertRaises(ValueError):m.record_history(store,rev,ev,read_authorization=lambda:None)
            self.assertEqual(store.read(),(new['revision'],new['history']))

    def test_caller_freshly_selects_consumed_diagnostic_and_preserves_blocker(self):
        p,c,q,reg,policy,route=entry.fixtures();b=copy.deepcopy(B);b.update(repository=c['repository'],environment_id=p['environments']['native_runtime']['id'],toolchain_fingerprint=c['recovery']['bindings']['toolchain_fingerprint'],policy_digest=p['policy_digest'])
        b['input_digests']['cloud-profile:native_runtime']=m.profile_api.profile_binding_digest(p,'native_runtime')
        history=copy.deepcopy(H);history['repository']=c['repository'];catalog=copy.deepcopy(C)
        c['recovery'].update(catalog_ref='git:catalog',catalog=catalog,diagnosis=DIAG,history_ref='git:history',history=history,bindings=b)
        first=m.prepare(p,c,q,reg,policy,route,entry.NOW);decision=first['recovery_decision'];self.assertEqual(decision['action_plan']['handler'],'inspect_exact_invocation')
        ev=event(decision['action_plan']);ev['at_utc']=entry.NOW;ev['subject']=recipes._subject(DIAG,b);history=recipes.append_history(history,ev);c['recovery']['history']=history
        again=m.prepare(p,c,q,reg,policy,route,entry.NOW);self.assertEqual(again['action'],'BLOCKED');self.assertEqual(again['recovery_decision']['selection']['reason'],'recovery_observation_consumed')
        self.assertEqual(again['recovery_decision']['action_plan']['parameters']['evidence_ref'],ev['evidence_ref'])

if __name__=='__main__':unittest.main()
