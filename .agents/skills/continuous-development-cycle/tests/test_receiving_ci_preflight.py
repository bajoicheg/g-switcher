"""Receiving event coverage includes cumulative PR paths and default workflow_run."""
import importlib,importlib.util,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

class ReceivingPredicatesTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('receiving_ci_preflight'),'native receiving preflight is missing')
  return importlib.import_module('receiving_ci_preflight')
 def workflows(self):
  return {'dev.yml':"name: Developer Tools\non:\n  pull_request:\n    paths: ['tools/dev/**']\njobs:\n  check:\n    if: needs.changed.outputs.dev_tools == 'true'\n    runs-on: ubuntu-latest\n    steps: []\n",'push-full.yml':"name: Legacy FULL\non:\n  push:\n    branches: [main, historical-full]\njobs:\n  full:\n    runs-on: ubuntu-latest\n    steps: []\n"}
 def inspect(self,**changes):
  args={'branch':'design/current','pr_base_branch':'main','push_paths':['.agents/skills/continuous-development-cycle/VERSION'],'cumulative_pr_paths':['tools/dev/Invoke-DevCheck.ps1','.agents/skills/continuous-development-cycle/VERSION'],'head_workflows':self.workflows(),'default_workflows':{'release.yml':"name: Post check\non:\n  workflow_run:\n    workflows: ['Developer Tools']\n    types: [completed]\n    branches: ['design/current']\njobs:\n  post:\n    runs-on: ubuntu-latest\n    steps: []\n"}}
  args.update(changes);return self.module().predict(**args)
 def test_cumulative_pr_paths_select_dev_check_even_when_last_delta_is_only_package(self):
  result=self.inspect();self.assertIn(('dev.yml','pull_request'),[(x['path'],x['event']) for x in result['required_cycles']])
  self.assertNotIn(('push-full.yml','push'),[(x['path'],x['event']) for x in result['required_cycles']])
  self.assertFalse(result['authorizes_writer_start'])
 def test_default_branch_workflow_run_is_not_replaced_by_head_definition(self):
  workflows=self.workflows();workflows['release.yml']='name: disabled on head\non: workflow_dispatch\njobs: {}\n'
  result=self.inspect(head_workflows=workflows)
  self.assertIn(('release.yml','workflow_run'),[(x['path'],x['event']) for x in result['required_cycles']])
 def test_job_expression_uncertainty_cannot_suppress_mandatory_receiving_gate(self):
  result=self.inspect();dev=next(x for x in result['required_cycles'] if x['path']=='dev.yml')
  self.assertEqual(dev['jobs'][0]['predicate'],'possible_requires_provider_reconciliation')
 def test_changed_path_only_last_delta_does_not_claim_cumulative_pr_coverage(self):
  with self.assertRaisesRegex(ValueError,'cumulative'):
   self.inspect(cumulative_pr_paths=None)
 def test_unknown_event_filter_or_invalid_workflow_fails_closed(self):
  with self.assertRaises(ValueError):self.inspect(head_workflows={'broken.yml':'on: [pull_request\n'})
  with self.assertRaisesRegex(ValueError,'filter'):
   self.inspect(head_workflows={'x.yml':"on:\n  pull_request:\n    unknown-path-filter: x\njobs: {}\n"})
 def test_pr_target_uses_authenticated_base_definition_not_head(self):
  base={'security.yml':"name: Base security\non: pull_request_target\njobs: {scan: {runs-on: ubuntu-latest, steps: []}}\n"}
  result=self.inspect(head_workflows={},default_workflows={},pr_base_workflows=base)
  self.assertIn(('security.yml','pull_request_target'),[(x['path'],x['event']) for x in result['required_cycles']])
 def test_github_cloud_diff_cutoff_preserves_possible_path_gates(self):
  result=self.inspect(cumulative_pr_paths=['irrelevant/'+str(i) for i in range(3001)])
  dev=next(x for x in result['required_cycles'] if x['path']=='dev.yml')
  self.assertIn('provider_diff_limit',dev['coverage_reason'])
 def test_github_optional_character_filters_never_report_false_skip(self):
  workflow={'frontend.yml':"name: Frontend checks\non:\n  pull_request:\n    paths: ['*.jsx?']\njobs: {check: {runs-on: ubuntu-latest, steps: []}}\n"}
  for path in ['page.js','page.jsx']:
   with self.subTest(path=path),self.assertRaisesRegex(ValueError,'unsupported.*pattern'):
    self.inspect(push_paths=[path],cumulative_pr_paths=[path],head_workflows=workflow,default_workflows={})

class ReceivingWriterIngressTests(unittest.TestCase):
 def test_missing_receiving_preflight_fails_before_native_writer_admission(self):
  import test_managed_host_bridge as native
  import managed_host_bridge as bridge
  fixture=native.ManagedHostBridgeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  request=fixture.start_request();request['plan']['tasks'][0]['write_paths']=['docs','.agents/skills/continuous-development-cycle']
  with self.assertRaisesRegex(ValueError,'BEFORE.*admission'):bridge.start(request)
  self.assertEqual(fixture.lease_store.read()[1]['generation'],0)
  self.assertFalse((fixture.root/'handles').exists())

class NativeReceivingAdmissionTests(unittest.TestCase):
 def setUp(self):
  import test_release_delivery_git as original
  import receiving_ci_preflight as receiving
  from git_lease_store import GitLeaseStore
  from git_document_store import GitDocumentStore
  import execution_lease_v2 as lease, budget, json, hashlib
  from datetime import datetime,timezone
  from live_target import GitSource
  self.fixture=original.GitDeliveryTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  f=self.fixture;self.m=receiving;self.at=datetime.now(timezone.utc)
  self.store=GitLeaseStore(f.work,'origin','refs/heads/cdc/preflight-lease')
  revision=self.store.compare_and_swap(None,lease.initialize('owner/product','refs/heads/main'))
  self.ledger=budget.new_ledger('receiving-task','receiving-wake',json.loads((Path(__file__).resolve().parents[1]/'templates/budget-ledger.json').read_text())['policy'])
  self.ledger_path='budget-ledger.json';self.save_ledger(self.ledger)
  ref='refs/heads/cdc/receiving-api-'+hashlib.sha256(b'owner/product\nrefs/heads/main').hexdigest()
  self.api_store=GitDocumentStore(f.work,'origin',ref,f.remote_id)
  reads=[]
  for suffix,value in [('',{'full_name':'owner/product','default_branch':'main'}),('/pulls?state=open&per_page=100',[])]:
   raw=json.dumps(value);reads.append({'schema':'provider-get-receipt/v1','transport':'github_connector','tool_name':'github_fetch','path':'repos/owner/product'+suffix,'observed_at_utc':self.at.isoformat(),'raw_response':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest()})
  doc={'schema':'canonical-provider-reads/v1','repository':'owner/product','source_ref':'refs/heads/main','lease_revision':self.store.read()[0],'reads':reads}
  self.api_revision=self.api_store.compare_and_swap(None,doc)
  self.api=receiving.CanonicalProviderReads(self.store,'refs/heads/main',self.api_revision,clock=lambda:self.at)
  self.source=GitSource(f.work,'origin',f.remote_id)
  # Reuse the authenticated native canonical release verification, not a caller tree label.
  f.delivery._verify_release(f.bindings['3.3.1'])
  f.canonical_source.clock=receiving._now
 def save_ledger(self,ledger):
  import json
  f=self.fixture;rev,_=self.store.read()
  rows=f.git(f.work,'ls-tree',rev).splitlines();rows=[r for r in rows if not r.endswith('\t'+self.ledger_path)]
  blob=f.git(f.work,'hash-object','-w','--stdin',input=json.dumps(ledger)+'\n')
  tree=f.git(f.work,'mktree',input='\n'.join(rows+['100644 blob '+blob+'\t'+self.ledger_path])+'\n')
  commit=f.git(f.work,'commit-tree',tree,'-p',rev,input='Authentic fixture control ledger\n')
  f.git(f.work,'push','-q','origin',commit+':'+self.store.ref)
 def preflight(self):
  f=self.fixture;b=f.bindings['3.3.1']
  return self.m.prepare_admission(self.source,self.store,release_commit=b['release_commit'],package_tree=b['package_tree'],canonical_source=f.canonical_source,release_binding=b,transaction_id='native-receiving-case',ledger_path=self.ledger_path,provider=self.api)
 def reserve(self,preflight,key=None):
  import budget
  event={'type':'reserve','event_id':'receiving-ci-a1','attempt_id':'receiving-ci-a1','task_id':'receiving-task','wake_id':'receiving-wake','at_utc':self.at.isoformat().replace('+00:00','Z'),'operation_key':key or preflight.reservation_descriptor()['operation_key'],'kind':'ci_start','scope':'native-receiving-case','recovery_ref':None,'cost':{'elapsed_seconds':None,'tokens':None,'tool_calls':1}}
  self.ledger=budget.apply_event(self.ledger,event);self.save_ledger(self.ledger)
 def test_native_released_preflight_requires_actual_cycle_reservation(self):
  pre=self.preflight()
  with self.assertRaisesRegex(ValueError,'reservation'):pre.admit('receiving-ci-a1')
  self.reserve(pre);admitted=pre.admit('receiving-ci-a1')
  self.assertEqual(admitted.snapshot.revision,self.fixture.source)
  self.assertFalse(pre.reservation_descriptor()['authorizes_writer_start'])
 def test_missing_policy_controls_rejected_before_admission(self):
  f=self.fixture;f.git(f.work,'rm','-q','docs/development-cycle.yaml');f.commit(f.work);f.git(f.work,'push','-q','origin','main')
  with self.assertRaisesRegex(ValueError,'control|Git source'):self.preflight()
 def test_unverified_canonical_release_cannot_supply_budget_descriptor(self):
  f=self.fixture;b=dict(f.bindings['3.3.1']);b['release_commit']=f.bindings['3.3.0']['release_commit']
  with self.assertRaisesRegex(ValueError,'release|binding'):self.m.prepare_admission(self.source,self.store,release_commit=b['release_commit'],package_tree=b['package_tree'],canonical_source=f.canonical_source,release_binding=b,transaction_id='native-receiving-case',ledger_path=self.ledger_path,provider=self.api)
 def test_mismatched_cycle_key_and_consumed_reservation_cannot_rearm(self):
  import budget
  pre=self.preflight();self.reserve(pre,key='sha256:'+'f'*64)
  with self.assertRaisesRegex(ValueError,'reservation'):pre.admit('receiving-ci-a1')
 def owned_delivery(self):
  import execution_lease_v2 as lease
  from unittest import mock
  import release_delivery
  pre=self.preflight();self.reserve(pre);admission=pre.admit('receiving-ci-a1')
  f=self.fixture;revision,record=self.store.read()
  stamp=self.m._stamp(self.m._now())
  invocation={'invocation_id':'native-receiving-fixture','automation_id':None,'conversation_id':'fixture','execution_surface':'managed','started_at_utc':stamp}
  # This existing unit-fixture capability adapter does not claim a provider launch.
  with mock.patch.object(lease.terminal_capability_api,'validate_verified',return_value={}):
   record=lease.acquire(record,'11111111-1111-4111-8111-111111111111',stamp,invocation=invocation,terminal_capability=object())
   revision=self.store.compare_and_swap(revision,record,ownership_capability=object())
  ownership={'expected_revision':revision,'repository':'owner/product','source_ref':'refs/heads/main','owner_id':record['owner_id'],'generation':record['generation'],'invocation_id':invocation['invocation_id']}
  delivery=release_delivery.GitReleaseDelivery(f.work,'origin','refs/heads/main',f.remote_id,f.canonical_source,'owner/cdc',self.store,ownership,f.attempt,f.assembly,receiving_admission=admission)
  return delivery,admission
 def test_original_prepared_cycle_confirms_lost_reply_without_rebinding(self):
  from unittest import mock
  delivery,admission=self.owned_delivery();f=self.fixture
  prepared=delivery.prepare(f.bindings['3.3.1'],expected_head=f.source,transaction_id='native-receiving-case',operation_budget=100)
  push=delivery.publisher._push
  def lost_reply(*args):push(*args);raise ValueError('synthetic lost reply after authentic Git effect')
  with mock.patch.object(delivery.publisher,'_push',side_effect=lost_reply) as effect:
   self.assertEqual(delivery.publish(prepared)['action'],'CONFIRMED_FROM_READBACK');self.assertEqual(effect.call_count,1)
  revision,record=admission._cycle_store().read()
  with mock.patch.object(delivery.publisher,'_push',side_effect=AssertionError('replay forbidden')):
   self.assertEqual(delivery.publish(prepared)['published_head'],prepared['state']['candidate_commit'])
  self.assertEqual(admission._cycle_store().read(),(revision,record))
  changed=__import__('copy').deepcopy(prepared);changed['state']['candidate_commit']=f.source
  with self.assertRaisesRegex(ValueError,'rebinding'):admission.bind_prepared(changed,delivery.ownership)
 def test_cycle_binding_rechecks_owner_at_actual_cas_effect(self):
  from unittest import mock
  import execution_lease_v2 as lease
  from git_document_store import GitDocumentStore
  delivery,admission=self.owned_delivery();f=self.fixture
  original=GitDocumentStore._git;changed=False
  def race(store,*args,**kwargs):
   nonlocal changed
   # Inject drift just before the checked store's push call enters its guard.
   if 'commit-tree' in args and store.ref.startswith('refs/heads/cdc/receiving-cycle-') and not changed:
    changed=True;rev,doc=self.store.read();doc=lease.renew(doc,delivery.ownership['owner_id'],1,delivery.ownership['invocation_id'],self.m._stamp(self.m._now()),activity_ref='fixture:actual-owner-renewal');self.store.compare_and_swap(rev,doc)
   return original(store,*args,**kwargs)
  with mock.patch.object(GitDocumentStore,'_git',race):
   with self.assertRaisesRegex(ValueError,'stale coordination'):delivery.prepare(f.bindings['3.3.1'],expected_head=f.source,transaction_id='native-receiving-case',operation_budget=100)
  self.assertTrue(changed);self.assertEqual(admission._cycle_store().read(),(None,None));self.assertEqual(f.remote_head(),f.source)
 def test_terminal_cycle_charge_cannot_be_rearmed(self):
  import budget
  pre=self.preflight();self.reserve(pre)
  event={'type':'outcome','event_id':'receiving-ci-terminal','task_id':'receiving-task','wake_id':'receiving-wake','at_utc':self.m._stamp(self.m._now()),'reservation_id':'receiving-ci-a1','status':'unknown','usage':{'tokens':None,'elapsed_seconds':None},'failure':None}
  self.ledger=budget.apply_event(self.ledger,event);self.save_ledger(self.ledger)
  with self.assertRaisesRegex(ValueError,'cannot rearm'):pre.admit('receiving-ci-a1')
 def test_provider_raw_bytes_and_scope_cannot_be_substituted(self):
  revision,doc=self.api_store.read();doc['reads'][0]['raw_response']='{"full_name":"other/project"}'
  self.api_revision=self.api_store.compare_and_swap(revision,doc)
  self.api=self.m.CanonicalProviderReads(self.store,'refs/heads/main',self.api_revision,clock=lambda:self.at)
  with self.assertRaisesRegex(ValueError,'bytes'):self.preflight()

if __name__=='__main__':unittest.main()
