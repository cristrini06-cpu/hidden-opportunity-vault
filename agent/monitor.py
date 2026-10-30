#!/usr/bin/env python3
"""Hidden Opportunity Vault: conservative, source-specific opportunity discovery.

The agent monitors public official sources. It produces UNVERIFIED CANDIDATES, not
verified offers; only an editor may publish a customer-facing listing. Generic
news, FTC enforcement notices, and merely changed webpages are not offers.
Python standard library only; compatible with the existing GitHub workflow and
homepage HOV-AGENT-1 report format.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HERE = Path(__file__).resolve().parent
UTC = dt.timezone.utc
MAX_BYTES = 2_000_000
MAX_AGE_DAYS = 45
NOW = lambda: dt.datetime.now(UTC)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.ignore = max(0, self.ignore - 1)

    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)


def text_only(raw):
    extractor = TextExtractor()
    try:
        extractor.feed(raw)
    except Exception:
        pass
    return re.sub(r'\s+', ' ', html.unescape(' '.join(extractor.parts))).strip()


def get_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def fetch(url):
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS sources are permitted')
    req = Request(url, headers={
        'User-Agent': 'HiddenOpportunityVaultResearchBot/1.1 (+manual editorial review)',
        'Accept': 'application/atom+xml,application/rss+xml,application/xml,text/xml,text/html;q=0.8',
    })
    # One restrained retry for transient service errors. Deliberate HTTP 403
    # restrictions are not bypassed: the source must be checked manually.
    for attempt in range(2):
        try:
            with urlopen(req, timeout=10) as response:
                final = response.geturl()
                if not final.startswith('https://'):
                    raise ValueError('Unsafe redirect')
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError('Source too large')
                return raw, final
        except HTTPError as exc:
            if attempt == 0 and exc.code in (429, 500, 502, 503, 504):
                time.sleep(0.8)
                continue
            raise
        except (TimeoutError, URLError):
            if attempt == 0:
                time.sleep(0.8)
                continue
            raise
    raise RuntimeError('Source retrieval could not complete')


def is_trusted(url, source):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    return (parsed.scheme == 'https' and bool(host)
            and not parsed.username and not parsed.password
            and any(host == allowed or host.endswith('.' + allowed)
                    for allowed in source.get('allowed_hosts', [])))


def rtext(node, key):
    for child in node:
        if child.tag.rsplit('}', 1)[-1].casefold() == key.casefold():
            return ''.join(child.itertext()).strip()
    return ''


def match(pattern, text):
    return re.search(pattern, text, re.I) is not None


# Conservative filters: a source publishing about money does not automatically
# provide a reward. Only positively identified application/claim windows count.
# Both the title and the excerpt must be examined; broad keyword appearance in
# the body alone is NOT sufficient to create a lead.
NEWS_ONLY = (
    r'\b(investigation|inquiry|report|study finds|survey finds|scrutiniz|'
    r'charges? against|sues?|lawsuit|allegation|court (orders?|shuts?|rules?)|'
    r'permanently shuts?|shuts? down|sentenc|indict|arrest|warns?|'
    r'consumer alert|price transparency|settles? charges?|settlement with|'
    r'files? complaint|announces? enforcement|proposes? rule|'
    r'policy update|rulemaking|webinar|speeches?|newsletter|'
    r'analysis|fraud prevention|scammers?|FTC orders?)\b'
)

REFUND_OPEN = (
    r'\b(file|submit|apply|register)\b.{0,45}\b(claim|refund|reimbursement|redress)\b|'
    r'\b(claim|refund|reimbursement)\b.{0,45}\b(application|form|portal|deadline|now open)\b|'
    r'\b(refund claims? (are|is) (now )?open|claim (period|window) (is )?open)\b'
)

PRIZE_OPEN = (
    r'\b(challenge|competition|contest|prize|award|fellowship|grant)\b.{0,100}'
    r'\b(apply|applications?|registration|register|submissions?|enter|entries|deadline|open|invites?)\b|'
    r'\b(apply|applications?|registration|register|submissions?|enter)\b.{0,100}'
    r'\b(challenge|competition|contest|prize|fellowship|grant)\b'
)

OTHER_OPEN = (
    r'\b(apply|applications?|registration|register|sign up|enroll|join|submit|book|claim)\b.{0,90}'
    r'\b(trial|testing|panel|rewards?|benefit|free|cashback|rebate|grants?|'
    r'scholarship|prize|fellowship|competition|challenge|refund|discount)\b|'
    r'\b(free|paid|cashback|rebate|scholarship|grant|prize)\b.{0,90}'
    r'\b(apply|applications?|register|sign up|submit|claim|open)\b'
)


def classify_offer(title, summary, source_name):
    """Return a suggested category or None; never certifies eligibility.

    Avoid publishing press coverage or paying-people headlines as opportunities.
    Specifically, receiving an FTC check is NOT a claim/application opening.
    """
    title = re.sub(r'\s+', ' ', title or '').strip()
    summary = re.sub(r'\s+', ' ', summary or '').strip()
    combined = title + ' ' + summary
    provider = (source_name or '').casefold()

    if not title or match(NEWS_ONLY, title):
        return None

    if 'ftc' in provider or 'federal trade commission' in provider:
        # Sending restitution to already-identified victims is not an offer.
        if match(r'\b(sends?|sending|mails?|mailing|distributes?|distributing|returns?|returning)\b.{0,80}\b(refunds?|checks?|payments?|money)\b', title):
            return None
        if match(r'\b(orders?|settles?|allegations?|lawsuit|enforcement|court|scam)\b', title):
            return None
        # A claim application must be explicit, in the headline or excerpt.
        return 'consumer_refund_claim' if match(REFUND_OPEN, combined) else None

    if 'nasa' in provider or 'space agency' in provider:
        if not match(r'\b(challenge|competition|contest|prize|grant|fellowship)\b', title):
            return None
        return 'innovation_application' if match(PRIZE_OPEN, combined) else None

    # Other official RSS feeds require actionable information, not broad mentions.
    if match(r'\b(inquiry|announcement|report|press release|lawsuit|settlement)\b', title):
        return None
    return 'application_or_reward' if match(OTHER_OPEN, combined) else None


def source_date(raw_date, now):
    if not raw_date:
        return None
    parsed = None
    try:
        parsed = email.utils.parsedate_to_datetime(raw_date)
    except (ValueError, TypeError, IndexError):
        pass
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if parsed > now + dt.timedelta(days=1) or parsed < now - dt.timedelta(days=MAX_AGE_DAYS):
        return None
    return parsed.date().isoformat()


def feed_records(raw, source, now):
    root = ET.fromstring(raw)
    entries = [c for c in root.iter() if c.tag.rsplit('}', 1)[-1] in ('item', 'entry')]
    out = []
    for entry in entries[:160]:
        title = html.unescape(rtext(entry, 'title'))[:200]
        excerpt = text_only(rtext(entry, 'description') or rtext(entry, 'summary')
                            or rtext(entry, 'content'))[:500]
        category = classify_offer(title, excerpt, source.get('name', ''))
        if not category:
            continue
        link = rtext(entry, 'link')
        if not link:
            for element in entry:
                if element.tag.rsplit('}', 1)[-1] == 'link' and element.attrib.get('href'):
                    if element.attrib.get('rel', 'alternate') == 'alternate':
                        link = element.attrib['href']
                        break
        if not link:
            continue
        link = urljoin(source['url'], link)
        if not is_trusted(link, source):
            continue
        raw_date = (rtext(entry, 'pubDate') or rtext(entry, 'published')
                    or rtext(entry, 'updated'))
        published_at = source_date(raw_date, now)
        # Undated official releases are too hard to distinguish from old posts.
        if published_at is None:
            continue
        uid = 'rss_' + hashlib.sha256(link.encode()).hexdigest()[:20]
        out.append({
            'id': uid, 'title': title, 'url': link,
            'provider': source['name'], 'source': source['name'],
            'country': source.get('country', 'Worldwide'),
            'kind': 'new_item', 'opportunity_type': category,
            'summary': ('Original publication: ' + published_at + '. ' +
                        (excerpt or 'Candidate detected. Confirm the original terms and eligibility.'))[:590],
            'published_at': published_at, 'found_at': now.date().isoformat(),
            'review_required': True,
        })
    return out


class OpportunityLinkExtractor(HTMLParser):
    """Visible anchor text on public official directory pages only."""
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.text = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript','svg'):
            self.skip_depth += 1
        if self.skip_depth == 0 and tag == 'a':
            self.href = dict(attrs).get('href', '')
            self.text = []

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            label = re.sub(r'\s+', ' ', html.unescape(' '.join(self.text))).strip()
            self.links.append((self.href, label))
            self.href = None
            self.text = []
        if tag in ('script','style','noscript','svg') and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.href is not None and not self.skip_depth:
            self.text.append(data)


# Whitelisted page formats: extract a SPECIFIC named opportunity with evidence.
# A generic link to a directory, guide, old award, or site navigation is not a lead.
NON_OPPORTUNITY_TITLE = re.compile(
    r'^(?:grants? (?:and|&) funding|apply for funding|funding opportunities|'
    r'available funding opportunities|past funding opportunities|'
    r'site readiness program guide\.?|open calls?|current calls?|'
    r'request a challenge|view (?:closed )?challenge|view challenges|'
    r'learn about.*|see (?:all|more).*|browse.*|apply now|'
    r'how to apply|funding programs?|all programs|benefits?|'
    r'upcoming challenges|closed challenges)$', re.I)


def parse_closing_date(label):
    label = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', label.strip(), flags=re.I)
    for fmt in ('%d %b %Y', '%d %B %Y'):
        try:
            return dt.datetime.strptime(label, fmt).date()
        except ValueError:
            pass
    return None


def specific_title(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return (24 <= len(text) <= 165 and len(text.split()) >= 4
            and not NON_OPPORTUNITY_TITLE.match(text)
            and not match(r'\b(closed|past|expired|under evaluation|results|winners?|'
                          r'blog|articles?|guide|learn about|request a challenge)\b', text))


def active_innocentive_challenges(raw, source, now, final_url):
    """Read the current *named* challenge list, never site-navigation labels.

    A named challenge needs an adjacent future Closing date AND stated Award.
    No assumption is made that any visitor meets the challenge eligibility.
    """
    page = raw.decode('utf-8', errors='replace')
    visible = text_only(page)
    boundary = re.search(r'\bUnder Evaluation Challenges\b', visible, re.I)
    if boundary:
        visible = visible[:boundary.start()]
    if not match(r'\bClosing date\s*:', visible) or not match(r'\bAward\s*:', visible):
        return []
    parser = OpportunityLinkExtractor()
    try: parser.feed(page)
    except Exception: return []
    results=[]; seen_urls=set(); seen_titles=set()
    for href, label in parser.links:
        title=re.sub(r'\s+', ' ', label).strip()
        if not specific_title(title): continue
        url=urljoin(final_url,href).split('#',1)[0]
        if not is_trusted(url,source) or url.rstrip('/')==final_url.rstrip('/'):
            continue
        # Named open item MUST appear before the closed/under-evaluation section.
        pos = visible.find(title)
        if pos < 0: continue
        tail = visible[pos+len(title):pos+len(title)+250]
        # Only accept a date and award attached to THIS item, before its View Challenge link.
        tail = re.split(r'\bView (?:Closed )?Challenge\b',tail,maxsplit=1,flags=re.I)[0]
        closing = re.search(r'Closing date\s*:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,10}\s+\d{4})',tail,re.I)
        award = re.search(r'\bAward\s*:\s*(.{3,100}?)(?=$|\bClosing date\s*:)',tail,re.I)
        if not closing or not award: continue
        date = parse_closing_date(closing.group(1))
        if not date or date < now.date() or date > now.date()+dt.timedelta(days=730): continue
        award_text = re.sub(r'\s+', ' ', award.group(1)).strip(' .;,')[:95]
        if not award_text or len(award_text)<3:continue
        norm=re.sub(r'\W+','',title.casefold())
        if url in seen_urls or norm in seen_titles:continue
        seen_urls.add(url);seen_titles.add(norm)
        results.append({
          'id':'challenge_'+hashlib.sha256(url.encode()).hexdigest()[:20],
          'title':title,'url':url,'provider':source['name'],'source':source['name'],
          'country':source.get('country','Worldwide'),'kind':'named_active_challenge',
          'opportunity_type':'innovation_prize_challenge',
          'summary':f'Official directory lists closing date {date.isoformat()} and award: {award_text}. Eligibility and availability need manual confirmation at the source.',
          'deadline':date.isoformat(),'award':award_text,'published_at':'',
          'found_at':now.date().isoformat(),'review_required':True,
          'verification_status':'unverified','priority':'specialist'
        })
    return results[:12]


def bao_current_fund(raw, source, now, final_url):
    """One specifically defined currently-listed arts fund, not menu headings.

    Zero generic broad 'Grant & Funding' links are considered opportunities.
    """
    visible=text_only(raw.decode('utf-8', errors='replace'))
    found=re.search(r'(Call for (\d{4}) BAO Professional Development Fund)',visible,re.I)
    if not found:return []
    start=found.start()
    # Require it to be in the Current Calls section rather than archived calls.
    before=visible[:start]
    current=before.lower().rfind('current calls for artists')
    archive=max(before.lower().rfind('past calls'),before.lower().rfind('closed calls'))
    if current<0 or archive>current:return []
    tail=visible[found.end():found.end()+1400]
    deadline=re.search(r'Application Deadline\s*:\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',tail,re.I)
    amount=re.search(r'Funding Amount\s*:\s*(up to\s*\$[\d,]+(?:\.\d\d)?)',tail,re.I)
    if not deadline or not amount: return []
    try: due=dt.datetime.strptime(deadline.group(1).replace(',',''),'%B %d %Y').date()
    except ValueError:return []
    if not (now.date()<=due<=now.date()+dt.timedelta(days=730)):return []
    title=found.group(1).strip()
    return [{
      'id':'program_'+hashlib.sha256((final_url+'#'+str(found.group(2))+'-bao-profdev').encode()).hexdigest()[:20],
      'title':title,'url':final_url,'provider':source['name'],'source':source['name'],
      'country':source.get('country','Canada'),'kind':'named_current_grant',
      'opportunity_type':'arts_professional_development_fund',
      'summary':f'Official current-calls page lists {amount.group(1)} and an application deadline of {due.isoformat()} (or until funds are depleted). Restricted eligibility; verify before approval.',
      'deadline':due.isoformat(),'award':amount.group(1), 'published_at':'',
      'found_at':now.date().isoformat(),'review_required':True,
      'verification_status':'unverified','priority':'specialist'
    }]




def trybers_active_campaigns(raw, source, now, final_url):
    """Product campaigns linked from the official Netherlands front page.

    Registration/selection and potential discounted keep-or-return terms must
    never be described as a free guaranteed product.
    """
    page = raw.decode('utf-8', errors='replace')
    visible = text_only(page)
    if not re.search(r'\bActive campaigns\b', visible, re.I):
        return []
    parser = OpportunityLinkExtractor()
    parser.feed(page)
    out = []
    seen = set()
    for href, label in parser.links:
        url = urljoin(final_url, href).split('#', 1)[0]
        if not is_trusted(url, source):
            continue
        if not re.search(r'/campaigns/[^/?#]{8,}', urlparse(url).path, re.I):
            continue
        label = re.sub(r'\s+', ' ', label).strip()
        if not re.search(r'\bby\s+[A-Za-z0-9]', label, re.I):
            continue
        title = re.sub(r'\s+by\s+[A-Za-z0-9À-ž][^|]*$', '', label, flags=re.I).strip()
        if not (12 <= len(title) <= 150 and len(title.split()) >= 3):
            continue
        if match(r'\b(closed|expired|past campaigns|campaigns|browse all|view all)\b', title):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append({
            'id': 'product_' + hashlib.sha256(url.encode()).hexdigest()[:20],
            'title': 'Product testing: ' + title,
            'url': url, 'provider': source['name'], 'source': source['name'],
            'country': source.get('country', 'Netherlands'),
            'kind': 'consumer_product_trial', 'opportunity_type': 'consumer_product_testing',
            'summary': 'Listed in the official Active campaigns section. Free registration; selection is required. Participants may need to return the product or purchase it at a discount. Verify campaign terms, region and availability.',
            'found_at': now.date().isoformat(), 'review_required': True,
            'verification_status': 'unverified', 'priority': 'consumer',
        })
    return out[:20]


def takepart_active_studies(raw, source, now, final_url):
    """Specific publicly listed paid-research projects with direct URLs.

    Project/session dates are not interpreted as application deadlines.
    Older projects remain on the source homepage, so filter by date first.
    """
    page = raw.decode('utf-8', errors='replace')
    visible = text_only(page)
    if not re.search(r'\bCurrent projects\b', visible, re.I):
        return []
    parser = OpportunityLinkExtractor()
    parser.feed(page)
    out=[]; seen=set()
    for href, label in parser.links:
        url=urljoin(final_url, href).split('#',1)[0]
        if not is_trusted(url,source) or not re.search(r'^/jobs/[^/]+/?$',urlparse(url).path):
            continue
        label=re.sub(r'\s+',' ',label).strip()
        cash=re.search(r'\$([1-9][0-9]{1,4})(?!\d)',label)
        # The source publishes US-style dates, which indicate research/session
        # periods rather than an application deadline.
        dates=re.findall(r'(?<!\d)(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(\d{2})(?!\d)',label)
        if not cash or not dates:
            continue
        parsed=[]
        for mm,dd,yy in dates:
            try:parsed.append(dt.date(2000+int(yy),int(mm),int(dd)))
            except ValueError:pass
        if not parsed or max(parsed)<now.date() or min(parsed)>now.date()+dt.timedelta(days=365):
            continue
        if not match(r'\b(research|study|studies|testing|interview|diary|group|survey)\b',label):
            continue
        title=re.split(r'\s+\d{1,2}/\d{1,2}/\d{2}\b',label,maxsplit=1)[0]
        title=re.sub(r'^(?:Online groups and interviews|Online tasks and diary studies|Face.to.face|Focus group)\s+', '',title,flags=re.I).strip()
        if not (10<=len(title)<=125 and len(title.split())>=2):
            continue
        if url in seen:continue
        seen.add(url)
        out.append({
            'id':'research_'+hashlib.sha256(url.encode()).hexdigest()[:20],
            'title':'Paid research: '+title, 'url':url,
            'provider':source['name'],'source':source['name'],
            'country':source.get('country','United States'),
            'kind':'consumer_paid_study','opportunity_type':'paid_consumer_research',
            'summary':f'Official current-project listing advertises ${cash.group(1)} for a qualifying research project and shows a session/project date through {max(parsed).isoformat()}. Apply through the official page; eligibility and recruitment status require confirmation.',
            'award':'$'+cash.group(1), 'event_end':max(parsed).isoformat(),
            'found_at':now.date().isoformat(), 'review_required':True,
            'verification_status':'unverified', 'priority':'consumer'
        })
    return out[:20]

def specific_page_candidates(raw, source, now, final_url):
    parser = {'innocentive_active_challenges': active_innocentive_challenges,
              'bao_current_fund': bao_current_fund,
              'trybers_active_campaigns': trybers_active_campaigns,
              'takepart_active_studies': takepart_active_studies}.get(source.get('discovery_strategy'))
    return parser(raw,source,now,final_url) if parser else []


def site_digest(raw):
    body = text_only(raw.decode('utf-8', errors='replace'))[:160_000]
    return hashlib.sha256(body.casefold().encode()).hexdigest(), len(body)


def scan(sources, storage, now, fetcher=fetch, pause_seconds=0.1):
    storage = Path(storage)
    state = get_json(storage / 'state.json', {'seen_ids': [], 'watched_hashes': {}})
    previous = get_json(storage / 'discoveries.json', {'candidates': [], 'page_changes': []})
    # Retrospectively screen previously queued headlines. This removes old
    # non-actionable FTC stories when the updated agent next runs.
    valid_sources = {s.get('name'): s for s in sources}
    known = {}
    for record in previous.get('candidates', []):
        if not isinstance(record, dict) or not record.get('id') or not record.get('url'):
            continue
        parent = valid_sources.get(record.get('source'))
        if not parent or not is_trusted(record['url'], parent):
            continue
        if parent.get('mode') == 'rss':
            category = classify_offer(record.get('title', ''), record.get('summary', ''), parent['name'])
            if not category:continue
            published_at = record.get('published_at', '')
            if not published_at or source_date(published_at, now) is None:continue
            record['opportunity_type'] = category
        if record.get('event_end') and str(record['event_end']) < now.date().isoformat():continue
        if record.get('deadline') and str(record['deadline']) < now.date().isoformat():continue
        record['review_required'] = True
        known[record['id']] = record

    seen = set(state.get('seen_ids', []))
    hashes = dict(state.get('watched_hashes', {}))
    page_changes = list(previous.get('page_changes', []))[-200:]
    active_specific_ids=set()
    successful_specific_sources=set()
    errors = []
    warnings = []
    health = []
    scanned = 0
    limited = 0
    fresh = 0
    changes_found = 0

    for source in sources:
        name = str(source.get('name', 'unnamed'))
        sid = str(source.get('id', ''))
        url = source.get('url', '')
        record = {
            'id': sid, 'name': name, 'mode': source.get('mode', ''),
            'url': url, 'status': 'unchecked',
            'checked_at': now.isoformat(timespec='seconds'),
            'detail': '',
        }
        if (not isinstance(url, str) or not url.startswith('https://')
                or not source.get('allowed_hosts') or not is_trusted(url, source)):
            record.update(status='failed', detail='Source configuration rejected')
            errors.append(name + ': ' + record['detail'])
            health.append(record)
            continue
        try:
            raw, final = fetcher(url)
            # Redirects to unrelated hosts must not be treated as official
            # without independently establishing the new source identity.
            if not is_trusted(final, source):
                raise ValueError('Redirected outside trusted source; manually review the destination')
            scanned += 1
            record['final_url'] = final
            if source.get('mode') == 'rss':
                candidates = feed_records(raw, source, now)
                for candidate in candidates:
                    if candidate['id'] not in seen:
                        known[candidate['id']] = candidate
                        fresh += 1
                        seen.add(candidate['id'])
                record.update(status='ok', detail='Official feed parsed; candidates are unverified')
            elif source.get('mode') == 'watch':
                # Some genuine partner portals require JavaScript or a user
                # session. A link check is not a test for open invitations.
                if source.get('monitor_policy') == 'link_only':
                    limited += 1
                    msg = ('Interactive page: link reachable, but active offers '
                           'cannot be extracted by this static scanner')
                    record.update(status='limited', detail=msg)
                    warnings.append(name + ': ' + msg)
                else:
                    digest, size = site_digest(raw)
                    if size < (80 if source.get('discovery_strategy') else 180):
                        raise ValueError('Page returned insufficient text; may require JavaScript or login')
                    if sid in hashes and hashes[sid] != digest:
                        eid = 'changed_' + hashlib.sha256((sid + digest).encode()).hexdigest()[:20]
                        if eid not in seen:
                            # Changed content does NOT prove a new offer.
                            page_changes.append({
                                'id': eid, 'title': 'Page change: ' + name,
                                'url': final, 'source': name,
                                'country': source.get('country', 'Worldwide'),
                                'kind': 'page_changed', 'found_at': now.date().isoformat(),
                                'summary': 'Source page changed; no new reward or eligibility is established.',
                            })
                            changes_found += 1
                            seen.add(eid)
                    hashes[sid] = digest
                    if source.get('discovery_strategy'):
                        active = specific_page_candidates(raw, source, now, final)
                        successful_specific_sources.add(name)
                        for candidate in active:
                            active_specific_ids.add(candidate['id'])
                            known[candidate['id']] = candidate
                            if candidate['id'] not in seen:
                                fresh += 1
                                seen.add(candidate['id'])
                        record.update(status='ok', detail=f'Named actionable opportunities checked; {len(active)} currently listed (not yet verified by editor)')
                    else:
                        record.update(status='ok', detail='Content monitored; changes are not verified offers')
            else:
                raise ValueError('Unknown source mode')
        except Exception as exc:
            detail = str(exc)[:180]
            if isinstance(exc, HTTPError):
                detail = ('HTTP ' + str(exc.code) +
                          (' (access restricted; do not bypass)' if exc.code in (401, 403)
                           else ' (rate limited; retry later)' if exc.code == 429
                           else ' (missing or moved page)' if exc.code in (404, 410)
                           else ' (upstream error)'))
            record.update(status='failed', detail=detail)
            errors.append(name + ': ' + detail)
        health.append(record)
        if pause_seconds:
            time.sleep(pause_seconds)

    floor = (now.date() - dt.timedelta(days=90)).isoformat()
    # Specialist and consumer leads from an available, successfully parsed
    # source disappear if the official listing no longer contains them.
    specific_names={s['name'] for s in sources if s.get('discovery_strategy')}
    candidates = sorted(
        [v for v in known.values() if v.get('found_at', '') >= floor
         and not (v.get('source') in successful_specific_sources
                  and v.get('source') in specific_names
                  and v.get('id') not in active_specific_ids)],
        key=lambda r: (r.get('priority') == 'consumer',r.get('found_at',''),r.get('published_at','')), reverse=True
    )[:300]
    page_changes = [v for v in page_changes if v.get('found_at', '') >= floor][-200:]
    report = {
        'format': 'HOV-AGENT-1', 'filter_version': '2026-10-v5-consumer-research-verified-source-paths',
        'generated_at': now.isoformat(timespec='seconds'),
        'sources_scanned': scanned, 'sources_configured': len(sources),
        'sources_limited': limited, 'source_warnings': warnings,
        'source_health': health,
        'new_candidates': fresh, 'consumer_candidates': sum(x.get('priority')=='consumer' for x in candidates),
        'specialist_candidates': sum(x.get('priority')=='specialist' for x in candidates), 'failures': errors,
        'source_changes': changes_found, 'page_changes': page_changes,
        'verification_rule': 'Named opportunity, future deadline, benefit and official source required for specialized page extracts.',
        'sources_failed': len(errors), 'sources_healthy': len([h for h in health if h['status']=='ok']),
        'candidates': candidates,
        'disclaimer': 'UNVERIFIED candidates only. Consumer testing/research may require selection, payment or product return. Study dates are not application deadlines. Named specialist offers need manual eligibility confirmation. Page changes and generic news are not live offers.'
    }
    # Preserve order of arrival (not alphabetical order) when trimming seen IDs.
    # A bounded set prevents the state file from growing forever.
    write_json(storage / 'state.json', {
        'seen_ids': sorted(seen)[-5000:], 'watched_hashes': hashes,
    })
    write_json(storage / 'discoveries.json', report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', default=str(HERE / 'source_registry.json'))
    parser.add_argument('--out', default=str(HERE / 'data'))
    args = parser.parse_args()
    cfg = json.loads(Path(args.sources).read_text(encoding='utf-8'))
    if cfg.get('format') != 'HOV-SOURCES-1':
        raise ValueError('Invalid source registry')
    report = scan(cfg['sources'], Path(args.out), NOW())
    print('Sources checked:', report['sources_scanned'], '/', report['sources_configured'],
          '| New opportunity candidates:', report['new_candidates'],
          '| Remaining candidates:', len(report['candidates']),
          '| Changed pages (separate):', report['source_changes'],
          '| Sources with limited monitoring:', report['sources_limited'],
          '| Source errors:', len(report['failures']))
    for warning in report['source_warnings']:
        print('LIMITED:', warning)
    for error in report['failures']:
        print('WARN:', error)


if __name__ == '__main__':
    main()
