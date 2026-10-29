"""Tests against the exact false leads shown in the customer's live screenshots."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent/'agent'
spec=importlib.util.spec_from_file_location('m', ROOT/'monitor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
S={s['id']:s for s in json.loads((ROOT/'source_registry.json').read_text())['sources']}
NOW=dt.datetime(2026,10,29,7,0,tzinfo=dt.timezone.utc)
I=S['watch_hov061']; B=S['watch_hov064'];O=S['watch_hov065'];G=S['watch_hov078']
HTML='''<html><head><title>Challenges</title></head><body>
<nav><a href="/challenges/">Challenges</a><a href="/request-challenge/">Request a Challenge</a></nav>
<main><h1>What Challenge Will You Solve Today?</h1>
<a href="/challenge/pipeline-cleaning">Innovative Pipeline Cleaning Solutions</a>
Closing date: 19th Nov 2026 Award: $20,000
<a href="/challenge/pipeline-cleaning">View Challenge</a>
<a href="/challenge/oral-peptide">Enabling oral peptide delivery to achieve bioavailability greater than 4%</a>
Closing date: 14th Dec 2026 Award: $25,000
<a href="/challenge/oral-peptide">View Challenge</a>
<h2>Under Evaluation Challenges</h2>
<a href="/challenge/closed">Closed Prize for Ocean Innovation 2026</a>
Under Evaluation Award: $800,000
<a href="/challenge/closed">View Closed Challenge</a>
</main></body></html>'''.encode()
GENERIC='''<html><body>
<a href="/Pages/GrantsFunding.aspx">Grants and Funding</a>
<a href="/grants">Grants and Funding</a>
<a href="/grantguide">Site Readiness Program Guide.</a>
<a href="/funding">Apply for funding</a>
<a href="/past">past funding opportunities</a>
<a href="/seed">Learn about our SEED and GROW funding pathways under this stream.</a>
<p>General guidance for applicants. Grants Funding Program</p>
</body></html>'''.encode()
BAO='''<html><body><h2>Current Calls for Artists</h2>
<h3>Call for 2026 BAO Professional Development Fund</h3>
<p>Call Opens: July 20, 2026</p>
<p>Application Deadline: November 30, 2026 or until fund is depleted</p>
<p>Fees: FREE - zero cost to apply</p>
<p>Funding Amount: up to $400.00</p>
<p>Open to Brampton-based professional artists and arts administrators.</p>
<h2>Past Calls</h2><h3>Call for 2025 BAO Professional Development Fund</h3>
</body></html>'''.encode()
class Tests(unittest.TestCase):
 def test_no_generic_navigation_titles_in_registry(self):
  for source in (I,B,O,G):
   self.assertNotIn('discover_links',source)
   self.assertNotIn('discovery_terms',source)
 def test_named_challenges_only(self):
  a=m.specific_page_candidates(HTML,I,NOW,I['url'])
  self.assertEqual(len(a),2, [x['title'] for x in a])
  self.assertEqual(sorted(x['deadline'] for x in a),['2026-11-19','2026-12-14'])
  self.assertTrue(all(x['award'] and x['review_required'] for x in a))
  self.assertTrue(all('Official directory lists closing date' in x['summary'] for x in a))
 def test_old_closed_challenge_not_listed(self):
  self.assertNotIn('Closed Prize',str(m.specific_page_candidates(HTML,I,NOW,I['url'])))
 def test_generic_menu_links_not_leads(self):
  self.assertEqual(m.specific_page_candidates(GENERIC,G,NOW,G['url']),[])
  self.assertEqual(m.specific_page_candidates(GENERIC,O,NOW,O['url']),[])
 def test_expired_challenge_not_listed(self):
  stale=HTML.replace(b'19th Nov 2026',b'19th Sep 2026').replace(b'14th Dec 2026',b'14th Dec 2025')
  self.assertEqual(m.specific_page_candidates(stale,I,NOW,I['url']),[])
 def test_require_award_and_deadline(self):
  self.assertEqual(m.specific_page_candidates(HTML.replace(b'Award:',b'Gift:'),I,NOW,I['url']),[])
 def test_bao_specific_current_fund(self):
  a=m.specific_page_candidates(BAO,B,NOW,B['url'])
  self.assertEqual(len(a),1)
  self.assertEqual(a[0]['deadline'],'2026-11-30')
  self.assertIn('$400',a[0]['award'])
 def test_bao_expired_fund_not_listed(self):
  self.assertEqual(m.specific_page_candidates(BAO.replace(b'November 30, 2026',b'September 30, 2026'),B,NOW,B['url']),[])
 def test_scan_new_named_records_no_duplicates(self):
  with tempfile.TemporaryDirectory() as folder:
   sources=[I,B,O,G]
   def f(url):
    s=next(s for s in sources if s['url']==url)
    return ({I['id']:HTML,B['id']:BAO,O['id']:GENERIC,G['id']:GENERIC}[s['id']],url)
   r=m.scan(sources,folder,NOW,fetcher=f,pause_seconds=0)
   self.assertEqual(len(r['candidates']),3)
   self.assertEqual(r['new_candidates'],3)
   self.assertEqual(r['failures'],[])
   r2=m.scan(sources,folder,NOW+dt.timedelta(days=1),fetcher=f,pause_seconds=0)
   self.assertEqual(len(r2['candidates']),3)
   self.assertEqual(r2['new_candidates'],0)
 def test_previous_spam_purged_without_resetting_history(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)
   m.write_json(path/'discoveries.json',{'candidates':[
    {'id':'dir_spam','kind':'directory_candidate','source':G['name'],'title':'Grants and Funding','url':G['url'],'found_at':'2026-10-29'},
    {'id':'dir_spam2','kind':'directory_candidate','source':I['name'],'title':'View Closed Challenge','url':I['url'],'found_at':'2026-10-29'}]})
   m.write_json(path/'state.json',{'seen_ids':['dir_spam','dir_spam2'],'watched_hashes':{}})
   result=m.scan([I],path,NOW,fetcher=lambda url:(HTML,url),pause_seconds=0)
   self.assertNotIn('Grants and Funding',str(result['candidates']))
   self.assertNotIn('Closed Challenge',str(result['candidates']))
   self.assertEqual(len(result['candidates']),2)
 def test_no_offer_if_link_to_untrusted_domain(self):
  evil=HTML.replace(b'/challenge/pipeline-cleaning',b'https://evil.example/challenge/pipeline-cleaning')
  a=m.specific_page_candidates(evil,I,NOW,I['url'])
  self.assertEqual(len(a),1)
if __name__=='__main__':unittest.main(verbosity=2)
