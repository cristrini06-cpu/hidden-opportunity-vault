"""Regression: generic directory labels must NOT enter the editorial queue."""
import datetime as dt,importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent/'agent'
spec=importlib.util.spec_from_file_location('monitor',ROOT/'monitor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
CFG={s['id']:s for s in json.loads((ROOT/'source_registry.json').read_text())['sources']}
NOW=dt.datetime(2026,10,29,7,tzinfo=dt.timezone.utc)
GENERIC=b'<html><body><a href="/grant">Grants and Funding</a><a href="/old">past funding opportunities</a>'+(b'<p>Learn about programs.</p>'*20)+b'</body></html>'
class DirectoryTests(unittest.TestCase):
 def test_generic_directory_never_creates_leads(self):
  source=CFG['watch_hov078']
  with tempfile.TemporaryDirectory() as d:
   result=m.scan([source],d,NOW,fetcher=lambda url:(GENERIC,url),pause_seconds=0)
   self.assertEqual(result['candidates'],[])
   self.assertEqual(result['new_candidates'],0)
 def test_source_change_not_promoted_to_deal(self):
  source=CFG['watch_hov044']
  with tempfile.TemporaryDirectory() as d:
   m.scan([source],d,NOW,fetcher=lambda url:(GENERIC,url),pause_seconds=0)
   other=GENERIC+b'<p>Page changed</p>'
   result=m.scan([source],d,NOW+dt.timedelta(days=1),fetcher=lambda url:(other,url),pause_seconds=0)
   self.assertEqual(result['candidates'],[])
   self.assertEqual(result['source_changes'],1)
if __name__=='__main__':unittest.main()
