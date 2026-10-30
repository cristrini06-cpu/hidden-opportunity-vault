import unittest
import datetime as dt
from agent.monitor import trybers_active_campaigns,takepart_active_studies,scan
from pathlib import Path
import json,tempfile
HERE=Path(__file__).resolve().parents[1]
SOURCES=json.loads((HERE/'agent/source_registry.json').read_text())['sources']
TRY=next(s for s in SOURCES if s['name']=='Trybers Product Tests')
TP=next(s for s in SOURCES if s['name']=='Take Part Current Paid Research')
NOW=dt.datetime(2026,10,29,12,tzinfo=dt.timezone.utc)
TRY_HTML=b'''<html><h2>Active campaigns</h2><a href="/campaigns/laifen-mini-hairdryer-green">Laifen Mini Haartrockner Gruen by Laifen</a><a href="/campaigns/cubi-doo-magnetic-tiles-racebaan">Cubi-Doo Magnetic Tiles Racebaan by Cubi-Doo</a><a href="/campaigns/closed-project">Closed campaign by Store</a><a href="https://malicious.example.com/campaigns/secret">Secret Free by Fake</a></html>'''
TP_HTML=b'''<html><h2>Current projects</h2><a href="/jobs/pet-owners-research-2/">Online tasks and diary studies Pet Owners Research 11/02/26 - 11/13/26 US Wide 2-week community $205</a><a href="/jobs/games-research/">Online groups and interviews Games Research 11/04/26 US Wide 45 Minutes $80</a><a href="/jobs/old-research/">Online groups and interviews Food Research 07/20/26 US Wide 1 hour $140</a><a href="/jobs/not-offer/">Information on research projects without value</a></html>'''
class ConsumerScanTests(unittest.TestCase):
 def test_trybers_specific_products_and_discounts(self):
  a=trybers_active_campaigns(TRY_HTML,TRY,NOW,TRY['url'])
  self.assertEqual(len(a),2)
  self.assertTrue(all(x['priority']=='consumer' for x in a))
  self.assertTrue(all(x['url'].startswith('https://www.trybers.com/campaigns/') for x in a))
  self.assertTrue(all('discount' in x['summary'] for x in a))
 def test_paid_research_specific_current_and_paid(self):
  a=takepart_active_studies(TP_HTML,TP,NOW,TP['url'])
  self.assertEqual(len(a),2)
  self.assertTrue(all(x['priority']=='consumer' for x in a))
  self.assertIn('$205',[x['award'] for x in a]);self.assertTrue(all('deadline' not in x for x in a))
 def test_old_studies_disappear_as_time_passes(self):
  a=takepart_active_studies(TP_HTML,TP,dt.datetime(2026,12,1,tzinfo=dt.timezone.utc),TP['url'])
  self.assertEqual(a,[])
 def test_no_generic_page_finds(self):
  self.assertEqual(trybers_active_campaigns(b'<h2>How does it work</h2><a href="/campaigns/">Browse all campaigns</a>',TRY,NOW,TRY['url']),[])
 def test_real_scan_prioritizes_consumer_and_deduplicates(self):
  def mock(url):return (TP_HTML,TP['url']) if 'takepart' in url else (TRY_HTML,TRY['url'])
  with tempfile.TemporaryDirectory() as t:
   r=scan([TRY,TP],t,NOW,fetcher=mock,pause_seconds=0)
   self.assertEqual(len(r['candidates']),4)
   self.assertEqual(r['consumer_candidates'],4)
   self.assertEqual(r['new_candidates'],4)
   r2=scan([TRY,TP],t,NOW,fetcher=mock,pause_seconds=0)
   self.assertEqual(r2['new_candidates'],0)
   self.assertEqual(len(r2['candidates']),4)
if __name__=='__main__':unittest.main()
