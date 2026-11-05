"""Resolve public scholarly metadata with at most two network requests per paper.

No credentials, browser sessions or local/private URLs. Values come from arXiv,
Crossref, or publisher citation metadata. Incomplete resolution is explicit.
"""
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
import json
import re
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

ALLOWED = ('arxiv.org', 'export.arxiv.org', 'doi.org', 'api.crossref.org',
           'biorxiv.org', 'medrxiv.org', 'nature.com', 'science.org', 'cell.com',
           'academic.oup.com', 'pnas.org', 'journals.plos.org', 'elifesciences.org',
           'pmc.ncbi.nlm.nih.gov', 'europepmc.org', 'link.springer.com',
           'onlinelibrary.wiley.com', 'pubs.acs.org', 'sciencedirect.com',
           'openreview.net', 'proceedings.mlr.press', 'jmlr.org', 'aclanthology.org')
MAX_BYTES = 3 * 1024 * 1024


def _safe(url):
    try:
        u = urlsplit(url)
        host = (u.hostname or '').lower()
        return (u.scheme == 'https' and not u.username and not u.password
                and u.port in (None, 443)
                and any(host == d or host.endswith('.' + d) for d in ALLOWED))
    except (TypeError, ValueError):
        return False


def _plain(value):
    value = re.sub(r'<[^>]+>', ' ', value or '')
    return re.sub(r'\s+', ' ', unescape(value)).strip()


def _norm_title(value):
    return re.sub(r'[^\w]+', '', _plain(value).casefold(), flags=re.UNICODE)


def _date(parts):
    try:
        vals = parts['date-parts'][0]
        return '-'.join([str(vals[0])] + [str(int(v)).zfill(2) for v in vals[1:3]])
    except (KeyError, IndexError, TypeError, ValueError):
        return ''


class _NoRedirect(HTTPRedirectHandler):
    # Count redirects as requests too: callers explicitly follow at most one.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Budget:
    def __init__(self):
        self.count = 0
        self.deadline = time.monotonic() + 20
        self.opener = build_opener(_NoRedirect())

    def fetch(self, url):
        while True:
            if not _safe(url): raise ValueError('unsupported_public_source')
            remaining = self.deadline - time.monotonic()
            if self.count >= 2 or remaining <= 0: raise TimeoutError('metadata_request_budget_exhausted')
            self.count += 1
            req = Request(url, headers={'User-Agent':'PaperInbox/0.1 (personal scholarly metadata)',
                                        'Accept':'application/json, application/atom+xml, text/html;q=0.8'})
            try:
                with self.opener.open(req, timeout=min(10, remaining)) as r:
                    data = r.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES: raise ValueError('metadata_response_too_large')
                    return data.decode(r.headers.get_content_charset() or 'utf-8', errors='replace'), url
            except HTTPError as exc:
                if exc.code in (301,302,303,307,308) and exc.headers.get('Location'):
                    url = urljoin(url, exc.headers['Location'])
                    continue
                raise


class _MetadataHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.abstract_depth = 0
        self.depth = 0
        self.abstract = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == 'meta':
            key = (attrs.get('name') or attrs.get('property') or '').lower()
            content = attrs.get('content','').strip()
            if content: self.meta.setdefault(key, []).append(content)
        if tag.lower() in ('div','section','p','blockquote'):
            self.depth += 1
            marker = ' '.join([attrs.get('class',''), attrs.get('id','')]).lower()
            # Narrow explicit abstract containers, not generic article descriptions.
            if not self.abstract_depth and (re.search(r'(^|\s)(abstract|abstract-content|abstract-text|abstract__text)(\s|$)',marker)
                    or attrs.get('id') in ('Abs1-content','abstract-content')):
                self.abstract_depth = self.depth

    def handle_endtag(self, tag):
        if tag.lower() in ('div','section','p','blockquote'):
            if self.abstract_depth and self.depth == self.abstract_depth:
                self.abstract_depth = 0
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.abstract_depth: self.abstract.append(data)


def _html(text, url):
    parser = _MetadataHTML()
    parser.feed(text)
    m = parser.meta
    def one(*keys):
        return next((_plain(m[k][0]) for k in keys if m.get(k)), '')
    out = {'title':one('citation_title','dc.title'),
           'authors':m.get('citation_author',m.get('dc.creator',[])),
           'abstract':one('citation_abstract','dc.description') or _plain(' '.join(parser.abstract)),
           'published':one('citation_publication_date','citation_date','dc.date'),
           'doi':one('citation_doi','dc.identifier.doi'),
           'journal':one('citation_journal_title'),
           'affiliations':m.get('citation_author_institution',[])}
    # Avoid generic site og:description: it frequently repeats a title, not an abstract.
    pdf = m.get('citation_pdf_url', [''])[0]
    if pdf:
        pdf = urljoin(url, pdf)
        if _safe(pdf): out['pdf_url'] = pdf
    if out['published']:
        out['published'] = out['published'].replace('/', '-')
    return {k:v for k,v in out.items() if v}


def _arxiv(text, expected_id):
    root = ET.fromstring(text)
    ns = {'a':'http://www.w3.org/2005/Atom'}
    entry = root.find('a:entry',ns)
    if entry is None: raise ValueError('arxiv_entry_missing')
    get = lambda k: _plain(entry.findtext('a:'+k,default='',namespaces=ns))
    entry_id = get('id').rsplit('/',1)[-1]
    if re.sub(r'v\d+$','',entry_id) != re.sub(r'v\d+$','',expected_id):
        raise ValueError('arxiv_identity_mismatch')
    out = {'title':get('title'),'abstract':get('summary'),'published':get('published')[:10],
           'authors':[_plain(a.findtext('a:name',default='',namespaces=ns)) for a in entry.findall('a:author',ns)],
           'pdf_url':'https://arxiv.org/pdf/'+expected_id}
    return {k:v for k,v in out.items() if v}


def _crossref(item):
    authors, affiliations = [], []
    for a in item.get('author',[]):
        name = ' '.join(x for x in (a.get('given',''),a.get('family','')) if x).strip() or a.get('name','')
        if name: authors.append(name)
        affiliations.extend(x.get('name','') for x in a.get('affiliation',[]) if x.get('name'))
    out = {'title':_plain((item.get('title') or [''])[0]),'authors':authors,
           'abstract':_plain(item.get('abstract','')),'doi':item.get('DOI',''),
           'published':_date(item.get('published') or item.get('published-online') or item.get('issued') or {}),
           'journal':_plain((item.get('container-title') or [''])[0]),
           'affiliations':list(dict.fromkeys(affiliations))}
    for link in item.get('link',[]):
        if link.get('content-type') == 'application/pdf' and _safe(link.get('URL','')):
            out['pdf_url'] = link['URL']; break
    return {k:v for k,v in out.items() if v}


def resolve_paper(p):
    """Return a copy enriched from public metadata; failures never invent fields."""
    out = dict(p)
    budget = _Budget()
    warnings = []
    title = str(p.get('title','')).strip()
    url = str(p.get('url','')).strip()
    doi = str(p.get('doi') or p.get('DOI') or '').strip()
    data = {}
    try:
        if url and not _safe(url): raise ValueError('unsupported_public_source')
        host = (urlsplit(url).hostname or '').lower()
        if host in ('doi.org','www.doi.org'):
            from urllib.parse import unquote
            doi = unquote(urlsplit(url).path.lstrip('/'))
        if doi.startswith('https://doi.org/'): doi = doi.split('doi.org/',1)[1]
        if host in ('arxiv.org','www.arxiv.org','export.arxiv.org'):
            match = re.match(r'^/(?:abs|html|pdf)/(.+?)(?:\.pdf)?/?$',urlsplit(url).path)
            if not match: raise ValueError('unsupported_arxiv_url')
            arxiv_id = match.group(1)
            if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?',arxiv_id):
                raise ValueError('invalid_arxiv_id')
            try:
                text, _ = budget.fetch('https://export.arxiv.org/api/query?' + urlencode({'id_list':arxiv_id}))
                data = _arxiv(text, arxiv_id)
            except Exception:
                text, final_url = budget.fetch('https://arxiv.org/abs/'+arxiv_id)
                data = _html(text,final_url)
        elif doi:
            if not re.fullmatch(r'10\.\d{4,9}/\S+',doi,re.I): raise ValueError('invalid_doi')
            text, _ = budget.fetch('https://api.crossref.org/works/'+quote(doi,safe=''))
            item = json.loads(text)['message']
            if str(item.get('DOI','')).casefold() != doi.casefold(): raise ValueError('doi_identity_mismatch')
            data = _crossref(item)
            if not url: out['url'] = 'https://doi.org/'+doi
        elif url:
            text, final_url = budget.fetch(url)
            data = _html(text, final_url)
            if not data.get('title'): warnings.append('官方页面未提供可解析题录')
        elif title:
            text, _ = budget.fetch('https://api.crossref.org/works?' + urlencode({'query.title':title,'rows':3}))
            candidates = json.loads(text)['message'].get('items',[])
            scored = [(SequenceMatcher(None,_norm_title(title),_norm_title((x.get('title') or [''])[0])).ratio(),x) for x in candidates]
            scored.sort(key=lambda x:x[0],reverse=True)
            if not scored or scored[0][0] < .94: raise ValueError('no_high_confidence_title_match')
            # Avoid two near-identical but distinct DOIs when the supplied title cannot resolve them.
            if len(scored)>1 and scored[1][0] >= .94 and scored[0][0]-scored[1][0] < .015 and scored[0][1].get('DOI') != scored[1][1].get('DOI'):
                raise ValueError('ambiguous_title_match')
            score,item = scored[0]
            data = _crossref(item)
            out['metadata_title_similarity'] = round(score,4)
            if item.get('DOI'): out['url'] = 'https://doi.org/'+item['DOI']
        else:
            raise ValueError('title_and_url_missing')
        for key,value in data.items():
            if value: out[key] = value
        if data: out['metadata_source'] = 'arXiv' if 'arxiv.org' in host else ('Crossref' if doi or not url else host)
    except Exception as exc:
        warnings.append('元数据未完全解析：'+type(exc).__name__ + ((' ('+str(exc)+')') if isinstance(exc,ValueError) else ''))
    for key,label in [('title','标题'),('authors','作者'),('abstract','原摘要'),('published','发表日期')]:
        if not out.get(key): warnings.append(label+'未获取')
    if warnings: out['metadata_warning'] = '；'.join(dict.fromkeys(warnings))
    elif 'metadata_warning' in out: out.pop('metadata_warning')
    return out
