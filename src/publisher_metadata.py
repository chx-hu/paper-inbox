"""Version-aware public author metadata; preserve source-specific provenance."""
from html.parser import HTMLParser
from difflib import SequenceMatcher
import re
from urllib.parse import urlsplit
from paper_metadata import _Budget, _norm_title
from author_affiliations import from_author_records

SCHEMA = 1

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
    if doi.startswith('10.1038/'):
        return 'https://www.nature.com/articles/' + doi.split('/', 1)[1]
    return ''

def parse_authors(text, paper, source_url):
    parser = CitationAuthors(); parser.feed(text)
    if not parser.title or SequenceMatcher(None, _norm_title(parser.title), _norm_title(paper.get('title', ''))).ratio() < .94:
        raise ValueError('publisher_title_mismatch')
    expected = paper.get('doi') or ''
    normalize = lambda s: re.sub(r'v\d+$', '', s.strip().removeprefix('https://doi.org/')).lower()
    if expected and parser.doi and normalize(expected) != normalize(parser.doi):
        raise ValueError('publisher_doi_mismatch')
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
        text, final = _Budget().fetch(url)
        result = parse_authors(text, paper, final)
        result.pop('author_metadata_error', None)
        return result
    except Exception as exc:
        return dict(paper, author_metadata_error=type(exc).__name__)
