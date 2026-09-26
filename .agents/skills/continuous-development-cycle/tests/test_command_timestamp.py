from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from command_timestamp import render
class T(unittest.TestCase):
 def data(self):
  return json.loads((ROOT/"templates"/"command-timestamp-request.json").read_text())
 def test_format(self):
  self.assertEqual(render(self.data())["display"],"[19:31 26.09]")
 def test_derived_time_source_is_rejected(self):
  d=self.data()
  d["time_source"]="previous_timestamp"
  with self.assertRaises(ValueError):
   render(d)
 def test_one_timestamp_per_command(self):
  d=self.data()
  d["already_timestamped_command_ids"]=[d["command_id"]]
  self.assertEqual(render(d)["action"],"SUPPRESS_DUPLICATE")
if __name__=="__main__":
 unittest.main()
