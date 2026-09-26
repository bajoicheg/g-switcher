import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("execution_continuity",ROOT/"scripts/execution_continuity.py")
m=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)

def base():
    return dict(schema="execution-continuity/v1",invocation_id="inv-1",current_state="CHECKPOINT",
                requested_terminal_outcome="progress",runnable_next_action=True,
                meaningful_progress_refs=[],primitive_steps=["status_read","health_check","lease_check","report_only"],
                external_binding=None,blocker=None,checkpoint_ref="checkpoint:1",next_action="implement",
                lease_release_required=False,lease_released=True)

class Tests(unittest.TestCase):
    def test_primitive_only_completion_rejected(self):
        r=m.evaluate(base()); self.assertFalse(r["allowed"]); self.assertEqual(r["reason"],"primitive_only_completion")
    def test_meaningful_progress_allowed(self):
        s=base(); s["meaningful_progress_refs"]=["git:abc"]; self.assertTrue(m.evaluate(s)["allowed"])
    def test_external_binding_allowed(self):
        s=base(); s.update(requested_terminal_outcome="waiting_external",external_binding={"kind":"ci","id":"run-1","operation_key":"sha256:x"})
        self.assertTrue(m.evaluate(s)["allowed"])
    def test_resumable_blocker_allowed(self):
        s=base(); s.update(requested_terminal_outcome="blocked",blocker="no compatible runtime")
        self.assertTrue(m.evaluate(s)["allowed"])
    def test_owned_lease_must_be_released(self):
        s=base(); s["meaningful_progress_refs"]=["git:abc"]; s.update(lease_release_required=True,lease_released=False)
        self.assertEqual(m.evaluate(s)["reason"],"owned_lease_not_released")

if __name__=="__main__": unittest.main()
