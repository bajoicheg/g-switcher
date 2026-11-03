"""Native adoption observations against isolated genuine Git histories."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import budget
import execution_lease as legacy_lease
import execution_lease_v2 as lease
import operation_intent as operation
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore, validate_coordination_transition
from git_remote_identity import remote_identity
from live_target import GitSource
from project_budget_store import GitProjectBudgetStore, ledger_digest
from validate_adapter import validate_adapter

SOURCE = 'refs/heads/work/retained'
CONTROL = 'refs/heads/cdc/coordination'
AUTHORITY = 'refs/heads/cdc/owner-scope'
OWNER = '11111111-1111-4111-8111-111111111111'
INVOCATION = 'managed-terminal:fixture-invocation'
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class ProjectAdoptionTests(unittest.TestCase):
    def setUp(self):
        for attribute in ('control_head', 'source_sha'):
            if hasattr(self, attribute): delattr(self, attribute)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bare = self.root / 'remote.git'; self.repo = self.root / 'cache'
        self.git(self.root, 'init', '--bare', str(self.bare)); self.git(self.root, 'init', str(self.repo))
        self.git(self.repo, 'config', 'user.name', 'Fixture'); self.git(self.repo, 'config', 'user.email', 'fixture@example.invalid')
        for remote in ['source', 'coordination', 'authority']: self.git(self.repo, 'remote', 'add', remote, str(self.bare))
        self.endpoint = remote_identity(self.repo, 'coordination'); self.now = NOW
        policy = {'task_limits': {'compute_starts': 8, 'ci_starts': 0, 'agent_starts': 0},
                  'wake_limits': {'compute_starts': 4}, 'max_parallel_agents': 0,
                  'checkpoint_reserve': {'tokens': 0, 'tool_calls': 0},
                  'provider_max_age_seconds': 90, 'actions_budget': 'conserve'}
        self.ledger = budget.new_ledger('original-product-task', 'old-wake', policy)
        if getattr(self, 'fixture_charged', False):
            policy['task_limits'].update(ci_starts=2, agent_starts=2); policy['max_parallel_agents'] = 2
            self.ledger = budget.new_ledger('original-product-task', 'old-wake', policy)
            for kind in ['agent_start', 'ci_start']:
                self.ledger = budget.apply_event(self.ledger, {
                    'type': 'reserve', 'event_id': kind, 'task_id': self.ledger['task_id'], 'wake_id': 'old-wake',
                    'at_utc': '2026-10-13T10:00:00Z', 'operation_key': 'sha256:' + hashlib.sha256(kind.encode()).hexdigest(),
                    'attempt_id': kind + '-a1', 'kind': kind, 'scope': 'original-product-task',
                    'recovery_ref': None, 'cost': {'tool_calls': 1, 'tokens': None, 'elapsed_seconds': None}})
        if getattr(self, 'fixture_prelease', False):
            (self.repo/'product.txt').write_text('original Source');self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','Source before coordination')
            self.git(self.repo,'checkout','-b','source-side');(self.repo/'side.txt').write_text('Source branch');self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','Source side ancestry')
            self.git(self.repo,'checkout','-b','source-primary','HEAD~1');(self.repo/'primary.txt').write_text('Source primary');self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','Source primary ancestry')
            self.git(self.repo,'merge','--no-ff','source-side','-m','Source merge before native initialization')
        self.initial = (legacy_lease if getattr(self, 'fixture_legacy', False) else lease).initialize('fixture/product', SOURCE)
        self.anchor = self.publish_control(self.initial)
        if getattr(self, 'fixture_opaque_history', False):
            old = copy.deepcopy(self.initial)
            old.update(owner_id='22222222-2222-4222-8222-222222222222', generation=1,
                       acquired_at_utc='2026-10-13T09:00:01Z', heartbeat_at_utc='2026-10-13T09:00:01Z',
                       expires_at_utc='2026-10-13T09:20:01Z',
                       invocation={'invocation_id':'old-watcher', 'automation_id':None, 'conversation_id':None,
                                   'execution_surface':'watchdog', 'started_at_utc':'2026-10-13T09:00:00Z'},
                       finalization={'state':'active', 'pending_shared_writes':False, 'checkpoint_ref':None,
                                     'external_reconciliation':'pending', 'completion_reason':None,
                                     'updated_at_utc':'2026-10-13T09:00:01Z', 'failure':None})
            self.publish_control(old)
            old.update(owner_id=None, acquired_at_utc=None, heartbeat_at_utc=None, expires_at_utc=None,
                       invocation=None, finalization=None, last_release={
                           'owner_id':'22222222-2222-4222-8222-222222222222', 'generation':1,
                           'invocation_id':'old-watcher', 'at_utc':'2026-10-13T09:05:00Z',
                           'checkpoint_ref':'fixture:old-checkpoint', 'external_reconciliation':'none',
                           'completion_reason':'resumable_blocker'})
            self.old_batched_revision = self.publish_control(old)
            incompatible = copy.deepcopy(old); incompatible['external_guard'] = {'old_metadata':'preserved'}
            self.old_incompatible_revision = self.publish_control(incompatible)
            self.initial = old
            self.publish_control(self.initial)
        if getattr(self, 'fixture_legacy', False):
            old=legacy_lease.acquire(self.initial,OWNER,'2026-10-13T09:00:00Z');self.publish_control(old)
            old=legacy_lease.release(old,OWNER,1,'2026-10-13T09:05:00Z');self.legacy_release_revision=self.publish_control(old)
            self.initial=lease.migrate_v1(old,'2026-10-13T09:10:00Z');self.migration_revision=self.publish_control(self.initial)
        generation=self.initial['generation']+1
        self.owned = copy.deepcopy(self.initial)
        self.owned.update(owner_id=OWNER, generation=generation, acquired_at_utc='2026-10-13T10:00:01Z',
                          heartbeat_at_utc='2026-10-13T10:00:01Z', expires_at_utc='2026-10-13T10:20:01Z',
                          invocation={'invocation_id': INVOCATION, 'automation_id': None, 'conversation_id': None if getattr(self,'fixture_metadata',False) else 'fixture',
                                      'execution_surface': 'managed', 'started_at_utc': '2026-10-13T10:00:00Z'},
                          finalization={'state': 'active', 'pending_shared_writes': False, 'checkpoint_ref': None,
                                        'external_reconciliation': 'pending', 'completion_reason': None,
                                        'updated_at_utc': '2026-10-13T10:00:01Z', 'failure': None})
        lease.validate(self.owned); self.owned_revision = self.publish_control(self.owned)
        if getattr(self,'fixture_metadata',False):
            registered=copy.deepcopy(self.owned);registered['invocation']['conversation_id']='native-registration'
            native=GitLeaseStore(self.repo,'coordination',CONTROL)
            self.control_head=native.compare_and_swap(self.owned_revision,registered)
            self.owned=registered
        self.ready = copy.deepcopy(self.owned)
        self.ready['finalization'].update(state='ready', external_reconciliation='none',
                                         checkpoint_ref='fixture:original-release-checkpoint', completion_reason='scope_complete')
        lease.validate(self.ready)
        if not getattr(self, 'fixture_bad_selected_closure', False): self.publish_control(self.ready)
        self.released = lease.release(self.ready, OWNER, generation, INVOCATION, '2026-10-13T10:00:05Z')
        self.release_revision = self.publish_control(self.released)
        self.adapter = yaml.safe_load((ROOT / 'templates/development-cycle.yaml').read_text())
        self.adapter['repository'].update(name='product', remote='fixture/product')
        self.adapter['validation']['final_platform'] = 'windows'
        self.adapter['orchestration']['execution_lease'].update(backend='git', remote='coordination', coordination_ref=CONTROL)
        self.adapter_binding = validate_adapter(self.adapter, skill_version='3.6.0')
        self.checkpoint = yaml.safe_load((ROOT / 'templates/work-status-v4.md').read_text().split('---')[1])
        self.checkpoint.update(repository='fixture/product', branch=SOURCE.removeprefix('refs/heads/'),
                               policy_revision=self.adapter_binding['policy_revision'], policy_digest=self.adapter_binding['policy_digest'],
                               observed_at_utc='2026-10-13T10:01:00Z', phase='blocked', active_change='Retained product task',
                               current_task='Complete Windows acceptance', blocker='Windows manual acceptance pending',
                               next_action='Run the original Windows acceptance kit', active_compute='none')
        self.checkpoint['control'].update(execution_lease_ref=CONTROL, execution_lease_revision=self.release_revision,
                                          lease_generation=generation, budget_ref='https://github.com/fixture/product/blob/cdc/coordination/budget.json')
        self.checkpoint['execution_continuity'].update(runnable_next_action=True, meaningful_progress=True,
                                                      completion_gate='continue', last_progress_ref='fixture:remaining-product-work')
        budget_ref=CONTROL;budget_endpoint=self.endpoint;budget_path='budget.json';budget_field=None;budget_remote='coordination'
        if getattr(self,'fixture_document_budget',False):
            budget_ref='refs/heads/cdc/original-operation';budget_path='document.json';budget_field='budget';budget_remote='budget'
            target=self.bare
            if getattr(self,'fixture_budget_endpoint',False):
                target=self.root/'original-budget.git';self.git(self.root,'init','--bare',str(target))
            self.git(self.repo,'remote','add',budget_remote,str(target));budget_endpoint=remote_identity(self.repo,budget_remote)
            self.budget_document=GitDocumentStore(self.repo,budget_remote,budget_ref,budget_endpoint,protected_refs=[SOURCE,CONTROL])
            self.anchor=self.budget_document.compare_and_swap(None,{'budget':self.ledger,'original_work':'Windows remains pending'})
            self.checkpoint['control']['budget_ref']=budget_ref+'#budget'
        self.source_sha = self.publish_source()
        self.budget_binding = {'schema': 'project-budget-binding/v1', 'repository': 'fixture/product',
                               'source_ref': SOURCE, 'coordination_ref': budget_ref, 'coordination_store_id': budget_endpoint,
                               'ledger_path': budget_path, 'budget_field': budget_field, 'task_id': self.ledger['task_id'],
                               'anchor_revision': self.anchor, 'anchor_ledger_digest': ledger_digest(self.ledger),
                               'wake_authorizations': {'connection-wake': 'owner:fixture-new-connection'}}
        self.source = GitSource(self.repo, 'source', self.endpoint, clock=lambda: self.now)
        self.lease_store = GitLeaseStore(self.repo, 'coordination', CONTROL)
        self.budget_store = GitProjectBudgetStore(self.repo, budget_remote, self.budget_binding, protected_refs=[SOURCE])
        self.authority_store = GitDocumentStore(self.repo, 'authority', AUTHORITY, self.endpoint, protected_refs=[SOURCE, CONTROL])
        self.authorization = self.authorization_record()
        self.auth_revision = self.authority_store.compare_and_swap(None, {'project_adoption_authorizations': {'product': self.authorization}})
        self.registration = self.registration_record()

    def git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()

    def publish_control(self, value):
        if hasattr(self, 'control_head'): self.git(self.repo, 'reset', '--hard', self.control_head)
        (self.repo / 'lease.json').write_text(json.dumps(value) + '\n')
        (self.repo / 'budget.json').write_text(json.dumps(self.ledger) + '\n')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '--allow-empty', '-m', 'Fixture control')
        self.control_head = self.git(self.repo, 'rev-parse', 'HEAD')
        self.git(self.repo, 'push', 'coordination', 'HEAD:' + CONTROL); return self.control_head

    def publish_source(self):
        if hasattr(self, 'source_sha'): self.git(self.repo, 'reset', '--hard', self.source_sha)
        (self.repo / 'docs/work-status').mkdir(parents=True, exist_ok=True)
        (self.repo / 'docs/development-cycle.yaml').write_text(yaml.safe_dump(self.adapter))
        (self.repo / 'docs/work-status/current.md').write_text('---\n' + yaml.safe_dump(self.checkpoint) + '---\nRetained requirements.\n')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '--allow-empty', '-m', 'Fixture Source')
        value = self.git(self.repo, 'rev-parse', 'HEAD'); self.git(self.repo, 'push', 'source', 'HEAD:' + SOURCE)
        return value

    def authorization_record(self):
        summary = budget.summarize(self.ledger)
        counts = {key: summary['task'][key] for key in ['compute_starts', 'ci_starts', 'agent_starts']}
        counts['active_agents'] = summary['active_agents']
        return {'schema': 'project-adoption-authorization/v1', 'project_id': 'product', 'repository': 'fixture/product',
                'source_ref': SOURCE, 'source_sha': self.source_sha, 'source_policy_revision': self.adapter_binding['policy_revision'],
                'source_policy_digest': self.adapter_binding['policy_digest'], 'lease_ref': CONTROL, 'lease_store_id': self.endpoint,
                'budget_binding_digest': digest(self.budget_binding), 'task_id': self.ledger['task_id'],
                'budget_policy_digest': self.ledger['policy_digest'], 'anchor_revision': self.anchor,
                'anchor_ledger_digest': ledger_digest(self.ledger), 'preserved_counts': counts,
                'owner_decision_ref': 'owner:fixture-explicit-adoption', 'owner_wake_id': 'connection-wake',
                'owner_wake_ref': 'owner:fixture-new-connection', 'scope': {'role': 'read_only', 'mode': 'COMPUTE_ONLY',
                'execution_platform': 'linux', 'ci_starts': 0, 'agent_starts': 0, 'product_writes': False, 'check_ids': ['diff-check']},
                'remaining_work': ['Original Windows acceptance remains pending']}

    def registration_record(self):
        return {'schema': 'project-adoption-registration/v1', 'project_id': 'product', 'repository': 'fixture/product',
                'source_ref': SOURCE, 'source_sha': self.source_sha, 'source_store_id': self.endpoint,
                'lease_ref': CONTROL, 'lease_store_id': self.endpoint, 'budget_binding_digest': digest(self.budget_binding),
                'authority_store_id': self.endpoint, 'authority_ref': AUTHORITY, 'authority_revision': self.auth_revision,
                'authority_path': 'project_adoption_authorizations/product', 'authority_digest': digest(self.authorization),
                'final_platform': 'windows', 'check_ids': ['diff-check']}

    def refresh_authorization(self):
        self.source_sha = self.publish_source(); self.authorization = self.authorization_record()
        revision, document = self.authority_store.read(); document['project_adoption_authorizations']['product'] = self.authorization
        self.auth_revision = self.authority_store.compare_and_swap(revision, document); self.registration = self.registration_record()

    def observe(self, **changes):
        try: native = importlib.import_module('project_adoption')
        except ModuleNotFoundError: self.fail('native sealed project-adoption observation is missing')
        arguments = {'source': self.source, 'lease_store': self.lease_store, 'budget_store': self.budget_store,
                     'policy_authority_store': self.authority_store, 'registration': self.registration, 'clock': lambda: self.now}
        arguments.update(changes); return native.observe_project_adoption(**arguments)

    def revalidate(self, proof):
        return proof.revalidate_for(self.source, self.lease_store, self.budget_store, self.authority_store, self.registration)

    def test_prelease_source_ancestry_and_merges_precede_native_boundary(self):
        self.fixture_prelease=True;self.setUp();proof=self.observe()
        self.assertEqual(self.revalidate(proof)['lease_release']['invocation_id'],INVOCATION)
        self.assertFalse(proof.payload['authorizes_launch'])
    def test_legacy_initialization_and_exact_migration_retain_native_v2_closure(self):
        self.fixture_prelease=True;self.fixture_legacy=True;self.setUp();proof=self.observe()
        self.assertEqual(proof.payload['lease_release']['generation'],2)
        self.checkpoint['control'].update(execution_lease_revision=self.legacy_release_revision,lease_generation=1)
        self.refresh_authorization()
        with self.assertRaises(ValueError):self.observe()
    def test_independently_registered_document_budget_on_distinct_channel(self):
        for split_endpoint in (False,True):
            with self.subTest(split_endpoint=split_endpoint):
                self.fixture_document_budget=True;self.fixture_budget_endpoint=split_endpoint;self.fixture_charged=True;self.setUp()
                before=self.budget_document.read();proof=self.observe();self.revalidate(proof)
                self.assertNotEqual(self.budget_binding['coordination_ref'],self.registration['lease_ref'])
                self.assertEqual(proof.payload['budget_summary']['active_agents'],1)
                self.assertEqual(proof.payload['budget_summary']['task']['ci_starts'],1)
                self.assertEqual(self.budget_document.read(),before)
    def test_native_post_acquisition_conversation_registration_is_supported(self):
        self.fixture_document_budget=True;self.fixture_metadata=True;self.setUp();proof=self.observe()
        self.assertEqual(proof.payload['lease_release']['invocation_id'],INVOCATION)
        self.assertFalse(self.revalidate(proof)['authorizes_launch'])

    def test_source_selected_closure_preserves_opaque_older_blobs_without_authority(self):
        self.fixture_opaque_history=True; self.setUp()
        old={revision:self.git(self.repo,'show',revision+':lease.json')
             for revision in [self.old_batched_revision,self.old_incompatible_revision]}
        channels=(self.lease_store.read(),self.budget_store.read(),self.source.pin(SOURCE).revision)
        proof=self.observe(); facts=self.revalidate(proof)
        self.assertEqual(facts['lease_release']['invocation_id'],INVOCATION)
        self.assertEqual(facts['lease_release']['generation'],2)
        self.assertFalse(facts['authorizes_launch']); self.assertFalse(facts['authorizes_product_acceptance'])
        self.assertEqual((self.lease_store.read(),self.budget_store.read(),self.source.pin(SOURCE).revision),channels)
        self.assertEqual({revision:self.git(self.repo,'show',revision+':lease.json') for revision in old},old)

    def test_unchanged_selected_released_snapshot_finds_actual_original_closure(self):
        self.fixture_opaque_history=True; self.setUp()
        snapshot=self.publish_control(self.released)
        self.checkpoint['control']['execution_lease_revision']=snapshot; self.refresh_authorization()
        value=self.revalidate(self.observe())
        self.assertEqual(value['lease_release_revision'],self.release_revision)
        self.assertEqual(value['checkpoint']['control']['execution_lease_revision'],snapshot)

    def test_owned_source_selected_snapshot_validates_through_its_later_closure(self):
        self.fixture_opaque_history=True; self.setUp()
        self.checkpoint.update(lease_state='active',active_executor=OWNER,
            executor_heartbeat_at_utc=self.owned['heartbeat_at_utc'],execution_lease_until_utc=self.owned['expires_at_utc'],
            active_compute='managed-host:22222222-2222-5222-8222-222222222222')
        self.checkpoint['control'].update(executor_id=OWNER,execution_lease_revision=self.owned_revision)
        self.checkpoint['execution_continuity']['invocation_id']=INVOCATION; self.refresh_authorization()
        value=self.revalidate(self.observe())
        self.assertEqual(value['checkpoint'],self.checkpoint)
        self.assertEqual(value['lease_release_revision'],self.release_revision)

    def test_selected_metadata_release_cannot_supply_genuine_original_closure(self):
        self.fixture_bad_selected_closure=True; self.setUp()
        with self.assertRaisesRegex(ValueError,'transactional|genuine|ready'): self.observe()

    def test_malformed_later_record_cannot_be_hidden_by_restore(self):
        changed=copy.deepcopy(self.released); changed['invocation']={'old_metadata':'not current authority'}
        self.publish_control(changed); self.publish_control(self.released)
        with self.assertRaises(ValueError): self.observe()

    def test_later_metadata_release_cannot_replace_native_transaction(self):
        later=copy.deepcopy(self.owned); later.update(generation=2,last_release=self.released['last_release'],
                                                     owner_id='33333333-3333-4333-8333-333333333333')
        later['invocation']['invocation_id']='managed-terminal:later'
        self.publish_control(later)
        ready=copy.deepcopy(later); ready['finalization']=copy.deepcopy(self.ready['finalization'])
        self.publish_control(lease.release(ready,ready['owner_id'],2,ready['invocation']['invocation_id'],
                                           '2026-10-13T10:10:00Z'))
        with self.assertRaisesRegex(ValueError,'transactional|ready'): self.observe()

    def test_later_ownership_cannot_reuse_or_skip_original_generation_identity(self):
        for mutation in ('same_generation','skipped_generation','reused_owner'):
            with self.subTest(mutation=mutation):
                self.setUp(); later=copy.deepcopy(self.owned)
                later.update(generation=2,last_release=self.released['last_release'],
                             owner_id='33333333-3333-4333-8333-333333333333')
                later['invocation']['invocation_id']='managed-terminal:later-owner'
                if mutation=='same_generation': later['generation']=1
                elif mutation=='skipped_generation': later['generation']=3
                else: later['owner_id']=OWNER
                self.publish_control(later)
                ready=copy.deepcopy(later); ready['finalization']=copy.deepcopy(self.ready['finalization'])
                self.publish_control(ready)
                self.publish_control(lease.release(ready,ready['owner_id'],ready['generation'],
                                                   ready['invocation']['invocation_id'],'2026-10-13T10:10:00Z'))
                with self.assertRaisesRegex(ValueError,'ownership generation|owner UUID'): self.observe()

    def guarded_later_generation(self, *, claimed=False, backend='local_command', mode='read_only'):
        owned=copy.deepcopy(self.owned); owned.update(generation=2,last_release=self.released['last_release'],
                                                    owner_id='33333333-3333-4333-8333-333333333333')
        owned['invocation']['invocation_id']='managed-terminal:later-guarded'
        self.publish_control(owned)
        intent=operation.prepare({'repository':'fixture/product','candidate_sha':'a'*40,
            'backend':backend,'mode':mode,'environment_id':'fixture',
            'check_suite_fingerprint':'sha256:'+'b'*64,'environment_fingerprint':'sha256:'+'c'*64,
            'check_plan_digest':'sha256:'+'d'*64},'guarded-later-attempt',SOURCE,'2026-10-13T10:00:02Z')
        receipt=operation.verify_readback(intent,copy.deepcopy(intent),'fixture:intent-readback','2026-10-13T10:00:03Z')
        intent=operation.transition(intent,'submitting','2026-10-13T10:00:03Z',receipt=receipt)
        guarded=lease.set_guard(owned,owned['owner_id'],2,owned['invocation']['invocation_id'],
                                '2026-10-13T10:00:03Z',intent,'fixture:intent')
        revision=self.publish_control(guarded)
        if claimed:
            result=lease.claim_submission(self.lease_store,revision,'fixture/product',SOURCE,
                owned['owner_id'],2,owned['invocation']['invocation_id'],'2026-10-13T10:00:04Z',
                intent_digest=guarded['external_guard']['intent_digest'])
            self.control_head=result['revision']; guarded=self.lease_store.read()[1]
        intent=operation.transition(intent,'unknown','2026-10-13T10:00:05Z')
        guarded=lease.set_guard(guarded,owned['owner_id'],2,owned['invocation']['invocation_id'],
                                '2026-10-13T10:00:05Z',intent,'fixture:intent-unknown')
        self.publish_control(guarded)
        return guarded,intent

    def close_later(self, owned, reconciliation):
        ready=copy.deepcopy(owned); ready['finalization']=copy.deepcopy(self.ready['finalization'])
        ready['finalization']['external_reconciliation']=reconciliation
        revision=self.publish_control(ready)
        released=lease.release(ready,ready['owner_id'],ready['generation'],ready['invocation']['invocation_id'],
                               '2026-10-13T10:00:07Z')
        self.control_head=self.lease_store.compare_and_swap(revision,released)
        return released

    def test_interval_rejects_unknown_guard_erasure_on_released_same_owner_or_acquire_edge(self):
        for edge in ('released','same_owner','new_generation'):
            with self.subTest(edge=edge):
                self.setUp(); guarded,_=self.guarded_later_generation(claimed=edge=='same_owner')
                if edge=='same_owner':
                    changed=copy.deepcopy(guarded); changed['external_guard']=None
                    self.publish_control(changed); self.close_later(changed,'none')
                else:
                    released=self.close_later(guarded,'unknown_preserved')
                    if edge=='released':
                        changed=copy.deepcopy(released); changed['external_guard']=None
                        with self.assertRaises(ValueError):validate_coordination_transition(released,changed)
                        self.publish_control(changed)
                    else:
                        changed=copy.deepcopy(self.owned)
                        changed.update(owner_id='44444444-4444-4444-8444-444444444444',generation=3,
                                       last_release=released['last_release'])
                        changed['invocation']['invocation_id']='managed-terminal:guard-erasing-owner'
                        self.publish_control(changed); self.close_later(changed,'none')
                with self.assertRaises(ValueError): self.observe()

    def test_selected_released_snapshot_cannot_hide_sealed_state_mutation(self):
        changed=copy.deepcopy(self.released); changed['activity_refs'].append('fixture:unrecorded-mutation')
        snapshot=self.publish_control(changed)
        self.checkpoint['control']['execution_lease_revision']=snapshot; self.refresh_authorization()
        with self.assertRaisesRegex(ValueError,'sealed'): self.observe()

    def test_canonical_owned_terminal_resolution_remains_eligible(self):
        for claimed in (False,True):
            with self.subTest(claimed=claimed):
                self.setUp(); self.canonical_owned_terminal_resolution(claimed)

    def canonical_owned_terminal_resolution(self, claimed):
        guarded,intent=self.guarded_later_generation(claimed=claimed)
        observation={'schema':'operation-observation/v1','operation_key':intent['operation_key'],
            'observed_at_utc':'2026-10-13T10:00:06Z','lookup_complete':True,'tasks':[{
                'task_id':'fixture-task','task_url':'https://example.invalid/task','operation_key':intent['operation_key'],
                'attempt_id':intent['attempt_id'],'binding':copy.deepcopy(intent['binding']),
                'state':'terminal','conclusion':'succeeded','evidence_refs':['fixture:terminal-evidence']}]}
        cleared=lease.clear_guard(guarded,guarded['owner_id'],2,guarded['invocation']['invocation_id'],
                                 '2026-10-13T10:00:06Z',observation,'fixture:terminal-evidence')
        revision=self.control_head; self.control_head=self.lease_store.compare_and_swap(revision,cleared)
        self.close_later(cleared,'none')
        proof=self.observe(); self.revalidate(proof)
        self.assertEqual(proof.payload['lease_release']['generation'],1)
        self.assertEqual(len(self.lease_store.read()[1]['submission_resolutions']),int(claimed))

    def test_historical_retirement_preserves_unknown_without_current_capability(self):
        from submission_retirement import retire_unknown_guard
        import project_adoption
        guarded,intent=self.guarded_later_generation(claimed=True,backend='git-conditional-create',mode='retained_windows_exe')
        released=self.close_later(guarded,'unknown_preserved'); revision=self.control_head
        at='2026-10-13T10:00:08Z'
        proof={'schema':'unknown-submission-retirement/v1','lease_revision':revision,
            'lease_digest':operation._hash(released),'guard_digest':operation._hash(released['external_guard']),
            'repository':'fixture/product','source_ref':SOURCE,'observed_at_utc':at,
            'owner_decision':{'action':'retire_unknown_without_replay','reference':'git:'+'1'*40},
            'effect':{'backend':'git-conditional-create','target_ref':'refs/heads/pilot/original',
                'candidate_sha':intent['binding']['candidate_sha'],'expected_target':None,'receive_pack_calls':1,
                'subprocess_returned':True,'caller_reference':'git:'+'2'*40,'caller_digest':'sha256:'+'3'*64,
                'observation_reference':'git:'+'4'*40},
            'runtime':{'invocation_id':guarded['invocation']['invocation_id'],'owner_id':guarded['owner_id'],
                'generation':2,'status':'stopped','quiescent':True,'pending_shared_writes':False,
                'observed_at_utc':at,'reference':'git:'+'5'*40}}
        retired=retire_unknown_guard(released,proof,'git:'+'6'*40,at)
        self.control_head=self.lease_store.compare_and_swap(revision,retired)
        observed=self.observe(); self.revalidate(observed)
        self.assertFalse(observed.payload['authorizes_launch'])
        self.assertEqual(retired['submission_retirements'][0]['outcome'],'UNKNOWN')
        self.assertEqual(retired['submission_claims'],released['submission_claims'])
        changed=copy.deepcopy(retired); changed['submission_retirements'][0]['proof']['lease_revision']='0'*40
        with self.assertRaisesRegex(ValueError,'exact original revision'):
            project_adoption._history_transition(released,changed,revision)
        changed=copy.deepcopy(retired); changed['activity_refs'].append('unrelated:mutation')
        with self.assertRaises(ValueError):project_adoption._history_transition(released,changed,revision)

    def test_deleted_downgraded_or_substituted_native_history_cannot_be_restored(self):
        for mutation in ('delete','downgrade','identity','rewind'):
            with self.subTest(mutation=mutation):
                self.setUp();self.git(self.repo,'reset','--hard',self.control_head)
                if mutation=='delete':
                    self.git(self.repo,'rm','lease.json');self.git(self.repo,'commit','-m','Missing native lease')
                    self.control_head=self.git(self.repo,'rev-parse','HEAD')
                    self.git(self.repo,'push','coordination','HEAD:'+CONTROL)
                else:
                    changed=copy.deepcopy(self.released)
                    if mutation=='downgrade':
                        changed=legacy_lease.acquire(legacy_lease.initialize('fixture/product',SOURCE),OWNER,'2026-10-13T10:00:01Z')
                        changed=legacy_lease.release(changed,OWNER,1,'2026-10-13T10:00:05Z')
                    elif mutation=='identity':changed['repository']='fixture/substituted'
                    else:changed['generation']=0;changed['last_release']=None
                    self.publish_control(changed)
                self.publish_control(self.released)
                with self.assertRaisesRegex(ValueError,'deleted|downgraded|binding|rewound'):self.observe()

    def test_truncated_history_cannot_erase_source_selected_original_revision(self):
        for owned in (True,False):
            with self.subTest(owned=owned):
                self.setUp();revision=self.publish_control(self.owned if owned else self.released)
                tree=self.git(self.repo,'rev-parse',revision+'^{tree}')
                root=self.git(self.repo,'commit-tree',tree,'-m','Truncated native ancestry')
                if owned:
                    tree=self.git(self.repo,'rev-parse',self.release_revision+'^{tree}')
                    root=self.git(self.repo,'commit-tree',tree,'-p',root,'-m','Closure after truncated native ancestry')
                self.git(self.repo,'push','--force','coordination',root+':'+CONTROL)
                with self.assertRaisesRegex(ValueError,'checkpoint lease revision|original history|ancestry'):self.observe()

    def test_merges_after_native_initialization_fail_even_when_record_unchanged(self):
        self.git(self.repo,'checkout','-b','native-side',self.control_head)
        (self.repo/'side.txt').write_text('side');self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','Native side')
        self.git(self.repo,'checkout','-b','native-primary',self.control_head)
        (self.repo/'primary.txt').write_text('primary');self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','Native primary')
        self.git(self.repo,'merge','--no-ff','native-side','-m','Ambiguous native merge')
        self.control_head=self.git(self.repo,'rev-parse','HEAD');self.git(self.repo,'push','coordination','HEAD:'+CONTROL)
        with self.assertRaisesRegex(ValueError,'merged lease'):self.observe()

    def test_shallow_native_history_cannot_supply_an_initialization_boundary(self):
        shallow=self.root/'shallow'
        self.git(self.root,'clone','--depth','1','--branch',CONTROL.removeprefix('refs/heads/'),self.bare.as_uri(),str(shallow))
        self.assertEqual(self.git(shallow,'rev-parse','--is-shallow-repository'),'true')
        candidate=GitLeaseStore(shallow,'origin',CONTROL)
        with self.assertRaisesRegex(ValueError,'lease history is shallow'):self.observe(lease_store=candidate)

    def test_metadata_registration_does_not_permit_owned_invocation_identity_substitution(self):
        for field,value in (('invocation_id','managed-terminal:substitute'),('execution_surface','chat'),
                            ('started_at_utc','2026-10-13T10:00:00.500000Z')):
            with self.subTest(field=field):
                self.fixture_document_budget=True;self.setUp()
                # Append genuine Git ancestry with a new owned generation and an
                # identity rewrite that generic native metadata CAS accepts.
                owned=copy.deepcopy(self.owned);owned['generation']=2;owned['last_release']=self.released['last_release']
                owned['owner_id']='33333333-3333-4333-8333-333333333333'
                first=self.publish_control(owned);changed=copy.deepcopy(owned);changed['invocation'][field]=value
                self.control_head=self.lease_store.compare_and_swap(first,changed)
                changed['finalization']=copy.deepcopy(self.ready['finalization']);self.publish_control(changed)
                self.publish_control(lease.release(changed,changed['owner_id'],2,changed['invocation']['invocation_id'],'2026-10-13T10:10:00Z'))
                with self.assertRaisesRegex(ValueError,'owned generation identity'):self.observe()

    def test_separate_budget_channel_cannot_borrow_root_registration(self):
        self.fixture_document_budget=True;self.fixture_budget_endpoint=True;self.setUp()
        for field in ('coordination_ref','coordination_store_id','task_id'):
            with self.subTest(field=field):
                changed=copy.deepcopy(self.budget_binding)
                changed['coordination_ref']='refs/heads/cdc/foreign-'+field
                ledger=copy.deepcopy(self.ledger);remote='budget'
                if field=='coordination_store_id':remote='coordination';changed[field]=self.endpoint
                if field=='task_id':
                    ledger=budget.new_ledger('replacement-task','old-wake',self.ledger['policy'])
                    changed[field]=ledger['task_id']
                document=GitDocumentStore(self.repo,remote,changed['coordination_ref'],changed['coordination_store_id'],protected_refs=[SOURCE,CONTROL])
                changed['anchor_revision']=document.compare_and_swap(None,{'budget':ledger})
                changed['anchor_ledger_digest']=ledger_digest(ledger)
                # Each substitute is a genuine independently readable native
                # channel; the original Root registration still rejects it.
                candidate=GitProjectBudgetStore(self.repo,remote,changed,protected_refs=[SOURCE])
                with self.assertRaisesRegex(ValueError,'original budget binding'):self.observe(budget_store=candidate)
    def test_stale_active_original_checkpoint_survives_later_native_readonly_release(self):
        self.checkpoint.update(lease_state='active',active_executor=OWNER,executor_heartbeat_at_utc='2026-10-13T10:00:01Z',execution_lease_until_utc='2026-10-13T10:20:01Z',active_compute='managed-host:22222222-2222-5222-8222-222222222222')
        self.checkpoint['control'].update(executor_id=OWNER,execution_lease_revision=self.owned_revision)
        self.checkpoint['execution_continuity']['invocation_id']=INVOCATION;self.refresh_authorization()
        original=copy.deepcopy(self.checkpoint);self.observe()
        later=copy.deepcopy(self.owned);later.update(owner_id='33333333-3333-4333-8333-333333333333',generation=2,last_release=self.released['last_release'])
        later['invocation']['invocation_id']='managed-terminal:later-readonly';later['finalization']=copy.deepcopy(self.ready['finalization']);self.publish_control(later)
        closed=lease.release(later,later['owner_id'],2,later['invocation']['invocation_id'],'2026-10-13T10:10:00Z');self.publish_control(closed)
        proof=self.observe();value=self.revalidate(proof)
        self.assertEqual(value['checkpoint'],original);self.assertEqual(value['lease_release']['generation'],1)
        self.assertEqual(value['remaining_work'],['Original Windows acceptance remains pending'])
        self.assertFalse(value['authorizes_product_acceptance'])

    def test_released_runnable_preserves_product_work_and_windows_gate(self):
        proof = self.observe(); value = self.revalidate(proof)
        self.assertTrue(value['checkpoint']['execution_continuity']['runnable_next_action'])
        self.assertEqual(value['checkpoint']['next_action'], 'Run the original Windows acceptance kit')
        self.assertEqual(value['required_final_platform'], 'windows')
        self.assertEqual(value['scope']['execution_platform'], 'linux')
        self.assertFalse(value['authorizes_product_acceptance']); self.assertFalse(value['authorizes_launch'])
        self.assertIs(proof.budget_store, self.budget_store)

    def test_original_policy_must_authorize_current_native_reader_version(self):
        self.adapter['policy']['skill_max_version_exclusive']=(ROOT/'VERSION').read_text().strip()
        self.adapter['convergence']['target_version']='3.6.0'
        self.adapter_binding=validate_adapter(self.adapter,skill_version='3.6.0')
        self.checkpoint.update(policy_revision=self.adapter_binding['policy_revision'],policy_digest=self.adapter_binding['policy_digest'])
        self.refresh_authorization()
        with self.assertRaises(ValueError):self.observe()

    def test_exact_stale_active_checkpoint_links_original_release(self):
        self.checkpoint.update(lease_state='active', active_executor=OWNER,
                               executor_heartbeat_at_utc='2026-10-13T10:00:01Z', execution_lease_until_utc='2026-10-13T10:20:01Z',
                               active_compute='managed-host:22222222-2222-5222-8222-222222222222')
        self.checkpoint['control'].update(executor_id=OWNER, execution_lease_revision=self.owned_revision)
        self.checkpoint['execution_continuity']['invocation_id'] = INVOCATION
        self.refresh_authorization(); proof = self.observe()
        self.assertEqual(proof.payload['checkpoint_classification'], 'stale_active_projection')
        self.assertEqual(proof.payload['checkpoint']['lease_state'], 'active')
        self.assertEqual(proof.payload['lease_release']['generation'], 1)

    def test_stale_active_wrong_owner_generation_invocation_or_revision_denied(self):
        for mutation in ['owner', 'generation', 'invocation', 'revision']:
            with self.subTest(mutation=mutation):
                self.setUp(); self.checkpoint.update(lease_state='active', active_executor=OWNER,
                    executor_heartbeat_at_utc='2026-10-13T10:00:01Z', execution_lease_until_utc='2026-10-13T10:20:01Z')
                self.checkpoint['control'].update(executor_id=OWNER, execution_lease_revision=self.owned_revision)
                self.checkpoint['execution_continuity']['invocation_id'] = INVOCATION
                if mutation == 'owner': self.checkpoint['control']['executor_id'] = '33333333-3333-4333-8333-333333333333'
                elif mutation == 'generation': self.checkpoint['control']['lease_generation'] = 2
                elif mutation == 'invocation': self.checkpoint['execution_continuity']['invocation_id'] = 'foreign-invocation'
                else: self.checkpoint['control']['execution_lease_revision'] = self.anchor
                self.refresh_authorization()
                with self.assertRaises(ValueError): self.observe()

    def test_unresolved_checkpoint_intents_waits_and_unknown_compute_denied(self):
        for key, value in [('active_compute', 'unknown-native-start'), ('operation_intent_ref', 'intent:unknown'),
                           ('operation_key', 'sha256:' + 'a' * 64), ('active_ci_run_id', 'unresolved-run'),
                           ('waiting_external_kind', 'compute')]:
            with self.subTest(key=key):
                self.setUp(); self.checkpoint[key] = value; self.refresh_authorization()
                with self.assertRaises(ValueError): self.observe()

    def test_source_policy_budget_scope_and_root_authority_substitutions_denied(self):
        for change in [{'source_sha': '0' * 40}, {'source_ref': 'refs/heads/main'}, {'lease_ref': 'refs/heads/cdc/other'},
                       {'source_store_id': 'sha256:' + '0' * 64}, {'budget_binding_digest': 'sha256:' + '0' * 64},
                       {'authority_digest': 'sha256:' + '0' * 64}, {'authority_path': 'project_adoption_authorizations/foreign'},
                       {'final_platform': 'linux'}, {'check_ids': ['arbitrary-command']}, {'approved': True}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.observe(registration={**self.registration, **change})

    def test_policy_authority_is_actual_immutable_native_document(self):
        proof = self.observe(); revision, document = self.authority_store.read()
        document['unrelated_observation'] = 'Root can advance other fields'
        self.authority_store.compare_and_swap(revision, document)
        self.assertFalse(self.revalidate(proof)['authorizes_launch'])
        revision, document = self.authority_store.read(); document['project_adoption_authorizations']['product']['scope']['agent_starts'] = 1
        self.authority_store.compare_and_swap(revision, document)
        with self.assertRaises(ValueError): self.revalidate(proof)

    def test_observation_payload_serialization_and_time_cannot_reconstruct_authority(self):
        proof = self.observe(); raw = proof.payload
        with self.assertRaises((AttributeError, ValueError)): self.revalidate(raw)
        proof._payload['scope']['agent_starts'] = 1
        with self.assertRaises(ValueError): self.revalidate(proof)
        fresh = self.observe(); self.now += timedelta(seconds=91)
        with self.assertRaises(ValueError): self.revalidate(fresh)

    def test_native_channels_and_semantic_budget_lease_source_drift_are_revalidated(self):
        proof = self.observe()
        with self.assertRaises(ValueError): self.observe(source={'observed': True})
        with self.assertRaises(ValueError): self.observe(policy_authority_store={'approved': True})
        revision, _ = self.budget_store.read(); self.budget_store.begin_wake(revision, 'connection-wake')
        with self.assertRaises(ValueError): self.revalidate(proof)
        updated = self.observe(); self.git(self.repo, 'reset', '--hard', self.source_sha)
        (self.repo / 'unrelated-product.txt').write_text('Source changed')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Fixture Source drift'); self.git(self.repo, 'push', 'source', 'HEAD:' + SOURCE)
        with self.assertRaises(ValueError): self.revalidate(updated)

    def test_older_released_projection_and_new_generation_history_are_supported(self):
        second = copy.deepcopy(self.owned)
        second.update(owner_id='33333333-3333-4333-8333-333333333333', generation=2,
                      last_release=self.released['last_release'])
        second['invocation']['invocation_id'] = 'managed-terminal:second-native-invocation'
        second['finalization'] = copy.deepcopy(self.ready['finalization'])
        self.publish_control(second)
        released = lease.release(second, second['owner_id'], 2, second['invocation']['invocation_id'], '2026-10-13T10:00:06Z')
        self.publish_control(released)
        proof = self.observe()
        self.assertEqual(proof.payload['checkpoint']['control']['lease_generation'], 1)
        self.assertEqual(proof.payload['lease_release']['generation'], 1)
        self.assertFalse(self.revalidate(proof)['authorizes_product_acceptance'])

    def test_live_owner_foreign_binding_and_fabricated_release_history_denied(self):
        for mutation in ['owner', 'repository', 'guard', 'release']:
            with self.subTest(mutation=mutation):
                self.setUp(); changed = copy.deepcopy(self.released)
                if mutation == 'owner': changed = copy.deepcopy(self.ready)
                elif mutation == 'repository': changed['repository'] = 'fixture/foreign-product'
                elif mutation == 'guard':
                    intent = operation.prepare({'repository': 'fixture/product', 'candidate_sha': 'a' * 40,
                        'backend': 'codex', 'mode': 'COMPUTE_ONLY', 'check_suite_fingerprint': 'sha256:' + 'b' * 64,
                        'environment_fingerprint': 'sha256:' + 'c' * 64, 'check_plan_digest': 'sha256:' + 'd' * 64,
                        'environment_id': 'fixture'}, 'guarded-attempt', SOURCE, '2026-10-13T10:00:01Z')
                    receipt = operation.verify_readback(intent, copy.deepcopy(intent), 'fixture:intent-readback', '2026-10-13T10:00:02Z')
                    intent = operation.transition(intent, 'submitting', '2026-10-13T10:00:03Z', receipt=receipt)
                    intent = operation.transition(intent, 'unknown', '2026-10-13T10:00:04Z')
                    changed = lease.set_guard(self.owned, OWNER, 1, INVOCATION, '2026-10-13T10:00:04Z', intent, 'fixture:intent')
                    changed['finalization'] = copy.deepcopy(self.ready['finalization'])
                    changed['finalization']['external_reconciliation'] = 'unknown_preserved'
                    changed = lease.release(changed, OWNER, 1, INVOCATION, '2026-10-13T10:00:05Z')
                    self.assertIsNone(changed['owner_id']); lease.validate(changed)
                else: changed['last_release']['checkpoint_ref'] = 'fabricated:replacement'
                self.publish_control(changed)
                with self.assertRaises(ValueError): self.observe()

    def test_authentic_document_does_not_authorize_foreign_task_policy_counts_or_scope(self):
        for key, value in [('task_id', 'replacement-task'), ('budget_policy_digest', 'sha256:' + 'b' * 64),
                           ('source_policy_revision', 'foreign-policy'), ('preserved_counts', {}),
                           ('owner_wake_ref', 'owner:unregistered-wake'), ('remaining_work', [])]:
            with self.subTest(key=key):
                self.setUp(); self.authorization[key] = value
                revision, document = self.authority_store.read()
                document['project_adoption_authorizations']['product'] = self.authorization
                self.auth_revision = self.authority_store.compare_and_swap(revision, document)
                self.registration = self.registration_record()
                with self.assertRaises(ValueError): self.observe()

    def test_restored_authority_rewrite_and_serialized_constructor_are_rejected(self):
        native = importlib.import_module('project_adoption'); proof = self.observe()
        with self.assertRaises(ValueError):
            native.ProjectAdoptionObservation(proof.payload, (), self.registration, lambda: NOW)
        revision, document = self.authority_store.read(); original = copy.deepcopy(document)
        document['project_adoption_authorizations']['product']['owner_decision_ref'] = 'foreign:decision'
        revision = self.authority_store.compare_and_swap(revision, document)
        self.authority_store.compare_and_swap(revision, original)
        with self.assertRaises(ValueError): self.observe()

    def test_native_channel_substitution_and_endpoint_drift_are_denied(self):
        proof = self.observe(); replacement = GitSource(self.repo, 'source', self.endpoint, clock=lambda: self.now)
        with self.assertRaises(ValueError):
            proof.revalidate_for(replacement, self.lease_store, self.budget_store, self.authority_store, self.registration)
        self.git(self.repo, 'remote', 'set-url', 'source', str(self.root / 'different.git'))
        with self.assertRaises(ValueError): self.revalidate(proof)

    def test_historical_task_policy_and_unknown_charges_survive_distinct_owner_wake(self):
        self.fixture_charged = True; self.setUp(); proof = self.observe()
        self.assertEqual(proof.payload['budget_summary']['active_agents'], 1)
        self.assertEqual(proof.payload['budget_summary']['task']['ci_starts'], 1)
        self.assertEqual(proof.payload['scope']['agent_starts'], 0)
        old_events = copy.deepcopy(self.ledger['events'])
        self.budget_store.begin_wake(proof.budget_revision, 'connection-wake')
        with self.assertRaises(ValueError): self.revalidate(proof)
        fresh = self.observe(); _, ledger = fresh.budget_store.read()
        self.assertEqual(ledger['events'], old_events)
        self.assertEqual(ledger['wake_ids'], ['old-wake', 'connection-wake'])
        self.assertEqual(fresh.payload['budget_summary']['active_agents'], 1)
        self.assertFalse(fresh.payload['authorizes_launch'])

    def test_released_projection_cannot_substitute_retained_executor_or_invocation(self):
        for field in ['executor', 'invocation']:
            with self.subTest(field=field):
                self.setUp()
                if field == 'executor': self.checkpoint['control']['executor_id'] = '33333333-3333-4333-8333-333333333333'
                else: self.checkpoint['execution_continuity']['invocation_id'] = 'foreign-invocation'
                self.refresh_authorization()
                with self.assertRaises(ValueError): self.observe()


if __name__ == '__main__': unittest.main()
