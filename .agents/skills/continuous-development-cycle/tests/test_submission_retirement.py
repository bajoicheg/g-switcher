"""Owner retirement preserves uncertainty while allowing unrelated maintenance."""
import copy
import importlib
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import execution_lease_v2 as lease
import operation_intent as op
from git_lease_store import validate_coordination_transition
from test_submission_recovery import fixture, NOW, REV

def retirement_fixture():
    record, old = fixture()
    guard = record['external_guard']
    prepared = copy.deepcopy(guard['intent'])
    prepared.update(state='prepared', durable_intent=None, updated_at_utc=prepared['created_at_utc'])
    prepared['binding'].update(backend='git-conditional-create', mode='retained_windows_exe')
    prepared['operation_key'] = op.operation_key(prepared['binding'])
    receipt = op.verify_readback(prepared, copy.deepcopy(prepared), 'git:'+'b'*40, prepared['updated_at_utc'])
    intent = op.transition(prepared, 'submitting', '2026-10-04T17:00:01Z', receipt=receipt)
    claim = copy.deepcopy(guard['submission_claim'])
    claim.update(operation_key=intent['operation_key'], intent_digest=op._hash(intent))
    guard.update(intent=intent, operation_key=intent['operation_key'], intent_digest=op._hash(intent), submission_claim=claim)
    record['submission_claims'] = [copy.deepcopy(claim)]
    proof = dict(schema='unknown-submission-retirement/v1', lease_revision=REV,
        lease_digest=op._hash(record), guard_digest=op._hash(guard), repository=record['repository'],
        source_ref=record['source_ref'], observed_at_utc=NOW,
        owner_decision=dict(action='retire_unknown_without_replay', reference='git:'+'1'*40),
        effect=dict(backend='git-conditional-create', target_ref='refs/heads/pilot/original',
            candidate_sha=intent['binding']['candidate_sha'], expected_target=None,
            receive_pack_calls=1, subprocess_returned=True, caller_reference='git:'+'2'*40,
            caller_digest='sha256:'+'3'*64, observation_reference='git:'+'4'*40),
        runtime=copy.deepcopy(old['runtime']))
    return record, proof

class Tests(unittest.TestCase):
    def retire(self, record, proof):
        try: module=importlib.import_module('submission_retirement')
        except ModuleNotFoundError: self.fail('Canonical UNKNOWN retirement is missing')
        return module.retire_unknown_guard(record, proof, 'git:'+'5'*40, NOW)

    def test_retirement_preserves_unknown_and_all_original_history(self):
        old,proof=retirement_fixture(); new=self.retire(old,proof)
        self.assertIsNone(new['external_guard'])
        entry=new['submission_retirements'][0]
        self.assertEqual(entry['outcome'],'UNKNOWN'); self.assertIs(entry['replay_forbidden'],True)
        self.assertEqual(entry['guard'],old['external_guard'])
        for key in set(old)-{'external_guard'}: self.assertEqual(new[key],old[key],key)
        validate_coordination_transition(old,new,expected_revision=REV)

    def test_invalid_scope_or_evidence_never_unlocks(self):
        old,proof=retirement_fixture()
        edits=[('effect','target_ref','refs/heads/main'),('effect','expected_target','a'*40),
            ('effect','subprocess_returned',False),('effect','receive_pack_calls',2),
            ('effect','candidate_sha','f'*40),('effect','caller_reference','mutable:path'),
            ('runtime','quiescent',False),('runtime','pending_shared_writes',True),
            ('runtime','invocation_id','other'),('owner_decision','action','forget')]
        for section,key,value in edits:
            bad=copy.deepcopy(proof);bad[section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):self.retire(old,bad)
        for key,value in [('guard_digest','sha256:'+'0'*64),('lease_digest','sha256:'+'0'*64),
                          ('observed_at_utc','2026-10-04T16:00:00Z')]:
            bad=copy.deepcopy(proof);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.retire(old,bad)

    def test_raw_clear_history_tamper_and_stale_revision_are_rejected(self):
        old,proof=retirement_fixture();new=self.retire(old,proof)
        for key,value in [('last_terminal',{}),('generation',2),('submission_claims',[])]:
            bad=copy.deepcopy(new);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_coordination_transition(old,bad,expected_revision=REV)
        bad=copy.deepcopy(old);bad['external_guard']=None
        with self.assertRaises(ValueError):validate_coordination_transition(old,bad,expected_revision=REV)
        with self.assertRaises(ValueError):validate_coordination_transition(old,new,expected_revision='0'*40)
        bad=copy.deepcopy(new);bad['submission_retirements']=[]
        with self.assertRaises(ValueError):validate_coordination_transition(new,bad,expected_revision=REV)

    def test_distinct_candidate_remains_eligible_without_resolving_old_outcome(self):
        old,proof=retirement_fixture();new=self.retire(old,proof)
        binding=copy.deepcopy(old['external_guard']['intent']['binding'])
        binding['candidate_sha']='f'*40
        intent=op.prepare(binding,'independent-upgrade',old['source_ref'],'2026-10-04T17:00:00Z')
        receipt=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc'])
        intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
        candidate=copy.deepcopy(new)
        candidate['external_guard']=dict(operation_key=intent['operation_key'],intent=intent,
            intent_digest=op._hash(intent),intent_reference='git:'+'b'*40,submission_claim=None)
        lease.validate(candidate)
        self.assertEqual(candidate['submission_retirements'][0]['outcome'],'UNKNOWN')

    def test_retired_candidate_cannot_rearm_under_new_attempt_or_binding(self):
        old,proof=retirement_fixture();new=self.retire(old,proof)
        for environment in ['original','another']:
            guard=copy.deepcopy(old['external_guard']);intent=guard['intent']
            intent['attempt_id']='new-attempt';intent['binding']['environment_id']=environment
            intent['operation_key']=op.operation_key(intent['binding']);intent['durable_intent']=None
            intent['state']='prepared';intent['updated_at_utc']=intent['created_at_utc']
            receipt=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc'])
            intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
            guard.update(intent=intent,operation_key=intent['operation_key'],intent_digest=op._hash(intent),submission_claim=None)
            bad=copy.deepcopy(new);bad['external_guard']=guard
            with self.subTest(environment=environment),self.assertRaises(ValueError):lease.validate(bad)

class GitTests(unittest.TestCase):
    retire = Tests.retire
    from test_submission_recovery import GitTests as _Fixture
    setUp = _Fixture.setUp

    def test_git_retirement_race_keeps_one_history_and_preserves_neighbors(self):
        import subprocess
        old,proof=retirement_fixture();store,other=self.stores
        revision=store.compare_and_swap(None,old)
        # Add unrelated durable evidence beside the lease using ordinary Git.
        repo=store.repo
        subprocess.run(['git','-C',str(repo),'checkout','-B','neighbor',revision],check=True,capture_output=True)
        (repo/'checkpoint.json').write_text('{"immutable":"original"}\n')
        subprocess.run(['git','-C',str(repo),'add','checkpoint.json'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','neighbor'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'push','origin','HEAD:refs/heads/recovery-test'],check=True,capture_output=True)
        revision,observed=store.read();self.assertEqual(observed,old)
        proof['lease_revision']=revision
        result=importlib.import_module('submission_retirement').retire_unknown_cas(store,revision,proof,'git:'+'5'*40,NOW)
        self.assertIs(result['authorizes_submission'],False)
        new=result['record']
        with self.assertRaises(ValueError):other.compare_and_swap(revision,new)
        rev,actual=other.read();self.assertEqual(actual,new)
        self.assertEqual(len(actual['submission_retirements']),1)
        neighbor=subprocess.run(['git','-C',str(other.repo),'show',rev+':checkpoint.json'],check=True,capture_output=True,text=True).stdout
        self.assertEqual(neighbor,'{"immutable":"original"}\n')

    def test_lost_reply_never_retries_cas_and_observation_preserves_unknown(self):
        old,proof=retirement_fixture();store=self.stores[0]
        revision=store.compare_and_swap(None,old);proof['lease_revision']=revision
        original=store.compare_and_swap; calls=[]
        def lost(expected,record):
            calls.append(expected);original(expected,record);raise OSError('lost CAS response')
        store.compare_and_swap=lost
        module=importlib.import_module('submission_retirement')
        with self.assertRaises(OSError):module.retire_unknown_cas(store,revision,proof,'git:'+'5'*40,NOW)
        rev,new=store.read();self.assertNotEqual(rev,revision)
        self.assertEqual(new['submission_retirements'][0]['outcome'],'UNKNOWN')
        with self.assertRaises(ValueError):module.retire_unknown_cas(store,revision,proof,'git:'+'5'*40,NOW)
        self.assertEqual(calls,[revision])
