import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import coordination_retention as m
def data():
 return {"schema":"coordination-retention/v1","policy":{"archive_after_seconds":3600,"delete_after_seconds":86400,"never_delete_kinds":["audit","ledger"]},"records":[]}
def rec(i,kind="operation",age=90000,terminal=True,active=False,guard=False):
 return {"id":i,"kind":kind,"age_seconds":age,"terminal":terminal,"active_reference":active,"guard_present":guard}
class T(unittest.TestCase):
 def test_terminal_expired_operation_candidate(self):
  x=data();x["records"]=[rec("op")];r=m.assess(x);self.assertEqual(r["delete_candidates"][0]["id"],"op");self.assertFalse(r["authorizes_delete"])
 def test_middle_age_archives(self):
  x=data();x["records"]=[rec("op",age=4000)];self.assertEqual(m.assess(x)["archive_candidates"][0]["id"],"op")
 def test_audit_ledger_active_guard_live_never_delete(self):
  x=data();x["records"]=[rec("a","audit"),rec("l","ledger"),rec("active",active=True),rec("guard",guard=True),rec("live",terminal=False)]
  self.assertEqual(len(m.assess(x)["keep"]),5)
if __name__=="__main__":unittest.main()
