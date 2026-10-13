import unittest
from publication_guard import assess
POL={"schema":"sensitive-context-policy/v1","forbidden_literals":["InternalCo"],"forbidden_domain_suffixes":[],"allow_example_domains":True,"detect_private_ips":True,"case_insensitive":True}
def inv():
 return {"schema":"publication-inventory/v1","repository":"owner/repo","target_visibility":"public","refs":["refs/heads/main"],"files":[{"path":"README.md","content":"example project"}],"conversations":[],"artifacts":[]}
class Tests(unittest.TestCase):
 def test_clean_inventory_passes(self):self.assertTrue(assess(inv(),POL)["pass"])
 def test_control_plane_path_blocks_direct_publication(self):
  i=inv();i["files"].append({"path":"operations/run.json","content":"{}"})
  r=assess(i,POL);self.assertFalse(r["pass"]);self.assertTrue(r["requires_sanitized_export"])
 def test_risky_coordination_ref_blocks(self):
  i=inv();i["refs"].append("refs/heads/cdc/coordination")
  self.assertFalse(assess(i,POL)["pass"])
 def test_conversation_sensitive_context_blocks(self):
  i=inv();i["conversations"].append({"kind":"pr","id":"1","body":"InternalCo controller"})
  self.assertFalse(assess(i,POL)["pass"])
 def test_private_ip_blocks(self):
  i=inv();i["artifacts"].append({"name":"log","metadata":"server=192.168.1.20"})
  self.assertFalse(assess(i,POL)["pass"])
if __name__=="__main__":unittest.main()
