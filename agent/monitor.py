#!/usr/bin/env python3
"""Hidden Opportunity Vault source-monitor agent (Python standard library only).

This program collects CANDIDATES from approved public RSS/Atom feeds and monitors
changes to opted-in official program pages. It deliberately never declares a
candidate to be a verified offer, and never automatically publishes a listing.
"""
from __future__ import annotations
import argparse, datetime as dt, email.utils, hashlib, html, json, re, sys, time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
UTC=dt.timezone.utc
MAX_BYTES=2_000_000
NOW=lambda: dt.datetime.now(UTC)

class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[];self.ignore=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','svg'):self.ignore+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','svg'):self.ignore=max(0,self.ignore-1)
    def handle_data(self,data):
        if not self.ignore:self.parts.append(data)

def text_only(raw):
    x=TextExtractor()
    try:x.feed(raw)
    except Exception:pass
    return re.sub(r'\s+',' ',html.unescape(' '.join(x.parts))).strip()

def get_json(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return default

def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

def fetch(url):
    if not url.startswith('https://'):raise ValueError('Only HTTPS sources are permitted')
    req=Request(url,headers={'User-Agent':'HiddenOpportunityVaultResearchBot/1.0 (+manual editorial review)','Accept':'application/atom+xml,application/rss+xml,application/xml,text/xml,text/html;q=0.8'})
    with urlopen(req,timeout=12) as response:
        final=response.geturl()
        if not final.startswith('https://'):raise ValueError('Unsafe redirect')
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError('Source too large')
        return raw,final

def is_trusted(url,source):
    host=(urlparse(url).hostname or '').lower()
    return any(host==allowed or host.endswith('.'+allowed) for allowed in source.get('allowed_hosts',[]))

def rtext(node,key):
    for child in node:
        if child.tag.rsplit('}',1)[-1].casefold()==key.casefold():
            return ''.join(child.itertext()).strip()
    return ''

def feed_records(raw,source,now):
    root=ET.fromstring(raw)
    items=[c for c in root.iter() if c.tag.rsplit('}',1)[-1] in ('item','entry')]
    kw=[k.casefold() for k in source.get('keywords',[])]
    out=[]
    for e in items[:160]:
        title=html.unescape(rtext(e,'title'))[:200]
        body=text_only(rtext(e,'description') or rtext(e,'summary') or rtext(e,'content'))[:400]
        if not title or (kw and not any(k in (title+' '+body).casefold() for k in kw)):continue
        link=rtext(e,'link')
        if not link:
            for el in e:
                if el.tag.rsplit('}',1)[-1]=='link' and el.attrib.get('href'):
                    if el.attrib.get('rel','alternate')=='alternate':link=el.attrib['href'];break
        link=urljoin(source['url'],link)
        if not is_trusted(link,source):continue
        raw_date=rtext(e,'pubDate') or rtext(e,'published') or rtext(e,'updated')
        stamped=''
        if raw_date:
            try:
                parsed=email.utils.parsedate_to_datetime(raw_date)
                if parsed is None:raise ValueError()
            except Exception:
                try:parsed=dt.datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                except Exception:parsed=None
            if parsed is not None:
                parsed=parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
                if parsed > now+dt.timedelta(days=2) or parsed < now-dt.timedelta(days=45):continue
                stamped=parsed.date().isoformat()
        uid='rss_'+hashlib.sha256(link.encode()).hexdigest()[:20]
        out.append({'id':uid,'title':title,'url':link,'provider':source['name'],
                    'source':source['name'],'country':source.get('country','Worldwide'),
                    'kind':'new_item','summary':body or 'Matching official-source publication; editorial verification required.',
                    'published_at':stamped,'found_at':now.date().isoformat()})
    return out

def site_digest(raw):
    s=text_only(raw.decode('utf-8',errors='replace'))[:160_000]
    # Target meaningful page text; dynamic banners may still cause false positives.
    return hashlib.sha256(s.casefold().encode()).hexdigest(),len(s)

def scan(sources,storage,now,fetcher=fetch):
    state=get_json(storage/'state.json',{'seen_ids':[],'watched_hashes':{}})
    prev=get_json(storage/'discoveries.json',{'candidates':[]})
    known={r['id']:r for r in prev.get('candidates',[]) if isinstance(r,dict) and r.get('id')}
    seen=set(state.get('seen_ids',[]))
    hashes=dict(state.get('watched_hashes',{}))
    errors=[];fresh=0;scanned=0
    for source in sources:
        url=source.get('url','')
        if not url.startswith('https://') or not source.get('allowed_hosts') or not is_trusted(url,source):
            errors.append(source.get('name','unnamed')+': configuration rejected');continue
        try:
            raw,final=fetcher(url)
            if not is_trusted(final,source):raise ValueError('Redirected outside trusted source')
            scanned+=1
            if source['mode']=='rss':
                rows=feed_records(raw,source,now)
                for item in rows:
                    if item['id'] not in seen:
                        known[item['id']]=item;seen.add(item['id']);fresh+=1
            elif source['mode']=='watch':
                digest,length=site_digest(raw)
                if length<180:raise ValueError('Page returned insufficient text')
                sid=source['id']
                if sid in hashes and hashes[sid]!=digest:
                    event_id='changed_'+hashlib.sha256((sid+digest).encode()).hexdigest()[:20]
                    if event_id not in seen:
                        known[event_id]={'id':event_id,'title':'Official page changed — '+source['name'],
                            'url':final,'provider':source['name'],'source':source['name'],
                            'country':source.get('country','Worldwide'),'kind':'page_changed',
                            'summary':'This official program page changed. This does NOT establish that a new perk, deal or open application exists. Inspect original program terms and dates.',
                            'found_at':now.date().isoformat()}
                        seen.add(event_id);fresh+=1
                hashes[sid]=digest
            else:raise ValueError('Unknown source mode')
        except Exception as ex:
            errors.append(source.get('name','unnamed')+': '+str(ex)[:145])
        # Caution and politeness: no burst crawling
        time.sleep(0.1)
    # Keep recent leads; candidates do not become verified by aging.
    floor=now.date()-dt.timedelta(days=90)
    candidates=sorted([r for r in known.values() if r.get('found_at','')>=floor.isoformat()],key=lambda r:r.get('found_at',''),reverse=True)[:300]
    report={'format':'HOV-AGENT-1','generated_at':now.isoformat(timespec='seconds'),
            'sources_scanned':scanned,'sources_configured':len(sources),'new_candidates':fresh,
            'failures':errors,'candidates':candidates,
            'disclaimer':'UNVERIFIED monitoring leads only. No claims of availability or eligibility. Editorial review required.'}
    # seen ids capped but preserves old de-dup for recent 12 months
    write_json(storage/'state.json',{'seen_ids':sorted(seen)[-3000:],'watched_hashes':hashes})
    write_json(storage/'discoveries.json',report)
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--sources',default=str(HERE/'source_registry.json'));p.add_argument('--out',default=str(HERE/'data'));a=p.parse_args()
    source_cfg=json.loads(Path(a.sources).read_text(encoding='utf-8'))
    if source_cfg.get('format')!='HOV-SOURCES-1':raise ValueError('Invalid source registry')
    report=scan(source_cfg['sources'],Path(a.out),NOW())
    print('Sources checked:',report['sources_scanned'],'/',report['sources_configured'],'| New candidates:',report['new_candidates'],'| Outstanding leads:',len(report['candidates']),'| Errors:',len(report['failures']))
    for err in report['failures']:print('WARN:',err)

if __name__=='__main__':main()
