import datetime as dt
import json
from pathlib import Path
import sys
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import budget,recovery

class PollContinuationTests(unittest.TestCase):
    def test_default_admission_and_wait_continue_after_four_polls(self):
        config=yaml.safe_load((ROOT/'templates/development-cycle.yaml').read_text())['orchestration']
        self.assertIsNone(config['budget']['wake_limits']['status_polls'])
        ledger=budget.new_ledger('task','wake',config['budget'])
        start=dt.datetime(2026,9,23,tzinfo=dt.timezone.utc)
        stamp=lambda t:t.isoformat().replace('+00:00','Z')
        state=dict(schema='external-wait/v1',operation_key='sha256:'+'a'*64,attempt_id='run',task_id='provider-task',candidate_sha='b'*40,phase='setup',phase_started_at_utc=stamp(start),last_successful_observation=None,last_poll_at_utc=None,observation_valid=False,source_valid=False,unchanged_polls=0,error_polls=0)
        now=start;delays=[]
        for n in range(6):
            event=dict(type='reserve',event_id=f'poll-{n}',task_id='task',wake_id='wake',at_utc=stamp(now),operation_key=state['operation_key'],attempt_id=f'poll-{n}',kind='status_poll',scope='provider-task',recovery_ref=None,cost=dict(tool_calls=1,tokens=None,elapsed_seconds=None))
            ledger=budget._append(ledger,event)
            observation={k:state[k] for k in recovery.IDENTITY}
            observation.update(schema='wait-observation/v1',phase='setup',observed_at_utc=stamp(now),source='provider',source_valid=True,observation_valid=True,lookup_complete=True,conclusion=None,evidence_refs=[],retry_after_seconds=None)
            result=recovery.supervise_wait(state,observation,config['wait'],stamp(now))
            self.assertEqual(result['action'],'observe');self.assertTrue(result['external_guard']);self.assertFalse(result['allow_submission'])
            state=result['state'];delays.append(result['next_poll_seconds']);now+=dt.timedelta(seconds=delays[-1])
        self.assertEqual(delays,[60,120,240,300,300,300])
        self.assertEqual(state['phase_started_at_utc'],stamp(start))
        self.assertEqual(budget.summarize(ledger)['wake']['status_polls'],6)
        later=start+dt.timedelta(seconds=config['wait']['setup_seconds'])
        observation['observed_at_utc']=stamp(later)
        result=recovery.supervise_wait(state,observation,config['wait'],stamp(later))
        self.assertEqual(result['action'],'diagnose');self.assertTrue(result['external_guard']);self.assertFalse(result['allow_submission'])

    def test_ledger_template_has_no_poll_count_cap(self):
        ledger=json.loads((ROOT/'templates/budget-ledger.json').read_text())
        budget.validate_ledger(ledger)
        for scope in ('task_limits','wake_limits'):self.assertIsNone(ledger['policy'][scope]['status_polls'])

if __name__=='__main__':unittest.main()
