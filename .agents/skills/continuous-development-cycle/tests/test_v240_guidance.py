from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
    def test_core_mentions_v24_controls(self):
        text=(ROOT/"SKILL.md").read_text().lower()
        for term in ("invocation-bound","resume capsule","execution-continuity","transactional"):
            self.assertIn(term,text)
    def test_watchdog_requires_hard_gate_and_release(self):
        text=(ROOT/"templates/watchdog-prompt.md").read_text().lower()
        for term in ("execution-continuity","transactionally","release"):
            self.assertIn(term,text)
if __name__=="__main__": unittest.main()
