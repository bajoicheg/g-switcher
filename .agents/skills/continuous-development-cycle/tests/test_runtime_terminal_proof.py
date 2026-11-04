"""Real supervisor quiescence and recorded births, not wrapper returncode."""
import time,unittest,sys,copy,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_managed_executor_runtime as native
import managed_executor_runtime as runtime

class TerminalProofTests(unittest.TestCase):
 def setUp(self):
  self.fixture=native.RuntimeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
 def start(self,delay=.1):
  f=self.fixture;rev,_=f.store.read()
  return f.rt.start(rev,'a','a1',reservation_token='reserve:a',argv=f.worker('a',delay=delay))
 def verify(self):
  method=getattr(self.fixture.rt,'verify_terminal',None)
  self.assertIsNotNone(method,'authentic birth-bound terminal verifier missing')
  return method('a','a1')
 def test_nonterminal_real_supervisor_is_not_terminal_from_a_wrapper_claim(self):
  self.start(delay=2)
  with self.assertRaisesRegex(ValueError,'terminal|quiescen'):self.verify()
 def test_actual_subreaper_terminal_has_births_and_fresh_absence(self):
  self.start();deadline=time.monotonic()+4
  while time.monotonic()<deadline:
   observation=self.fixture.rt.observe('a','a1')
   if observation.get('quiescent'):
    try:proof=self.verify();break
    except ValueError:pass
   time.sleep(.01)
  else:self.fail('actual terminal/birth/physical proof unavailable')
  self.assertEqual(proof['status'],'succeeded')
  self.assertTrue(proof['fresh_physical_absence'])
  self.assertEqual(proof['quiescence_method'],'waitpid_ECHILD')
  self.assertTrue(all(p['birth'] is not None for p in proof['processes']))
  self.assertFalse(proof['authorizes_release'])
 def test_removed_quiescence_proof_cannot_be_replaced_by_exit_zero(self):
  self.start();deadline=time.monotonic()+4
  while time.monotonic()<deadline:
   observation=self.fixture.rt.observe('a','a1')
   if observation.get('quiescent'):break
   time.sleep(.01)
  request=self.fixture.rt._request('a','a1');path=Path(request['journal_directory'])/'receipt.json'
  record=json.loads(path.read_text());record.pop('quiescence_proof',None);path.write_text(json.dumps(record))
  with self.assertRaisesRegex(ValueError,'quiescence proof'):self.verify()

if __name__=='__main__':unittest.main()
