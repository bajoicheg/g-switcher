"""Pure synthetic replay-defence fixtures; no native authority or provider proof."""
import copy
import unittest
from test_recovery_recipes_v2 import m, selection, event, DIAG, B, H, PARAMS, D, E

class SelectedCorrection(unittest.TestCase):
    def consumed_with_unrelated_verified(self):
        old=selection();p=m.action_plan(old,DIAG,B,H,PARAMS)
        h=m.append_history(H,event(p))
        unrelated=event(p,outcome='verified',event_id='unrelated',attempt='attempt:unrelated')
        unrelated.update(action_fingerprint=D,evidence_ref='evidence:unrelated-success',evidence_digest=D)
        h=m.append_history(h,unrelated)
        return old,p,h

    def test_forged_reason_without_selected_signal_cannot_replay(self):
        old,p,h=self.consumed_with_unrelated_verified()
        self.assertEqual(selection(h=h)['reason'],'recovery_observation_consumed')
        forged=copy.deepcopy(old);forged['reason']='completed_correction_retry'
        with self.assertRaises(ValueError):m.action_plan(forged,DIAG,B,h,PARAMS)

    def test_selected_correction_must_match_exact_verified_digest(self):
        old,p,h=self.consumed_with_unrelated_verified()
        signal={'reference':'signal:correction','digest':D,'changed_inputs':{},'completed_correction_ref':'evidence:unrelated-success'}
        selected=selection(h=h,signal=signal)
        self.assertEqual(selected['reason'],'completed_correction_retry')
        self.assertIn('selected_signal',selected)
        forged=copy.deepcopy(selected);forged['selected_signal']['digest']=E
        with self.assertRaises(ValueError):m.action_plan(forged,DIAG,B,h,PARAMS)

    def test_explicit_bound_unused_correction_retry_is_valid_and_consumed_once(self):
        old,p,h=self.consumed_with_unrelated_verified()
        signal={'reference':'signal:correction','digest':D,'changed_inputs':{},'completed_correction_ref':'evidence:unrelated-success'}
        selected=selection(h=h,signal=signal)
        self.assertEqual(selected['selected_signal'],signal)
        self.assertEqual(m.action_plan(selected,DIAG,B,h,PARAMS)['action_fingerprint'],p['action_fingerprint'])
        used=event(p,event_id='retry',attempt='attempt:retry');used.update(completed_correction_ref=signal['completed_correction_ref'],new_signal_ref=signal['reference'])
        h=m.append_history(h,used)
        with self.assertRaises(ValueError):m.action_plan(selected,DIAG,B,h,PARAMS)
