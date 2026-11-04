import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import version_convergence as m
T={"schema":"version-convergence-target/v1","target_version":"2.6.0","target_package_fingerprint":"git-tree:"+"a"*40,"checkpoint_schema":"development-work-status/v4","safe_boundary_required":True}
def s():return {"schema":"version-convergence-snapshot/v1","repository":"o/r","source_ref":"refs/heads/main","cdc_version":"2.6.0","package_fingerprint":"git-tree:"+"a"*40,"checkpoint_schema":"development-work-status/v4","owner_active":False,"guard_present":False,"policy_revision":"p"}
class X(unittest.TestCase):
 def test_converged(self):self.assertEqual(m.assess(T,s())["state"],"CONVERGED")
 def test_package_drift(self):x=s();x["package_fingerprint"]="git-tree:"+"b"*40;self.assertEqual(m.assess(T,x)["state"],"DRIFT")
 def test_active_owner_defers_lagging_adoption(self):x=s();x["cdc_version"]="2.5.0";x["owner_active"]=True;self.assertEqual(m.assess(T,x)["recommended_action"],"wait_safe_boundary")
 def test_major_mismatch_manual(self):x=s();x["cdc_version"]="3.0.0";self.assertEqual(m.assess(T,x)["state"],"INCOMPATIBLE")
if __name__=="__main__":unittest.main()
