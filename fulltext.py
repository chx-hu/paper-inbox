"""Discover and probe legally public PDFs, with explicit access failures.

No login cookies, paywall bypass, CAPTCHA solving, or implicit proxy settings.
Only a short prefix is read to verify a PDF; attachment download is a separate
operation. institution_proxy_template produces a browser login link only.
"""
import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE = Path(__file__).resolve().parent


def load_config():
    try:
        data = json.loads((BASE / 'config.json').read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _public(url):
    """Reject local/private targets, including every redirect destination."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 80, 443) or not parsed.hostname:
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    except (ValueError, OSError):
        return False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Client:
    def __init__(self, config):
        proxy = config.get('network_proxy') or ''
        if proxy:
            p = urlsplit(proxy)
            # A local HTTP proxy is valid explicit user configuration.
            if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
                raise ValueError('network_proxy must be an HTTP(S) URL without credentials')
        self.opener = build_opener(ProxyHandler({'http': proxy, 'https': proxy} if proxy else {}), _NoRedirect())
        self.deadline = time.monotonic() + 45
        self.count = 0

    def fetch(self, url, pdf=False):
        for _ in range(6):
            if not _public(url):
                raise ValueError('URL is not a public HTTP(S) address')
            remaining = self.deadline - time.monotonic()
            if self.count >= 16 or remaining <= 0:
                raise TimeoutError('full-text lookup request/time budget exhausted')
            self.count += 1
            headers = {'User-Agent': 'PaperInbox/0.1 (personal scholarly full-text lookup)'}
            if pdf:
                headers['Range'] = 'bytes=0-1023'
            try:
                with self.opener.open(Request(url, headers=headers), timeout=min(9, remaining)) as response:
                    raw = response.read(1024 if pdf else 2 * 1024 * 1024 + 1)
                    if not pdf and len(raw) > 2 * 1024 * 1024:
                        raise ValueError('metadata response too large')
                    return raw, url, response.headers.get('Content-Type', '')
            except HTTPError as exc:
                location = exc.headers.get('Location')
                if exc.code in (301, 302, 303, 307, 308) and location:
                    url = urljoin(url, location)
                    exc.close()
                    continue
                exc.close()
                raise
        raise ValueError('too many redirects')


class _PDFMeta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == 'meta' and (values.get('name') or values.get('property') or '').lower() == 'citation_pdf_url':
            if values.get('content'):
                self.urls.append(values['content'])


def _doi(paper):
    doi = str(paper.get('doi') or paper.get('DOI') or '').strip()
    url = str(paper.get('url') or '')
    if not doi and urlsplit(url).hostname in ('doi.org', 'www.doi.org'):
        doi = unquote(urlsplit(url).path.lstrip('/'))
    if not doi and '/content/10.' in url:
        doi = urlsplit(url).path.split('/content/', 1)[1]
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi, flags=re.I)
    doi = re.sub(r'v\d+(?:\.full(?:\.pdf)?)?$', '', doi)
    return doi if re.fullmatch(r'10\.\d{4,9}/\S+', doi, re.I) else ''


def resolve_pdf(paper):
    """Return status available/blocked/unavailable/error plus source and message.

    An available result has pdf_url whose response prefix contained %PDF-.
    open_url is the article landing page; proxy_url, when configured, is a
    user-initiated institutional login route, never a claim of entitlement.
    errors lists actual lookup failures; a 403 is not labelled a paywall.
    """
    config = load_config()
    doi = _doi(paper)
    landing = str(paper.get('url') or ('https://doi.org/' + doi if doi else ''))
    try:
        target = urlsplit(landing)
        if target.scheme not in ('http', 'https') or not target.hostname or target.username or target.password:
            landing = ''
    except ValueError:
        landing = ''
    fallback = {'open_url': landing} if landing else {}
    template = config.get('institution_proxy_template') or ''
    if template and landing and '{url}' in template:
        candidate = template.replace('{url}', quote(landing, safe=''))
        parsed = urlsplit(candidate)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            fallback['proxy_url'] = candidate
    errors = []
    seen = set()
    try:
        client = _Client(config)
    except ValueError as exc:
        return dict(fallback, status='error', source='configuration', message=str(exc))

    def record(source, exc):
        errors.append({'source': source, 'error': 'HTTP %s' % exc.code if isinstance(exc, HTTPError) else str(exc)[:180]})

    def probe(url, source):
        if not url or url in seen:
            return None
        seen.add(url)
        try:
            data, final, _ = client.fetch(url, pdf=True)
            if b'%PDF-' in data[:1024]:
                return dict(fallback, status='available', source=source, pdf_url=final,
                            message='已验证可访问的 PDF 响应；尚未下载或导入 Zotero', errors=errors)
            errors.append({'source': source, 'error': 'response is not a PDF (may require login or browser verification)'})
        except Exception as exc:
            record(source, exc)
        return None

    parsed = urlsplit(landing)
    host = (parsed.hostname or '').lower()
    if host in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
        match = re.fullmatch(r'/(?:abs|pdf|html)/((?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?)(?:\.pdf)?/?', parsed.path)
        if match:
            result = probe('https://arxiv.org/pdf/' + match[1], 'arxiv')
            if result: return result
    if host in ('biorxiv.org', 'www.biorxiv.org', 'medrxiv.org', 'www.medrxiv.org') and parsed.path.startswith('/content/10.'):
        path = re.sub(r'\.(?:full|abstract)(?:\.pdf)?$', '', parsed.path.rstrip('/'))
        result = probe('https://' + host + path + '.full.pdf', 'preprint_repository')
        if result: return result
    result = probe(str(paper.get('pdf_url') or ''), 'supplied_pdf_url')
    if result: return result

    if doi:
        try:
            query = urlencode({'query': 'DOI:"' + doi.replace('"', '') + '"', 'format': 'json', 'resultType': 'core', 'pageSize': 3})
            raw, _, _ = client.fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + query)
            rows = json.loads(raw).get('resultList', {}).get('result', [])
            for row in rows:
                if str(row.get('doi', '')).casefold() != doi.casefold(): continue
                for link in row.get('fullTextUrlList', {}).get('fullTextUrl', []):
                    if str(link.get('documentStyle', '')).lower() == 'pdf' and link.get('availabilityCode') == 'OA':
                        result = probe(link.get('url'), 'EuropePMC_open_access')
                        if result: return result
                pmcid = row.get('pmcid', '')
                if re.fullmatch(r'PMC\d+', pmcid) and row.get('isOpenAccess') == 'Y':
                    result = probe('https://europepmc.org/articles/' + pmcid + '?pdf=render', 'EuropePMC_PMC')
                    if result: return result
        except Exception as exc:
            record('EuropePMC', exc)
        try:
            raw, _, _ = client.fetch('https://api.crossref.org/works/' + quote(doi, safe=''))
            item = json.loads(raw)['message']
            if str(item.get('DOI', '')).casefold() != doi.casefold():
                raise ValueError('Crossref DOI identity mismatch')
            # Crossref links may be TDM/subscription endpoints. Probe only when
            # an explicitly open license is present, and still verify bytes.
            licenses = [str(x.get('URL', '')).lower() for x in item.get('license', [])]
            opened = any(re.match(r'https?://(?:www\.)?creativecommons\.org/(?:licenses|publicdomain)/', x) for x in licenses)
            if opened:
                for link in item.get('link', []):
                    if link.get('content-type') == 'application/pdf':
                        result = probe(link.get('URL'), 'Crossref_open_license')
                        if result: return result
            if item.get('URL') and not landing:
                landing = item['URL']
                fallback['open_url'] = landing
        except Exception as exc:
            record('Crossref', exc)

    if landing:
        try:
            raw, final, content_type = client.fetch(landing)
            if raw.startswith(b'%PDF-'):
                return dict(fallback, status='available', source='article_url', pdf_url=final, message='已验证公开 PDF 响应', errors=errors)
            parser = _PDFMeta()
            parser.feed(raw.decode('utf-8', errors='replace'))
            for candidate in parser.urls[:3]:
                result = probe(urljoin(final, candidate), 'publisher_citation_pdf_url')
                if result: return result
        except Exception as exc:
            record('publisher', exc)
    blocked = any(e['error'] in ('HTTP 401', 'HTTP 403', 'HTTP 429', 'HTTP 451') or 'not a PDF' in e['error'] for e in errors)
    return dict(fallback, status='blocked' if blocked else 'unavailable', source='public_lookup', errors=errors,
                message='未取得可验证的公开 PDF；请打开原文，或使用已配置的机构登录链接（访问权限需由机构确认）')
