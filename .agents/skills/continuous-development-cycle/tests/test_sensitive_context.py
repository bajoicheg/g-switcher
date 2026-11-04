import unittest
from sensitive_context import scan_text
POL={"schema":"sensitive-context-policy/v1","forbidden_literals":["AcmeInternal"],"forbidden_domain_suffixes":["corp.invalid.example"],"allow_example_domains":True,"detect_private_ips":True,"case_insensitive":True}
class Tests(unittest.TestCase):
 def test_literal_is_case_insensitive(self):self.assertEqual(scan_text("acmeinternal",POL)[0]["kind"],"forbidden_literal")
 def test_private_ip_is_detected(self):self.assertIn("private_ip",{x["kind"] for x in scan_text("host 10.20.30.40",POL)})
 def test_example_domains_are_safe(self):self.assertEqual(scan_text("dc01.example.test alice@example.com",POL),[])
 def test_configured_internal_domain_is_flagged(self):
  p=dict(POL);p["allow_example_domains"]=False
  self.assertIn("forbidden_domain",{x["kind"] for x in scan_text("dc01.corp.invalid.example",p)})
if __name__=="__main__":unittest.main()
