import base64,json,unittest
from stable_reader import read_lease_document

class StableReader(unittest.TestCase):
 def test_concurrent_renewal_restarts_entire_snapshot(self):
  refs=iter(['a','b','b','b']);contents=[]
  def api(path):
   if path.startswith('git/ref/'):return {'object':{'sha':next(refs)}}
   revision=path.split('=')[1];contents.append(revision)
   return {'content':base64.b64encode(json.dumps({'revision':revision}).encode()).decode()}
  revision,value=read_lease_document(api)
  self.assertEqual((revision,value),('b',{'revision':'b'}))
  self.assertEqual(contents,['a','b'])
 def test_continuous_drift_fails_with_bounded_reads(self):
  calls=[]
  def api(path):
   calls.append(path)
   if path.startswith('git/ref/'):return {'object':{'sha':str(len(calls))}}
   return {'content':base64.b64encode(b'{}').decode()}
  with self.assertRaises(RuntimeError):read_lease_document(api,attempts=2)
  self.assertEqual(len(calls),6)
