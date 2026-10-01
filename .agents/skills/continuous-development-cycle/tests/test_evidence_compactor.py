import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import evidence_compactor as m
def s():
 return {"schema":"evidence-stream/v1","scope_id":"t","events":[
  {"id":"1","kind":"test","result":"PASS","ref":"run:1","digest":"sha256:a","terminal":False,"detail":"verbose"},
  {"id":"2","kind":"test","result":"PASS","ref":"run:1","digest":"sha256:b","terminal":True,"detail":"more"},
  {"id":"3","kind":"review","result":"FAIL","ref":"review:1","digest":"sha256:c","terminal":True,"detail":"detail"}]}
class T(unittest.TestCase):
 def test_compacts_counts_refs_and_digest(self):
  r=m.compact(s());self.assertEqual(r["source_event_count"],3);self.assertEqual(r["result_counts"]["PASS"],2);self.assertEqual(r["evidence_refs"],["run:1","review:1"]);self.assertTrue(r["source_digest"].startswith("sha256:"));self.assertFalse(r["details_retained"])
 def test_deterministic(self):self.assertEqual(m.compact(s())["source_digest"],m.compact(s())["source_digest"])
 def test_duplicate_event_rejected(self):
  x=s();x["events"][1]["id"]="1"
  with self.assertRaises(ValueError):m.compact(x)
if __name__=="__main__":unittest.main()
