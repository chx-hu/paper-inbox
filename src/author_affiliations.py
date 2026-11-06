"""Explicit author-to-institution associations, represented by 1-based indices."""
from html.parser import HTMLParser
import re
import unicodedata

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
EMAIL = re.compile(r'(?:\{[^{}]*\}\s*|[^\s<>@]+)@[^\s<>@]+')


def _clean(value):
    return re.sub(r'\s+', ' ', value).strip(' ,;\n\t')


def _key(value):
    value = unicodedata.normalize('NFKD', value).casefold()
    return ' '.join(re.findall(r'[^\W_]+', ''.join(c for c in value if not unicodedata.combining(c))))


def _name_key(value):
    return tuple(sorted(_key(value).split()))


def _display_name(source_name, authors):
    matches = [name for name in authors if _name_key(name) == _name_key(source_name)]
    return matches[0] if len(matches) == 1 else None


def from_author_records(records, paper):
    """Map records of {'name': str, 'affiliations': [str]} to displayed authors.

    Names must match a unique displayed author. No order-based or single-unit
    inference is used. Numbered units are compiled only from referenced source
    records. If no author can be mapped, original flat units stay unnumbered.
    """
    affiliations = []
    mapping = {}
    for record in records:
        name = _display_name(record.get('name', ''), paper.get('authors') or [])
        if not name:
            continue
        for value in record.get('affiliations', []):
            value = _clean(value)
            if not value:
                continue
            matches = [i for i, existing in enumerate(affiliations) if _key(existing) == _key(value)]
            if not matches:
                affiliations.append(value)
                matches = [len(affiliations) - 1]
            if len(matches) == 1:
                index = matches[0] + 1
                if index not in mapping.setdefault(name, []):
                    mapping[name].append(index)
    if not mapping:
        affiliations = list(paper.get('affiliations') or [])
    return {'affiliations': affiliations, 'author_affiliations': mapping}


def normalize_associations(paper):
    """Compact validated existing links without adding author/unit associations."""
    original = list(paper.get('affiliations') or [])
    authors = paper.get('authors') or []
    source = paper.get('author_affiliations') or {}
    valid = {}
    for name in authors:
        indices = source.get(name, [])
        if not isinstance(indices, list):
            continue
        values = [index for index in indices if type(index) is int and 1 <= index <= len(original)]
        if values:
            valid[name] = values
    used = {index for indices in valid.values() for index in indices}
    units, old_to_new = [], {}
    for index, unit in enumerate(original, 1):
        if index not in used or not isinstance(unit, str) or not _clean(unit):
            continue
        value = _clean(unit)
        matches = [i for i, existing in enumerate(units) if _key(existing) == _key(value)]
        if not matches:
            units.append(value)
            matches = [len(units) - 1]
        old_to_new[index] = matches[0] + 1
    mapping = {}
    for name, indices in valid.items():
        translated = sorted({old_to_new[index] for index in indices if index in old_to_new})
        if translated:
            mapping[name] = translated
    return {'affiliations': units if mapping else original, 'author_affiliations': mapping}


def merge_associations(previous, incoming):
    """Rebuild indices across sources, preferring incoming links for each author."""
    authors = incoming.get('authors') or previous.get('authors') or []
    newest = normalize_associations(dict(incoming, authors=authors))
    prior = normalize_associations(dict(previous, authors=authors))
    records = []
    for result in (prior, newest):
        for name, indices in result['author_affiliations'].items():
            if result is prior and name in newest['author_affiliations']:
                continue
            records.append({'name': name, 'affiliations': [result['affiliations'][index - 1]
                            for index in indices]})
    fallback = incoming.get('affiliations') or previous.get('affiliations') or []
    return from_author_records(records, {'authors': authors, 'affiliations': fallback})


def from_crossref(message, paper):
    """Use only Crossref's affiliation arrays nested inside each author record."""
    records = []
    for author in message.get('author', []):
        name = author.get('name') or ' '.join(part for part in
                (author.get('given', ''), author.get('family', '')) if part)
        records.append({'name': name, 'affiliations': [item['name'] for item in
                        author.get('affiliation', []) if item.get('name')]})
    return from_author_records(records, paper)


class _Node:
    def __init__(self, tag='', attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.classes = set(self.attrs.get('class', '').split())
        self.children = []


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        if len(self.nodes) >= 150000 or len(self.stack) > 200:
            raise ValueError('author_metadata_html_too_complex')
        node = _Node(tag, attrs)
        self.nodes.append(node)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _descendants(node):
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _descendants(child)


def _excluded(node):
    return (node.tag in ('script', 'style') or
            node.attrs.get('href', '').casefold().startswith('mailto:') or
            bool(node.classes & {'ltx_contact_name', 'ltx_role_email', 'ltx_note', 'ltx_note_mark', 'ltx_note_outer', 'ltx_note_content'}))


def _events(node):
    if _excluded(node):
        return
    if node.tag == 'sup':
        yield ('sup', _text(node))
        return
    if node.tag == 'br':
        yield ('break', '')
        return
    for child in node.children:
        if isinstance(child, str):
            yield ('text', child)
        else:
            yield from _events(child)


def _text(node):
    return _clean(EMAIL.sub('', ''.join(value for kind, value in _events_without_sup(node))))


def _events_without_sup(node):
    if _excluded(node):
        return
    for child in node.children:
        if isinstance(child, str):
            yield ('text', child)
        elif child.tag != 'sup':
            if child.tag == 'br':
                yield ('text', ' ')
            else:
                yield from _events_without_sup(child)


def _numbers(value):
    # Only numeric affiliation labels survive. Contribution/contact symbols have no index.
    if not re.fullmatch(r'[\d,\s*†‡∗§¶]+', value):
        return []
    return list(dict.fromkeys(re.findall(r'\d+', value)))


def _segments(node):
    """Return text separated by explicit superscript and line-break boundaries."""
    events = list(_events(node))
    segments, text = [], []
    preceding = None
    for kind, value in events:
        if kind == 'text':
            text.append(value)
        else:
            segments.append((preceding, _clean(''.join(text)), kind, value))
            preceding = _numbers(value) if kind == 'sup' else None
            text = []
    segments.append((preceding, _clean(''.join(text)), 'end', ''))
    return segments


def from_arxiv_html(text, paper):
    """Read scoped author units and explicit numeric cross-references from HTML.

    Flat unit strings come from the caller's independently verified extraction.
    A numeric label is accepted only when its following text matches one of
    those units. Names match uniquely against the displayed author list.
    """
    tree = _Tree()
    tree.feed(text)
    affiliations = list(paper.get('affiliations') or [])
    authors = paper.get('authors') or []
    records = []
    contexts = [node for node in tree.nodes if 'ltx_authors' in node.classes]
    # Some sources put explicitly numbered front matter in ordinary paragraphs.
    # Accept only the paragraph immediately after a verified author paragraph.
    previous_authors = False
    for node in tree.nodes:
        if node.tag == 'section' or 'ltx_abstract' in node.classes:
            break
        if node.tag != 'p':
            continue
        segments = _segments(node)
        recognized = [bool(_display_name(value, authors)) for _, value, kind, _ in segments
                      if value and kind == 'sup']
        if previous_authors:
            contexts.append(node)
        previous_authors = bool(recognized) and all(recognized)
        if previous_authors:
            contexts.append(node)

    label_units = {}
    author_labels = {}
    for context in contexts:
        for preceding, value, kind, marker in _segments(context):
            if preceding and value:
                matches = [item for item in affiliations if _key(item) == _key(value)]
                if len(matches) == 1:
                    for label in preceding:
                        label_units.setdefault(label, set()).add(value)
            if kind == 'sup' and value:
                name = _display_name(value, authors)
                if name:
                    author_labels.setdefault(name, set()).update(_numbers(marker))
    for name, labels in author_labels.items():
        units = []
        for label in sorted(labels, key=int):
            matches = label_units.get(label, set())
            if len(matches) == 1:
                units.extend(matches)
        records.append({'name': name, 'affiliations': units})

    for creator in (node for node in tree.nodes if 'ltx_role_author' in node.classes):
        nodes = list(_descendants(creator))
        names = [node for node in nodes if 'ltx_personname' in node.classes]
        if len(names) != 1:
            continue
        name = _display_name(_text(names[0]), authors)
        if not name:
            continue
        units = []
        for node in nodes:
            if ('ltx_affiliation' in node.classes or
                    {'ltx_contact', 'ltx_role_affiliation'}.issubset(node.classes)):
                value = _text(node)
                matches = [item for item in affiliations if _key(item) == _key(value)]
                if len(matches) == 1:
                    units.append(value)
        records.append({'name': name, 'affiliations': units})
    return from_author_records(records, paper)


def apply_reviewed_associations(paper):
    """Apply narrowly scoped, visually reviewed first-page corrections.

    An explicit newer version or a changed title/author roster invalidates the
    correction. Never generalize a spelling discrepancy to other papers.
    """
    import json
    from pathlib import Path
    from urllib.parse import urlsplit
    aid = urlsplit(paper.get('url', '')).path.rsplit('/', 1)[-1]
    match = re.fullmatch(r'(\d{4}\.\d{4,5})(?:v(\d+))?', aid)
    if not match or match.group(2) not in (None, '1'):
        return paper
    try:
        entry = json.loads(Path(__file__).with_name('reviewed_author_affiliations.json').read_text()).get(match.group(1))
    except (OSError, ValueError):
        return paper
    if not entry or paper.get('title') != entry['title'] or paper.get('authors') != entry['authors']:
        return paper
    result = dict(paper, affiliations=entry['affiliations'], author_affiliations=entry['author_affiliations'])
    result['author_affiliation_evidence'] = {k: entry[k] for k in ('source_url', 'page', 'pdf_sha256', 'evidence')}
    return result
