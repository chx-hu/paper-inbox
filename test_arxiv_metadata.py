"""Offline fixtures for official arXiv metadata enrichment."""
from pathlib import Path
from io import BytesIO
from urllib.error import HTTPError
import tempfile
import unittest
from unittest.mock import patch

import arxiv_metadata as metadata

ABS = '''<html><head>
<meta name="citation_arxiv_id" content="2610.41322">
<meta name="citation_author" content="Lee, Jian">
<meta name="citation_author" content="Cho, Changyun">
<meta name="citation_author" content="Kim, Sun">
<meta name="citation_date" content="2026/10/30">
</head></html>'''
ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"
xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
<id>http://arxiv.org/abs/2610.41322v1</id>
<published>2026-10-30T00:00:00Z</published>
<author><name>Jian Lee</name><arxiv:affiliation>AIGENDRUG Co., Ltd.</arxiv:affiliation></author>
<author><name>Sun Kim</name><arxiv:affiliation>Seoul National University</arxiv:affiliation></author>
</entry></feed>'''
HTML = '''<div class="ltx_authors"><span class="ltx_personname">Jian Lee</span>
<span class="ltx_contact ltx_role_affiliation"><span class="ltx_contact_name">Affiliation: </span>
<span>AIGENDRUG <b>Co., Ltd.</b>, Seoul</span><br>South Korea
<a href="mailto:jian@example.org">jian@example.org</a></span>
<span class="ltx_affiliation"><sup>2</sup>Seoul <em>National</em> University
<span class="ltx_contact ltx_role_email">sun@example.org</span></span>
<span class="ltx_affiliation">Seoul <em>National</em> University</span>
</div><p>Elsewhere affiliation speculation and other@example.org</p>
<script>never_run_this()</script>'''


class ArxivMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache_patch = patch.object(metadata, 'CACHE_DIR', Path(self.temp.name))
        self.cache_patch.start()
        self.paper = {'url': 'https://arxiv.org/abs/2610.41322', 'title': 'Original title'}

    def tearDown(self):
        self.cache_patch.stop()
        self.temp.cleanup()

    def test_exact_id_and_url_validation(self):
        for url, identifier in [
            ('https://arxiv.org/abs/2610.41322', '2610.41322'),
            ('https://arxiv.org/pdf/2610.41322v2.pdf', '2610.41322v2'),
            ('http://arxiv.org/html/hep-th/9901001v1', 'hep-th/9901001v1'),
        ]:
            self.assertEqual(metadata.arxiv_id_from_url(url), identifier)
        for url in ['https://arxiv.org.evil.test/abs/2610.41322',
                    'https://user@arxiv.org/abs/2610.41322',
                    'https://arxiv.org/abs/2610.41322/extra',
                    'https://arxiv.org/abs/2610.41322?query=other',
                    'https://arxiv.org/abs/2610.41322#fragment',
                    'https://arxiv.org/abs/2610.41322v0',
                    'https://arxiv.org/abs/../../file',
                    'https://arxiv.org/abs/2610.41322.pdf']:
            self.assertEqual(metadata.arxiv_id_from_url(url), '', url)

    def test_abs_authors_and_date(self):
        result = metadata._parse_abs(ABS, '2610.41322v1')
        self.assertEqual(result['authors'], ['Lee, Jian', 'Cho, Changyun', 'Kim, Sun'])
        self.assertEqual(result['published'], '2026-10-30')
        with self.assertRaises(ValueError):
            metadata._parse_abs(ABS, '2610.12345')

    def test_nested_affiliations_exclude_names_emails_and_labels(self):
        self.assertEqual(metadata._parse_affiliations(HTML), [
            'AIGENDRUG Co., Ltd., Seoul South Korea', 'Seoul National University'])

    def test_grouped_email_and_authors_inside_affiliation_are_excluded(self):
        html = '''<div class="ltx_affiliation"><span class="ltx_personname">Fiorella Ruggiu</span>
<span class="ltx_personname">Imran S. Haque</span></div>
<div class="ltx_affiliation">Genentech , {lisanza.sidney, joren.taylor}@gene.com</div>'''
        self.assertEqual(metadata._parse_affiliations(html), ['Genentech'])

    def test_mislabelled_author_list_is_rejected_using_citation_authors(self):
        html = '''<div class="ltx_creator ltx_role_author">
<span class="ltx_contact ltx_role_affiliation"><b>Fiorella Ruggiu</b> Imran S. Haque</span>
<span class="ltx_contact ltx_role_affiliation">Kimia Therapeutics, Berkeley, CA 94710</span></div>'''
        self.assertEqual(metadata._parse_affiliations(html, ['Ruggiu, Fiorella', 'Haque, Imran S.']),
                         ['Kimia Therapeutics, Berkeley, CA 94710'])

    def test_numbered_affiliation_line_inside_personname(self):
        html = '''<span class="ltx_personname">Mingrui Li<sup>1</sup> Minzhang Li<sup>1,2</sup>
<br><sup><i>1</i></sup>ShanghaiTech University <sup>2</sup>Cellverse Co., Ltd.
<br><sup>*</sup>Corresponding authors: somebody@example.org</span>'''
        self.assertEqual(metadata._parse_affiliations(html),
                         ['ShanghaiTech University', 'Cellverse Co., Ltd.'])

    def test_numbered_frontmatter_requires_matching_author_line(self):
        html = '''<article class="ltx_document"><p>Lisheng Zhang<sup>1</sup>, Qingsong Li<sup>2</sup></p>
<p><sup>1</sup>Peking University<br><sup>2</sup>Yuanpei College, Peking University
<br><sup>*</sup>Correspondence: somebody@example.org</p>
<section><p><sup>3</sup>Unrelated body text</p></section></article>'''
        self.assertEqual(metadata._parse_affiliations(html, ['Zhang, Lisheng', 'Li, Qingsong']),
                         ['Peking University', 'Yuanpei College, Peking University'])
        self.assertEqual(metadata._parse_affiliations(html, ['Different, Author']), [])

    def test_atom_author_namespace_affiliations(self):
        result = metadata._parse_atom(ATOM, '2610.41322')
        self.assertEqual(result['authors'], ['Jian Lee', 'Sun Kim'])
        self.assertEqual(result['affiliations'], ['AIGENDRUG Co., Ltd.', 'Seoul National University'])
        self.assertEqual(result['author_affiliations'], {'Jian Lee': [1], 'Sun Kim': [2]})
        with self.assertRaises(ValueError):
            metadata._parse_atom(ATOM, '2610.41322v2')

    def test_partial_failure_preserves_original_fields_and_caches(self):
        paper = dict(self.paper, affiliations=['Previously verified institution'], abstract='Original abstract')
        with patch.object(metadata._Fetcher, 'fetch', side_effect=[ABS, OSError('API offline'), OSError('HTML absent')]) as fetch:
            result = metadata.enrich_arxiv(paper)
            self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result['affiliations'], paper['affiliations'])
        self.assertEqual(result['abstract'], 'Original abstract')
        self.assertEqual(result['authors'], ['Lee, Jian', 'Cho, Changyun', 'Kim, Sun'])
        self.assertIn('失败', result['metadata_note'])
        self.assertEqual(result['metadata_sources'], ['https://arxiv.org/abs/2610.41322'])
        self.assertNotIn('authors', paper)
        with patch.object(metadata._Fetcher, 'fetch', side_effect=AssertionError('cached')):
            cached = metadata.enrich_arxiv(paper)
        self.assertEqual(cached, result)

    def test_negative_cache_retries_after_one_day(self):
        with patch.object(metadata._Fetcher, 'fetch', side_effect=OSError('offline')) as fetch:
            first = metadata.enrich_arxiv(self.paper)
            second = metadata.enrich_arxiv(self.paper)
            self.assertEqual(fetch.call_count, 3)
        self.assertNotIn('metadata_sources', first)
        self.assertEqual(first, second)
        with patch.object(metadata.time, 'time', return_value=metadata.time.time() + 86401), patch.object(metadata._Fetcher, 'fetch', side_effect=[ABS, '', ATOM]) as fetch:
            result = metadata.enrich_arxiv(self.paper)
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(result['affiliations'])

    def test_html_fallback_and_complete_cache(self):
        with patch.object(metadata._Fetcher, 'fetch', side_effect=[ABS, HTML]):
            result = metadata.enrich_arxiv(self.paper)
        self.assertEqual(len(result['affiliations']), 2)
        self.assertEqual(result['metadata_sources'], [
            'https://arxiv.org/abs/2610.41322', 'https://arxiv.org/html/2610.41322'])
        with patch.object(metadata._Fetcher, 'fetch', side_effect=AssertionError('cached')):
            self.assertEqual(metadata.enrich_arxiv(self.paper)['affiliations'], result['affiliations'])

    def test_enrichment_caches_explicit_mapping_with_displayed_author_name(self):
        html = '''<div class="ltx_authors"><span class="ltx_creator ltx_role_author">
<span class="ltx_personname">Jian Lee</span><span class="ltx_contact ltx_role_affiliation">
AIGENDRUG Co., Ltd.</span></span></div>'''
        with patch.object(metadata._Fetcher, 'fetch', side_effect=[ABS, html, OSError('API offline')]):
            result = metadata.enrich_arxiv(self.paper)
        self.assertEqual(result['author_affiliations'], {'Lee, Jian': [1]})
        self.assertEqual(result['affiliations'], ['AIGENDRUG Co., Ltd.'])
        with patch.object(metadata._Fetcher, 'fetch', side_effect=AssertionError('cached')):
            cached = metadata.enrich_arxiv(self.paper)
        self.assertEqual(cached['author_affiliations'], {'Lee, Jian': [1]})

    def test_non_arxiv_does_not_fetch(self):
        paper = {'url': 'https://example.org/abs/2610.41322', 'authors': ['A']}
        with patch.object(metadata._Fetcher, 'fetch', side_effect=AssertionError('not arxiv')):
            self.assertEqual(metadata.enrich_arxiv(paper), paper)

    def test_official_version_redirect_is_followed(self):
        fetcher = metadata._Fetcher()
        redirect = HTTPError('https://arxiv.org/html/2610.41322', 302, 'Found',
                             {'Location': '/html/2610.41322v1'}, BytesIO(b''))
        with patch.object(fetcher, '_fetch_once', side_effect=[redirect, HTML]) as fetch:
            self.assertEqual(fetcher.fetch('https://arxiv.org/html/2610.41322'), HTML)
        self.assertEqual(fetch.call_args_list[1].args[0], 'https://arxiv.org/html/2610.41322v1')

    def test_redirect_to_private_host_or_other_paper_is_rejected(self):
        for target in ['http://127.0.0.1/private', 'https://arxiv.org/html/2610.12345']:
            fetcher = metadata._Fetcher()
            redirect = HTTPError('https://arxiv.org/html/2610.41322', 302, 'Found',
                                 {'Location': target}, BytesIO(b''))
            with patch.object(fetcher, '_fetch_once', side_effect=redirect) as fetch:
                with self.assertRaises(ValueError):
                    fetcher.fetch('https://arxiv.org/html/2610.41322')
                self.assertEqual(fetch.call_count, 1)

    def test_corrupt_cache_is_retried(self):
        (Path(self.temp.name) / '2610.41322.json').write_text('[]')
        with patch.object(metadata._Fetcher, 'fetch', side_effect=[ABS, '', ATOM]):
            self.assertTrue(metadata.enrich_arxiv(self.paper)['authors'])


if __name__ == '__main__':
    unittest.main()
