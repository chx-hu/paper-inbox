"""Version-aware public author metadata; preserve source-specific provenance."""
from html.parser import HTMLParser
from difflib import SequenceMatcher
import re
import json
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.parse import urlsplit
from paper_metadata import _Budget, _norm_title, _safe
from author_affiliations import from_author_records

SCHEMA = 2

class CitationAuthors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.records = []
        self.title = ''
        self.doi = ''
        self.pdf = ''
    def handle_starttag(self, tag, attrs):
        if tag != 'meta': return
        a = dict(attrs); key = a.get('name', '').lower(); value = a.get('content', '').strip()
        if not value: return
        if key == 'citation_title': self.title = value
        elif key == 'citation_doi': self.doi = value
        elif key == 'citation_pdf_url': self.pdf = value
        elif key == 'citation_author': self.records.append({'name': value, 'affiliations': []})
        elif key == 'citation_author_institution' and self.records:
            # Highwire citation metadata groups institutions under the preceding author.
            self.records[-1]['affiliations'].append(value)

def publisher_url(paper):
    url = paper.get('url', '')
    host = (urlsplit(url).hostname or '').lower()
    if host in ('biorxiv.org', 'www.biorxiv.org') and '/content/' in url:
        return url  # Keep v1/v2/v3; DOI metadata alone is not version-specific.
    doi = paper.get('doi') or (url.split('doi.org/', 1)[1] if 'doi.org/' in url else '')
    if doi.startswith('10.1186/'):
        return 'https://link.springer.com/article/' + doi
    if doi.startswith('10.1038/'):
        return 'https://www.nature.com/articles/' + doi.split('/', 1)[1]
    candidate = paper.get('publisher_url', '')
    if candidate.startswith('http://'):candidate = 'https://' + candidate[len('http://'):]
    return candidate if candidate and _safe(candidate) and 'doi.org' not in (urlsplit(candidate).hostname or '') else ''

def parse_authors(text, paper, source_url):
    parser = CitationAuthors(); parser.feed(text)
    expected = paper.get('doi') or ''
    normalize = lambda s: re.sub(r'v\d+$', '', s.strip().removeprefix('https://doi.org/')).lower()
    if expected and parser.doi and normalize(expected) != normalize(parser.doi):
        raise ValueError('publisher_doi_mismatch')
    doi_matches = bool(expected and parser.doi and normalize(expected) == normalize(parser.doi))
    if not doi_matches and (not parser.title or SequenceMatcher(None, _norm_title(parser.title), _norm_title(paper.get('title', ''))).ratio() < .94):
        raise ValueError('publisher_title_mismatch')
    if not parser.records: raise ValueError('publisher_authors_missing')
    authors = [r['name'] for r in parser.records]
    # An all-authors-then-all-institutions block is ambiguous; do not guess its links.
    records = parser.records
    if len(records) > 1 and all(not r['affiliations'] for r in records[:-1]):
        records = [dict(r, affiliations=[]) for r in records]
    result = dict(paper, authors=authors, affiliations=[], author_affiliations={})
    result.update(from_author_records(records, result))
    result.update(author_metadata_schema=SCHEMA, author_metadata_url=source_url,
                  author_metadata_version_url=paper.get('url', ''))
    return result

def enrich_publisher(paper):
    url = publisher_url(paper)
    if not url: return paper
    try:
        text, final = _Budget(max_requests=6, timeout_seconds=45, request_timeout=25).fetch(url)
        result = parse_authors(text, paper, final)
        result.pop('author_metadata_error', None)
        return result
    except HTTPError as exc:
        return dict(paper, author_metadata_error='HTTP_'+str(exc.code))
    except Exception as exc:
        return dict(paper, author_metadata_error=type(exc).__name__)


def enrich_europepmc(paper):
    """Public DOI-exact fallback; only explicit author-nested units are accepted."""
    doi = paper.get('doi') or (paper.get('url','').split('doi.org/',1)[1] if 'doi.org/' in paper.get('url','') else '')
    if not doi or all(paper.get('author_affiliations',{}).get(name) for name in paper.get('authors',[])) and paper.get('authors'):
        return paper
    url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urlencode({'query':'DOI:"'+doi+'"','format':'json','resultType':'core','pageSize':3})
    try:
        text, final = _Budget(max_requests=2, timeout_seconds=35, request_timeout=20).fetch(url)
        items = json.loads(text).get('resultList',{}).get('result',[])
        matches = [item for item in items if item.get('doi','').casefold() == doi.casefold()]
        if len(matches) != 1: return paper
        records = []
        for author in matches[0].get('authorList',{}).get('author',[]):
            name = ' '.join(filter(None,[author.get('firstName'),author.get('lastName')])) or author.get('fullName','')
            units = [entry['affiliation'] for entry in author.get('authorAffiliationDetailsList',{}).get('authorAffiliation',[]) if entry.get('affiliation')]
            records.append({'name':name,'affiliations':units})
        result = dict(paper)
        if not result.get('authors'): result['authors'] = [r['name'] for r in records if r['name']]
        found = from_author_records(records, result)
        if not found['author_affiliations']:return paper
        from author_affiliations import merge_associations
        result.update(merge_associations(result, dict(result, **found)))
        result['affiliation_fallback_url'] = final
        return result
    except HTTPError as exc:
        return dict(paper, affiliation_fallback_error='HTTP_'+str(exc.code))
    except Exception as exc:
        return dict(paper, affiliation_fallback_error=type(exc).__name__)
