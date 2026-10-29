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


def site_digest(raw):
    body = text_only(raw.decode('utf-8', errors='replace'))[:160_000]
    return hashlib.sha256(body.casefold().encode()).hexdigest(), len(body)


def scan(sources, storage, now, fetcher=fetch, pause_seconds=0.1):
    storage = Path(storage)
    state = get_json(storage / 'state.json', {'seen_ids': [], 'watched_hashes': {}})
    previous = get_json(storage / 'discoveries.json', {'candidates': [], 'page_changes': []})
    # Retrospectively screen previously queued headlines. This removes old
    # non-actionable FTC stories when the updated agent next runs.
    valid_sources = {s.get('name'): s for s in sources if s.get('mode') == 'rss'}
    known = {}
    for record in previous.get('candidates', []):
        if not isinstance(record, dict) or not record.get('id') or not record.get('url'):
            continue
        parent = valid_sources.get(record.get('source'))
        if not parent or not is_trusted(record['url'], parent):
            continue
        category = classify_offer(record.get('title', ''), record.get('summary', ''), parent['name'])
        if not category:
            continue
        published_at = record.get('published_at', '')
        # Legacy items had an original publish date; do not infer it from the
        # date the Agent happened to discover the item.
        if not published_at or source_date(published_at, now) is None:
            continue
        record['opportunity_type'] = category
        record['review_required'] = True
        known[record['id']] = record

    seen = set(state.get('seen_ids', []))
    hashes = dict(state.get('watched_hashes', {}))
    page_changes = list(previous.get('page_changes', []))[-200:]
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
                    if size < 180:
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
    candidates = sorted(
        [v for v in known.values() if v.get('found_at', '') >= floor],
        key=lambda r: (r.get('found_at', ''), r.get('published_at', '')), reverse=True
    )[:300]
    page_changes = [v for v in page_changes if v.get('found_at', '') >= floor][-200:]
    report = {
        'format': 'HOV-AGENT-1', 'filter_version': '2026-10-actionable-v2',
        'generated_at': now.isoformat(timespec='seconds'),
        'sources_scanned': scanned, 'sources_configured': len(sources),
        'sources_limited': limited, 'source_warnings': warnings,
        'source_health': health,
        'new_candidates': fresh, 'failures': errors,
        'source_changes': changes_found, 'page_changes': page_changes,
        'candidates': candidates,
        'disclaimer': 'UNVERIFIED actionable candidates only. No guarantee of availability or eligibility. Changed pages and unrelated news are excluded from opportunities.'
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
