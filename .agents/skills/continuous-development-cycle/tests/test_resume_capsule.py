import importlib.util, json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("resume_capsule",ROOT/"scripts/resume_capsule.py")
m=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)

class Tests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/"templates/resume-capsule.json").read_text())
    def probe(self, at="2026-01-01T00:01:00Z"):
        return {"schema":"resume-probe/v1","observed_at_utc":at,"complete":True,
                "repository":self.c["repository"],"source_ref":self.c["source_ref"],
                "head_sha":self.c["head_sha"],"policy_version":self.c["policy_version"],
                "policy_revision":self.c["policy_revision"],"policy_digest":self.c["policy_digest"],
                "checkpoint_digest":self.c["checkpoint_digest"],"lease_revision":self.c["ownership"]["revision"]}
    def test_exact_probe_fast_resumes(self): self.assertTrue(m.assess(self.c,self.probe())["fast_resume"])
    def test_policy_change_forces_reconcile(self):
        p=self.probe(); p["policy_digest"]="sha256:"+"2"*64; self.assertFalse(m.assess(self.c,p)["fast_resume"])
    def test_head_change_forces_reconcile(self):
        p=self.probe(); p["head_sha"]="1"*40; self.assertFalse(m.assess(self.c,p)["fast_resume"])
    def test_lease_revision_change_forces_reconcile(self):
        p=self.probe(); p["lease_revision"]="abc"; self.assertFalse(m.assess(self.c,p)["fast_resume"])
    def test_stale_capsule_forces_reconcile(self):
        self.assertFalse(m.assess(self.c,self.probe("2026-01-01T03:00:01Z"))["fast_resume"])

if __name__=="__main__": unittest.main()
