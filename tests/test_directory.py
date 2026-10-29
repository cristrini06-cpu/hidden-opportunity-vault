import datetime as dt
import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent/'agent'
spec=importlib.util.spec_from_file_location('vmonitor',ROOT/'monitor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
S={x['id']:x for x in json.loads((ROOT/'source_registry.json').read_text())['sources']}
NOW=dt.datetime(2026,10,29,7,tzinfo=dt.timezone.utc)
SRC=S['watch_hov061']; BASE=SRC['url']
PAGE=('''<html><body><main><h1>Available challenges</h1>'''+
      '<a href="/challenges/climate-innovation-prize-2026">Climate Innovation Prize Challenge for New Technology</a>'+
      '<a href="https://example.net/scam">Open Challenge for Free Rewards</a>'+
      '<a href="/about">About us</a>'+
      '<a href="/challenges/another">Apply now</a>'+
      '<a href="/news/2026">News announces challenge winners</a>'+
      '<a href="/challenges/climate-innovation-prize-2026">Climate Innovation Prize Challenge for New Technology</a>'+
      '<p>'+'Useful program details. '*30+'</p></main></body></html>').encode()
class DirectoryTests(unittest.TestCase):
 def test_specific_official_directory_find(self):
  a=m.directory_candidates(PAGE,SRC,NOW,BASE)
  self.assertEqual(len(a),1)
  self.assertEqual(a[0]['kind'],'directory_candidate')
  self.assertTrue(a[0]['review_required'])
  self.assertIn('NOT been verified',a[0]['summary'])
 def test_scan_retains_cautious_lead_and_no_duplicate(self):
  with tempfile.TemporaryDirectory() as d:
   storage=Path(d)
   f=lambda _: (PAGE,BASE)
   first=m.scan([SRC],storage,NOW,fetcher=f,pause_seconds=0)
   self.assertEqual(first['new_candidates'],1)
   self.assertEqual(len(first['candidates']),1)
   second=m.scan([SRC],storage,NOW+dt.timedelta(days=1),fetcher=f,pause_seconds=0)
   self.assertEqual(second['new_candidates'],0)
   self.assertEqual(len(second['candidates']),1)
 def test_does_not_surface_watch_changes_as_offers(self):
  with tempfile.TemporaryDirectory() as d:
   storage=Path(d)
   normal=S['watch_hov044'];base=normal['url']
   m.scan([normal],storage,NOW,fetcher=lambda _:(b'<p>' + b'Example '*100+b'</p>',base),pause_seconds=0)
   out=m.scan([normal],storage,NOW+dt.timedelta(days=1),fetcher=lambda _:(b'<p>' + b'Changed '*100+b'</p>',base),pause_seconds=0)
   self.assertEqual(len(out['candidates']),0)
   self.assertEqual(out['source_changes'],1)
   self.assertEqual(len(out['page_changes']),1)
if __name__=='__main__':unittest.main()
