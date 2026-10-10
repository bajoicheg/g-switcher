"""The public delivery command is strict read-only planning, never a write grant."""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import release_delivery

def request():
    version="3.3.0"
    binding=dict(schema="live-target-release/v1",version=version,canonical_repository="owner/cdc",
        release_ref="refs/heads/release/v"+version,release_commit="b"*40,package_tree="c"*40)
    lock=dict(schema="cdc-consumer-lock/v1",version="3.2.0",canonical_repository="owner/cdc",
        release_ref="refs/heads/release/v3.2.0",release_commit="d"*40,package_tree="e"*40,
        checkpoint_schema="development-work-status/v4",safe_boundary_required=True,local_core_modifications_allowed=False)
    return dict(schema="cdc-delivery-request/v1",source_head="a"*40,canonical_repository="owner/cdc",
        canonical_source_identity="sha256:"+"f"*64,release=binding,current_lock=lock,
        rollback_from=None,operation_budget=100)

class DeliveryCLITests(unittest.TestCase):
    def invoke(self,raw,standalone=False):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"request.json";path.write_text(raw);before=set(Path(root).iterdir())
            argv=[sys.executable,"-B",str(ROOT/"scripts"/("release_delivery.py" if standalone else "cdc.py"))]
            if not standalone:argv.append("delivery")
            result=subprocess.run([*argv,str(path)],cwd=root,text=True,capture_output=True)
            self.assertEqual(set(Path(root).iterdir()),before)
            return result

    def test_valid_request_reports_missing_live_authority_and_never_writes(self):
        for standalone in (False,True):
            p=self.invoke(json.dumps(request()),standalone)
            self.assertEqual(p.returncode,0,p.stderr);r=json.loads(p.stdout)
            self.assertEqual(r["action"],"VERIFY_RELEASE_AND_OWNERSHIP")
            self.assertFalse(r["publication_prerequisites_satisfied"])
            self.assertFalse(any(v for k,v in r.items() if k.startswith("authorizes_")))

    def test_duplicates_unknown_fields_and_malformed_release_are_controlled(self):
        raw=json.dumps(request())
        for bad in (raw[:-1]+',"schema":"cdc-delivery-request/v1"}',json.dumps({**request(),"allow_write":True}),
                    json.dumps({**request(),"release":None}),json.dumps({**request(),"current_lock":{"version":None}})):
            for standalone in (False,True):
                p=self.invoke(bad,standalone)
                self.assertEqual(p.returncode,2,p.stderr);self.assertNotIn("Traceback",p.stderr)

    def test_downgrade_requires_historical_acceptance_and_retains_full_gates(self):
        r=request();r["release"].update(version="3.1.0",release_ref="refs/heads/release/v3.1.0")
        with self.assertRaises(ValueError):release_delivery.plan(r)
        r["rollback_from"]="9"*40
        result=release_delivery.plan(r)
        self.assertEqual(result["mode"],"rollback")
        self.assertIn("verified_historical_consumer_acceptance",result["required_live_checks"])
        self.assertFalse(result["authorizes_force_push"])

    def test_deeply_nested_json_is_rejected_without_a_traceback(self):
        for standalone in (False,True):
            p=self.invoke("["*1500+"0"+"]"*1500,standalone)
            self.assertEqual(p.returncode,2)
            self.assertNotIn("Traceback",p.stderr)

if __name__=="__main__":unittest.main()

