import unittest
from boundary import released_state

class ReleaseBoundaryTests(unittest.TestCase):
    def test_failed_worker_retains_unresolved_sibling_as_blocked(self):
        self.assertEqual(released_state('failed', {'intent': 'original'}), 'blocked-unknown-preserved')
    def test_success_cannot_close_while_sibling_unresolved(self):
        with self.assertRaises(ValueError):
            released_state('succeeded', {'intent': 'original'})
    def test_failed_terminal_sibling_is_a_released_failure(self):
        self.assertEqual(released_state('failed', None), 'failure-terminal')
    def test_successful_reconciled_sibling_can_close(self):
        self.assertEqual(released_state('succeeded', None), 'terminal')
