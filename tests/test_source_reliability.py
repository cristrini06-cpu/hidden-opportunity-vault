import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent / 'agent'
spec = importlib.util.spec_from_file_location('hov_monitor',ROOT/'monitor.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = dt.datetime(2026,10,29,2,38,tzinfo=dt.timezone.utc)
CFG = json.loads((ROOT/'source_registry.json').read_text())
D = {s['id']:s for s in CFG['sources']}
PAGE=('<html><head><title>Official initiative</title></head><body>'+('Program information is posted here. '*20)+'</body></html>').encode()

class ReliabilityTests(unittest.TestCase):
    def scan(self, sources, fetcher):
        with tempfile.TemporaryDirectory() as d:
            return m.scan(sources, Path(d), NOW, fetcher=fetcher, pause_seconds=0)
    def test_registry_source_count_expanded(self):
        self.assertEqual(len(CFG['sources']),72)
        self.assertEqual({s['id'] for s in CFG['sources']},len(D) and set(D))
    def test_adidas_is_link_only(self):
        self.assertEqual(D['watch_hov005']['monitor_policy'], 'link_only')
    def test_1iota_is_link_only(self):
        self.assertEqual(D['watch_hov023']['monitor_policy'], 'link_only')
    def test_brazil_source_is_official_bcb_explainer(self):
        s=D['watch_hov044']; self.assertEqual(s['allowed_hosts'],['www.bcb.gov.br'])
        self.assertIn('www.bcb.gov.br/',s['url'])
        self.assertTrue(m.is_trusted(s['url'],s))
        self.assertFalse(m.is_trusted('https://fake-bcb.gov.br/',s))
    def test_js_page_is_limited_without_fake_deal(self):
        s=D['watch_hov005']
        r=self.scan([s],lambda _: (b'<html><div id="root"></div></html>',s['url']))
        self.assertEqual(r['sources_scanned'],1)
        self.assertEqual(r['sources_limited'],1)
        self.assertEqual(len(r['failures']),0)
        self.assertEqual(len(r['candidates']),0)
        self.assertEqual(r['source_health'][0]['status'],'limited')
    def test_static_watch_is_accurately_monitored(self):
        s=D['watch_hov044']
        r=self.scan([s],lambda _: (PAGE,s['url']))
        self.assertEqual(r['sources_scanned'],1)
        self.assertEqual(r['sources_limited'],0)
        self.assertEqual(r['source_health'][0]['status'],'ok')
        self.assertEqual(r['source_changes'],0)
    def test_redirect_to_untrusted_host_still_error(self):
        s=D['watch_hov044']
        r=self.scan([s],lambda _: (PAGE,'https://phishing-login.example/'))
        self.assertEqual(len(r['failures']),1)
        self.assertIn('Redirected outside trusted source',r['failures'][0])
    def test_http403_not_masked(self):
        s=D['watch_hov044']
        def blocked(_): raise HTTPError(s['url'],403,'Forbidden',{},None)
        r=self.scan([s],blocked)
        self.assertEqual(len(r['failures']),1)
        self.assertIn('access restricted',r['failures'][0])
    def test_low_text_on_regular_site_still_flags_failure(self):
        s=D['watch_hov044']
        r=self.scan([s],lambda _: (b'<html></html>',s['url']))
        self.assertEqual(len(r['failures']),1)
        self.assertEqual(r['sources_limited'],0)
    def test_automated_offers_are_unverified(self):
        s=D['feed_ftc_refunds']
        rss=('<?xml version="1.0"?><rss><channel><item><title>FTC Opens Refund Claim Portal</title>'
             '<description>Eligible consumers can file refund claims before deadline</description>'
             '<link>https://www.ftc.gov/refunds/open</link>'
             '<pubDate>Wed, 28 Oct 2026 20:00:00 GMT</pubDate></item></channel></rss>').encode()
        r=self.scan([s],lambda _: (rss,s['url']))
        self.assertEqual(len(r['candidates']),1)
        self.assertTrue(r['candidates'][0]['review_required'])
    def test_government_headlines_not_valid_offers(self):
        self.assertIsNone(m.classify_offer('FTC Launches Personalized Pricing and Compensation Inquiry','', 'FTC Consumer Protection'))
        self.assertIsNone(m.classify_offer('FTC Sends More than $9.8 Million to Consumers','', 'FTC Consumer Protection'))
    def test_no_live_requests_in_unit_tests(self):
        s=D['watch_hov023']
        r=self.scan([s],lambda _: (b'<div id="app"></div>',s['url']))
        self.assertEqual(r['sources_limited'],1)
    def test_all_health_records_accounted_for(self):
        s1=D['watch_hov005'];s2=D['watch_hov044']
        def testfetch(url):
            s=s1 if url==s1['url'] else s2
            return (PAGE,s['url'])
        r=self.scan([s1,s2],testfetch)
        self.assertEqual([x['status'] for x in r['source_health']],['limited','ok'])
        self.assertEqual(len(r['source_health']),2)

if __name__=='__main__':unittest.main(verbosity=2)
