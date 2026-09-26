import sys, unittest, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import execution_lease_v2 as v2
from git_lease_store import validate_coordination_record, validate_coordination_transition

OWNER=str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
INV={"invocation_id":"wake-1","automation_id":"auto-1","conversation_id":"chat-1","execution_surface":"watchdog","started_at_utc":"2026-01-01T10:00:00Z"}

class Tests(unittest.TestCase):
    def test_valid_owned_v2_is_supported_by_git_store(self):
        r=v2.acquire(v2.initialize("example/project","refs/heads/main"),OWNER,"2026-01-01T10:00:01Z",invocation=INV)
        self.assertIs(validate_coordination_record(r),r)

    def test_generation58_style_partial_v1_patch_is_rejected(self):
        r=v2.initialize("example/project","refs/heads/main")
        r.update(owner_id=OWNER,generation=1,acquired_at_utc="2026-01-01T10:00:01Z",
                 heartbeat_at_utc="2026-01-01T10:00:01Z",expires_at_utc="2026-01-01T10:20:01Z")
        self.assertIsNone(r["invocation"]); self.assertIsNone(r["finalization"])
        with self.assertRaises((ValueError,TypeError)):
            validate_coordination_record(r)

    def test_v2_cannot_downgrade_to_v1(self):
        previous=v2.initialize("example/project","refs/heads/main")
        legacy=v2.legacy.initialize("example/project","refs/heads/main")
        with self.assertRaisesRegex(ValueError,"cannot downgrade"):
            validate_coordination_transition(previous,legacy)

if __name__=="__main__": unittest.main()
