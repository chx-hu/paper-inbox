"""Offline checks for evidence-scoped author/institution associations."""
import unittest
from author_affiliations import from_arxiv_html, from_crossref, from_author_records, normalize_associations, merge_associations


class AuthorAffiliationTests(unittest.TestCase):
    def test_numbered_authors_link_multiple_units_without_contribution_symbols(self):
        paper = {'authors': ['Li, Mingrui', 'Li, Minzhang', 'Yu, Jingyi'],
                 'affiliations': ['ShanghaiTech University', 'Cellverse Co., Ltd.']}
        html = '''<div class="ltx_authors"><span class="ltx_personname">
Mingrui Li<sup><i>1</i></sup> Minzhang Li<sup>1,2†</sup> Jingyi Yu<sup>1∗</sup>
<br><sup>1</sup>ShanghaiTech University <sup>2</sup>Cellverse Co., Ltd.
<br><sup>†</sup>Equal contribution<br><sup>*</sup>Correspondence: email@example.org
</span></div>'''
        result = from_arxiv_html(html, paper)
        self.assertEqual(result['author_affiliations'],
                         {'Li, Mingrui': [1], 'Li, Minzhang': [1, 2], 'Yu, Jingyi': [1]})
        self.assertEqual(result['affiliations'], paper['affiliations'])

    def test_scope_is_single_author_and_not_order(self):
        paper = {'authors': ['Bent, Oliver', 'Quinn, Eoin'],
                 'affiliations': ['InstaDeep', 'London, UK', 'Paris, France']}
        html = '''<div class="ltx_authors"><span class="ltx_creator ltx_role_author">
<span class="ltx_personname">Eoin Quinn</span><span class="ltx_contact ltx_role_affiliation">
<span class="ltx_contact_name">Affiliation: </span>InstaDeep</span>
<span class="ltx_contact ltx_role_affiliation">London, UK</span></span>
<span class="ltx_creator ltx_role_author"><span class="ltx_personname">Oliver Bent</span>
<span class="ltx_contact ltx_role_affiliation">InstaDeep</span>
<span class="ltx_contact ltx_role_affiliation">Paris, France</span></span></div>'''
        self.assertEqual(from_arxiv_html(html, paper)['author_affiliations'],
                         {'Quinn, Eoin': [1, 2], 'Bent, Oliver': [1, 3]})

    def test_frontmatter_paragraph_numbering(self):
        paper = {'authors': ['Zhang, Lisheng', 'Li, Qingsong'],
                 'affiliations': ['Peking University', 'Yuanpei College']}
        html = '''<article><p>Lisheng Zhang<sup>1,†</sup>, Qingsong Li<sup>2,†</sup></p>
<p><sup>1</sup>Peking University<br><sup>2</sup>Yuanpei College
<br><sup>†</sup>Equal contribution</p><section><p>Lisheng Zhang<sup>2</sup></p></section></article>'''
        self.assertEqual(from_arxiv_html(html, paper)['author_affiliations'],
                         {'Zhang, Lisheng': [1], 'Li, Qingsong': [2]})

    def test_unmarked_single_unit_does_not_imply_all_authors(self):
        paper = {'authors': ['Li, Mingrui', 'Li, Minzhang'], 'affiliations': ['University A']}
        html = '''<div class="ltx_authors"><span class="ltx_personname">Mingrui Li, Minzhang Li</span>
<span class="ltx_affiliation">University A</span></div>'''
        self.assertEqual(from_arxiv_html(html, paper)['author_affiliations'], {})

    def test_typo_and_ambiguous_identity_are_not_matched(self):
        paper = {'authors': ['Chuang, Kangway'], 'affiliations': ['Genentech']}
        html = '''<span class="ltx_creator ltx_role_author"><span class="ltx_personname">Kangway Chauang</span>
<span class="ltx_contact ltx_role_affiliation">Genentech</span></span>'''
        self.assertEqual(from_arxiv_html(html, paper)['author_affiliations'], {})
        duplicate = {'authors': ['John Smith', 'Smith, John'], 'affiliations': []}
        self.assertEqual(from_author_records([{'name': 'John Smith', 'affiliations': ['A']}], duplicate)
                         ['author_affiliations'], {})

    def test_conflicting_numeric_label_is_not_mapped(self):
        paper = {'authors': ['John Smith'], 'affiliations': ['University A', 'University B']}
        html = '''<div class="ltx_authors">John Smith<sup>1</sup>
<br><sup>1</sup>University A<br><sup>1</sup>University B</div>'''
        self.assertEqual(from_arxiv_html(html, paper)['author_affiliations'], {})

    def test_crossref_compiles_fresh_referenced_units_and_indices(self):
        paper = {'authors': ['Smith, John', 'Jane Jones'], 'affiliations': ['Institution Z']}
        message = {'author': [
            {'given': 'Jane', 'family': 'Jones', 'affiliation': [{'name': 'Institution B'}]},
            {'given': 'John', 'family': 'Smith', 'affiliation': [{'name': 'Institution Z'}, {'name': 'Institution B'}]},
        ]}
        result = from_crossref(message, paper)
        self.assertEqual(result['affiliations'], ['Institution B', 'Institution Z'])
        self.assertEqual(result['author_affiliations'], {'Jane Jones': [1], 'Smith, John': [2, 1]})
        self.assertEqual(paper['affiliations'], ['Institution Z'])

    def test_prior_flat_variants_cannot_become_orphan_numbered_units(self):
        paper = {'authors': ['Ana Chen'], 'affiliations': ['University of Toronto', 'University of Toronto;']}
        result = from_author_records([{'name': 'Ana Chen', 'affiliations':
                                      ['Department of Chemistry, University of Toronto, Canada']}], paper)
        self.assertEqual(result, {'affiliations': ['Department of Chemistry, University of Toronto, Canada'],
                                  'author_affiliations': {'Ana Chen': [1]}})
        self.assertEqual({i for values in result['author_affiliations'].values() for i in values},
                         set(range(1, len(result['affiliations']) + 1)))

    def test_html_returns_source_unit_text_and_drops_unreferenced_flat_unit(self):
        paper = {'authors': ['Ana Chen'], 'affiliations': ['Orphan unit', 'Department of Chemistry University A']}
        html = '''<span class="ltx_creator ltx_role_author"><span class="ltx_personname">Ana Chen</span>
<span class="ltx_contact ltx_role_affiliation">Department of Chemistry, University A</span></span>'''
        self.assertEqual(from_arxiv_html(html, paper),
                         {'affiliations': ['Department of Chemistry, University A'],
                          'author_affiliations': {'Ana Chen': [1]}})

    def test_normalize_existing_indices_compacts_only_known_valid_links(self):
        paper = {'authors': ['Ana Chen', 'Bob Li'],
                 'affiliations': ['Orphan A', 'Institution B', 'Orphan C', 'Institution D'],
                 'author_affiliations': {'Ana Chen': [4, 2, 4, 20, True], 'Bob Li': [2], 'Unknown': [1]}}
        self.assertEqual(normalize_associations(paper),
                         {'affiliations': ['Institution B', 'Institution D'],
                          'author_affiliations': {'Ana Chen': [1, 2], 'Bob Li': [1]}})
        unknown = {'authors': ['Ana Chen'], 'affiliations': ['Unassociated institution'],
                   'author_affiliations': {'Unknown': [1]}}
        self.assertEqual(normalize_associations(unknown),
                         {'affiliations': ['Unassociated institution'], 'author_affiliations': {}})

    def test_source_merge_rebuilds_all_indices_when_units_change(self):
        previous = {'authors': ['Ana Chen', 'Bob Li'], 'affiliations': ['Old A', 'Orphan', 'Institution B'],
                    'author_affiliations': {'Ana Chen': [1], 'Bob Li': [3]}}
        incoming = {'authors': ['Ana Chen', 'Bob Li'], 'affiliations': ['New A'],
                    'author_affiliations': {'Ana Chen': [1]}}
        self.assertEqual(merge_associations(previous, incoming),
                         {'affiliations': ['Institution B', 'New A'],
                          'author_affiliations': {'Bob Li': [1], 'Ana Chen': [2]}})
        empty = {'authors': ['Ana Chen', 'Bob Li'], 'affiliations': ['Unlinked unit'],
                 'author_affiliations': {}}
        preserved = merge_associations(previous, empty)
        self.assertEqual(preserved['affiliations'], ['Old A', 'Institution B'])
        self.assertEqual(preserved['author_affiliations'], {'Ana Chen': [1], 'Bob Li': [2]})

    def test_script_and_unscoped_metadata_do_not_create_links(self):
        paper = {'authors': ['John Smith'], 'affiliations': ['University A']}
        html = '''<script>John Smith<sup>1</sup>University A</script>
<meta name="citation_author" content="John Smith"><meta name="citation_author_institution" content="University A">'''
        self.assertEqual(from_arxiv_html(html, paper)['author_affiliations'], {})


if __name__ == '__main__':
    unittest.main()
