from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from command_timestamp import render

class T(unittest.TestCase):
 def data(self):
  return json.loads((ROOT/"templates"/"command-timestamp-request.json").read_text())
 def now(self,seconds=0):
  return datetime(2026,9,26,16,31,tzinfo=timezone.utc)+timedelta(seconds=seconds)
 def test_format(self):
  self.assertEqual(render(self.data(),now=self.now(10))["display"],"[19:31 26.09]")
 def test_derived_time_source_is_rejected(self):
  d=self.data();d["time_source"]="previous_timestamp"
  with self.assertRaises(ValueError):render(d,now=self.now())
 def test_one_timestamp_per_command(self):
  d=self.data();d["already_timestamped_command_ids"]=[d["command_id"]]
  self.assertEqual(render(d,now=self.now())["action"],"SUPPRESS_DUPLICATE")
 def test_stale_timestamp_is_rejected(self):
  with self.assertRaisesRegex(ValueError,"stale"):
   render(self.data(),now=self.now(91))
 def test_future_drift_is_rejected(self):
  d=self.data();d["observed_at"]="2026-09-26T16:39:00Z"
  with self.assertRaisesRegex(ValueError,"ahead"):
   render(d,now=self.now())
 def test_small_clock_skew_is_tolerated(self):
  d=self.data();d["observed_at"]="2026-09-26T16:31:04Z"
  self.assertEqual(render(d,now=self.now())["action"],"EMIT_ONCE")
if __name__=="__main__":
 unittest.main()
