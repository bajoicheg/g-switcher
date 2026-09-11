import inspect
import os
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('RUNNER_TEMP', tempfile.gettempdir())
import apply_history as a

class ResumeTests(unittest.TestCase):
    def test_deleted_run_is_accepted_without_delete(self):
        self.assertTrue(callable(getattr(a, 'confirm_prior_removal', None)))
        with patch.object(a, 'api', return_value=(404, None)) as api:
            self.assertEqual(a.confirm_prior_removal(), 404)
            api.assert_called_once_with('GET', f'actions/runs/{a.RUN_TO_DELETE}', allow_missing=True)
    def test_existing_run_is_not_deleted(self):
        self.assertTrue(callable(getattr(a, 'confirm_prior_removal', None)))
        with patch.object(a, 'api', return_value=(200, {})) as api:
            with self.assertRaises(RuntimeError): a.confirm_prior_removal()
            self.assertEqual(api.call_count, 1)
    def test_owner_disabled_window_is_required(self):
        self.assertTrue(callable(getattr(a, 'confirm_window', None)))
        for state in ('active', 'evaluate', None):
            with patch.object(a, 'api', return_value=(200, {'id':22084348, 'enforcement':state})):
                with self.assertRaises(RuntimeError): a.confirm_window()
    def test_disabled_expected_ruleset_is_accepted(self):
        self.assertTrue(callable(getattr(a, 'confirm_window', None)))
        with patch.object(a, 'api', return_value=(200, {'id':22084348, 'enforcement':'disabled'})):
            a.confirm_window()
    def test_wrong_ruleset_rejected(self):
        self.assertTrue(callable(getattr(a, 'confirm_window', None)))
        with patch.object(a, 'api', return_value=(200, {'id':42, 'enforcement':'disabled'})):
            with self.assertRaises(RuntimeError): a.confirm_window()
    def test_resume_cannot_delete_runs(self):
        self.assertNotIn("api('DELETE'", inspect.getsource(a))

if __name__=='__main__': unittest.main()
