"""Bounded, cached metadata enrichment from official arXiv pages only."""
from html.parser import HTMLParser
from html import escape
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from author_affiliations import from_arxiv_html, from_author_records, merge_associations

CACHE_DIR = Path(__file__).resolve().parent / 'cache' / 'arxiv-metadata'
RETRY_SECONDS = 86400
CACHE_VERSION = 4
MAX_BYTES = 4 * 1024 * 1024
ARXIV_ID = re.compile(r'(?:\d{4}\.(?:\d{4}|\d{5})|[a-zA-Z][a-zA-Z.-]*/\d{7})(?:v[1-9]\d*)?')
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
EMAIL = re.compile(r'(?:\{[^{}]*\}\s*|[^\s<>@]+)@[^\s<>@]+')


def _clean(value):
    return re.sub(r'\s+', ' ', value).strip()


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def arxiv_id_from_url(url):
    """Return an exact official abs/pdf/html URL's ID, or an empty string."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in
                ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org') or
                parsed.username or parsed.password or parsed.port not in (None, 80, 443) or
                parsed.query or parsed.fragment):
            return ''
        match = re.fullmatch(r'/(abs|html|pdf)/(.+?)/?', parsed.path)
        if not match:
            return ''
        identifier = match.group(2)
        if match.group(1) == 'pdf' and identifier.endswith('.pdf'):
            identifier = identifier[:-4]
        return identifier if ARXIV_ID.fullmatch(identifier) else ''
    except (TypeError, ValueError):
        return ''


class _AbsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs = dict(attrs)
            key = (attrs.get('name') or attrs.get('property') or '').lower()
            value = _clean(attrs.get('content', ''))
            if value:
                self.meta.setdefault(key, []).append(value)


def _parse_abs(text, identifier):
    parser = _AbsParser()
    parser.feed(text)
    meta = parser.meta
    declared = meta.get('citation_arxiv_id', [])
    if declared and declared[0] != identifier:
        # An unversioned citation ID can describe the requested version.
        if declared[0] != re.sub(r'v\d+$', '', identifier):
            raise ValueError('arxiv_identity_mismatch')
    result = {'authors': _unique(meta.get('citation_author', []))}
    for key in ('citation_publication_date', 'citation_date', 'dc.date'):
        if meta.get(key):
            result['published'] = meta[key][0].replace('/', '-')[:10]
            break
    return {key: value for key, value in result.items() if value}


def _parse_atom(text, identifier, paper=None):
    root = ET.fromstring(text)
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    entry = root.find('a:entry', ns)
    if entry is None:
        raise ValueError('arxiv_entry_missing')
    actual = entry.findtext('a:id', default='', namespaces=ns)
    actual_id = arxiv_id_from_url(actual)
    if (not actual_id or re.sub(r'v\d+$', '', actual_id) != re.sub(r'v\d+$', '', identifier)
            or ('v' in identifier.rsplit('/', 1)[-1] and actual_id != identifier)):
        raise ValueError('arxiv_identity_mismatch')
    authors, affiliations, records = [], [], []
    for author in entry.findall('a:author', ns):
        name = _clean(author.findtext('a:name', default='', namespaces=ns))
        authors.append(name)
        author_units = []
        for affiliation in author.iter('{http://arxiv.org/schemas/atom}affiliation'):
            value = _clean(' '.join(affiliation.itertext()))
            affiliations.append(value)
            author_units.append(value)
        records.append({'name': name, 'affiliations': author_units})
    result = {'authors': _unique(authors), 'affiliations': _unique(affiliations)}
    identity = dict(paper or {})
    if not identity.get('authors'):
        identity['authors'] = result['authors']
    identity.setdefault('affiliations', result['affiliations'])
    linked = from_author_records(records, identity)
    result.update(linked)
    result['authors'] = identity['authors']
    published = entry.findtext('a:published', default='', namespaces=ns)
    if published:
        result['published'] = published[:10]
    return {key: value for key, value in result.items() if value or key == 'author_affiliations'}


class _AffiliationParser(HTMLParser):
    """Collect only explicit affiliation elements, including nested inline text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.capture_depth = None
        self.parts = []
        self.affiliations = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        excluded = (tag in ('script', 'style', 'sup') or
                    attrs.get('href', '').lower().startswith('mailto:') or
                    bool(classes & {'ltx_role_email', 'ltx_contact_name', 'ltx_personname'}))
        inherited = self.stack[-1][1] if self.stack else False
        if tag not in VOID_TAGS:
            self.stack.append((tag, inherited or excluded))
            explicit = ('ltx_affiliation' in classes or
                        {'ltx_contact', 'ltx_role_affiliation'}.issubset(classes))
            if explicit and self.capture_depth is None and not (inherited or excluded):
                self.capture_depth = len(self.stack)
                self.parts = []
        if self.capture_depth is not None and tag == 'br':
            self.parts.append(' ')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        indices = [i for i, (open_tag, _) in enumerate(self.stack) if open_tag == tag]
        if not indices:
            return
        index = indices[-1]
        if self.capture_depth is not None and index < self.capture_depth:
            value = _clean(EMAIL.sub('', ''.join(self.parts))).strip(' ,;')
            if value:
                self.affiliations.append(value)
            self.capture_depth = None
            self.parts = []
        elif self.capture_depth is not None and tag in ('div', 'p'):
            self.parts.append(' ')
        del self.stack[index:]

    def handle_data(self, data):
        if self.capture_depth is not None and self.stack and not self.stack[-1][1]:
            self.parts.append(data)


class _NumberedAffiliationParser(HTMLParser):
    """Read only numbered lines introduced by a break inside an author name block."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.person_depth = None
        self.marker_depth = None
        self.marker = []
        self.waiting = False
        self.active = False
        self.parts = []
        self.affiliations = []

    def finish(self):
        value = _clean(EMAIL.sub('', ''.join(self.parts))).strip(' ,;')
        if self.active and value:
            self.affiliations.append(value)
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get('class', '').split())
        if tag == 'br' and self.person_depth is not None:
            self.finish()
            self.waiting = True
        if tag in VOID_TAGS:
            return
        self.stack.append(tag)
        if 'ltx_personname' in classes:
            self.person_depth = len(self.stack)
        if tag == 'sup' and self.person_depth is not None and (self.waiting or self.active):
            self.finish()
            self.marker_depth = len(self.stack)
            self.marker = []

    def handle_endtag(self, tag):
        indices = [i for i, open_tag in enumerate(self.stack) if open_tag == tag]
        if not indices:
            return
        index = indices[-1]
        if self.marker_depth is not None and index < self.marker_depth:
            self.active = bool(re.fullmatch(r'\d+', _clean(''.join(self.marker))))
            self.waiting = False
            self.marker_depth = None
        if self.person_depth is not None and index < self.person_depth:
            self.finish()
            self.person_depth = None
            self.waiting = False
        del self.stack[index:]

    def handle_data(self, data):
        if self.marker_depth is not None:
            self.marker.append(data)
        elif self.active:
            self.parts.append(data)
        elif self.waiting and data.strip():
            self.waiting = False


def _author_only(value, authors):
    remaining = _clean(re.sub(r'[^\w]+', ' ', value.casefold()))
    variants = []
    for author in authors:
        variants.append(author)
        if ',' in author:
            family, given = author.split(',', 1)
            variants.append(given + ' ' + family)
    for author in sorted(variants, key=len, reverse=True):
        normalized = _clean(re.sub(r'[^\w]+', ' ', author.casefold()))
        if normalized:
            remaining = re.sub(r'(?<!\w)' + re.escape(normalized) + r'(?!\w)', ' ', remaining)
    return not remaining.strip()


class _FrontmatterAffiliationParser(HTMLParser):
    """Accept numbered affiliations only immediately after a verified author line."""
    def __init__(self, authors):
        super().__init__(convert_charrefs=True)
        self.authors = authors
        self.html = None
        self.plain = []
        self.sup_depth = 0
        self.after_authors = False
        self.candidate = False
        self.stopped = False
        self.affiliations = []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get('class', '').split())
        if tag == 'section' or 'ltx_abstract' in classes:
            self.stopped = True
        if tag == 'p' and not self.stopped:
            self.html = []
            self.plain = []
            self.candidate = self.after_authors
            self.after_authors = False
        elif self.html is not None:
            self.html.append(self.get_starttag_text())
        if self.html is not None and tag == 'sup':
            self.sup_depth += 1

    def handle_endtag(self, tag):
        if self.html is None:
            return
        if tag == 'sup':
            self.sup_depth = max(0, self.sup_depth - 1)
        if tag == 'p':
            if self.candidate:
                parser = _NumberedAffiliationParser()
                parser.feed('<span class="ltx_personname"><br>' + ''.join(self.html) + '</span>')
                self.affiliations.extend(parser.affiliations)
            elif _clean(''.join(self.plain)) and _author_only(''.join(self.plain), self.authors):
                self.after_authors = True
            self.html = None
        else:
            self.html.append('</' + tag + '>')

    def handle_data(self, data):
        if self.html is not None:
            self.html.append(escape(data))
            if not self.sup_depth:
                self.plain.append(data)


def _parse_affiliations(text, authors=()):
    parser = _AffiliationParser()
    parser.feed(text)
    parser.close()
    numbered = _NumberedAffiliationParser()
    numbered.feed(text)
    numbered.close()
    frontmatter = _FrontmatterAffiliationParser(authors)
    frontmatter.feed(text)
    frontmatter.close()
    return _unique(value for value in parser.affiliations + numbered.affiliations + frontmatter.affiliations
                   if not _author_only(value, authors))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Fetcher:
    def __init__(self):
        self.deadline = time.monotonic() + 24
        self.opener = build_opener(_NoRedirect())
        self.requests = 0

    def fetch(self, url):
        original = url
        for _ in range(3):
            try:
                return self._fetch_once(url)
            except HTTPError as exc:
                location = exc.headers.get('Location', '')
                if exc.fp is not None:
                    exc.close()
                if exc.code not in (301, 302, 303, 307, 308) or not location:
                    raise
                target = urljoin(url, location)
                parsed = urlsplit(target)
                identifier = arxiv_id_from_url(target)
                original_id = arxiv_id_from_url(original)
                same_paper = (identifier and original_id and
                              re.sub(r'v\d+$', '', identifier) == re.sub(r'v\d+$', '', original_id))
                same_api = (parsed.path == '/api/query' and parsed.query == urlsplit(original).query)
                if (parsed.scheme != 'https' or parsed.hostname not in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org')
                        or parsed.username or parsed.password or parsed.port not in (None, 443)
                        or not (same_paper or same_api)):
                    raise ValueError('unsupported_arxiv_redirect')
                url = target
        raise ValueError('arxiv_redirect_limit')

    def _fetch_once(self, url):
        self.requests += 1
        if self.requests > 6:
            raise TimeoutError('metadata_request_budget_exhausted')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('metadata_time_budget_exhausted')
        request = Request(url, headers={'User-Agent': 'PaperInbox/0.1 (scholarly metadata)',
                                       'Accept': 'text/html, application/atom+xml'})
        with self.opener.open(request, timeout=min(8, remaining)) as response:
            chunks, count = [], 0
            while True:
                if time.monotonic() >= self.deadline:
                    raise TimeoutError('metadata_time_budget_exhausted')
                chunk = response.read(min(65536, MAX_BYTES + 1 - count))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
                if count > MAX_BYTES:
                    raise ValueError('metadata_response_too_large')
            return b''.join(chunks).decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


def _read_cache(path, identifier):
    try:
        if path.stat().st_size > MAX_BYTES:
            return {}
        cached = json.loads(path.read_text(encoding='utf-8'))
        if (isinstance(cached, dict) and cached.get('version') == CACHE_VERSION
                and cached.get('id') == identifier
                and isinstance(cached.get('data'), dict)
                and isinstance(cached.get('checked_at'), (int, float))
                and isinstance(cached.get('sources'), list)
                and isinstance(cached.get('errors'), list)):
            return cached
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _write_cache(path, cached):
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(path.parent), delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(cached, stream, ensure_ascii=False)
        temp_path.replace(path)
    except OSError:
        pass
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def enrich_arxiv(p):
    """Return a copy enriched with authors, published, affiliations and source URLs.

    Failed/absent fields preserve input values. Partial results and failures are
    retried after one day. Complete results are refreshed after thirty days.
    Non-arXiv URLs are returned unchanged. All content is parsed as inert data.
    """
    out = dict(p)
    url = p.get('url', '')
    identifier = arxiv_id_from_url(url)
    if not identifier:
        try:
            host = urlsplit(url).hostname
        except (TypeError, ValueError):
            host = None
        if host in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
            out['metadata_note'] = 'arXiv URL 或标识符无效'
        return out
    path = CACHE_DIR / (identifier.replace('/', '_') + '.json')
    cached = _read_cache(path, identifier)
    data = dict(cached.get('data', {}))
    sources = list(cached.get('sources', []))
    errors = []
    complete = (all(data.get(key) for key in ('authors', 'published', 'affiliations'))
                and all(data.get('author_affiliations', {}).get(name) for name in data.get('authors', [])))
    ttl = RETRY_SECONDS * (30 if complete else 1)
    if not cached or time.time() - cached.get('checked_at', 0) >= ttl:
        fetcher = _Fetcher()
        abs_url = 'https://arxiv.org/abs/' + identifier
        api_url = 'https://export.arxiv.org/api/query?' + urlencode({'id_list': identifier})
        html_url = 'https://arxiv.org/html/' + identifier

        def collect(source, parser):
            try:
                found = {key: value for key, value in parser(fetcher.fetch(source)).items()
                         if value or key == 'author_affiliations'}
                if found:
                    if 'author_affiliations' in found and (data.get('author_affiliations') or found['author_affiliations']):
                        incoming = dict(found, authors=found.get('authors') or data.get('authors', []))
                        found.update(merge_associations(data, incoming))
                    data.update(found)
                    sources.append(source)
            except Exception as exc:
                errors.append(type(exc).__name__)

        if not data.get('authors') or not data.get('published'):
            collect(abs_url, lambda text: _parse_abs(text, identifier))
        def parse_html(text):
            affiliations = _parse_affiliations(text, data.get('authors', [])) or data.get('affiliations', [])
            return from_arxiv_html(text, dict(data, affiliations=affiliations))

        if (not data.get('affiliations') or
                not all(data.get('author_affiliations', {}).get(name) for name in data.get('authors', []))):
            collect(html_url, parse_html)
        if (any(not data.get(key) for key in ('authors', 'published', 'affiliations'))
                or not all(data.get('author_affiliations', {}).get(name) for name in data.get('authors', []))):
            collect(api_url, lambda text: _parse_atom(text, identifier, data))
        data = {key: value for key, value in data.items() if value or key == 'author_affiliations'}
        _write_cache(path, {'version': CACHE_VERSION, 'id': identifier, 'checked_at': time.time(), 'data': data,
                            'sources': _unique(sources), 'errors': errors})
    else:
        errors = cached.get('errors', [])
    out.update({key: value for key, value in data.items() if value or key == 'author_affiliations'})
    existing_sources = out.get('metadata_sources', [])
    if isinstance(existing_sources, str):
        existing_sources = [existing_sources]
    if sources:
        out['metadata_sources'] = _unique(list(existing_sources) + sources)
    missing = [label for key, label in [('authors', '作者'), ('published', '日期'), ('affiliations', '单位')]
               if not out.get(key)]
    notes = []
    if out.get('metadata_note'):
        notes.append(str(out['metadata_note']))
    if missing:
        notes.append('arXiv 未获取' + '、'.join(missing))
    if errors:
        notes.append('部分 arXiv 来源获取失败（' + '、'.join(_unique(errors)) + '）')
    if notes:
        out['metadata_note'] = '；'.join(_unique(notes))
    return out
