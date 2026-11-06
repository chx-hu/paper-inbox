import json
from pathlib import Path
import unittest
import author_affiliations as aa

class ReviewedAuthorsTests(unittest.TestCase):
    def test_reviewed_roster_is_complete_and_has_evidence(self):
        entries=json.loads(Path(aa.__file__).with_name('reviewed_author_affiliations.json').read_text())
        for aid, e in entries.items():
            p={'url':'https://arxiv.org/abs/'+aid, 'title':e['title'],'authors':e['authors']}
            q=aa.apply_reviewed_associations(p)
            self.assertEqual(set(q['authors']),set(q['author_affiliations']))
            self.assertEqual(q['author_affiliation_evidence']['page'],1)
            for indices in q['author_affiliations'].values():
                self.assertTrue(all(1<=i<=len(q['affiliations']) for i in indices))
            self.assertNotIn('author_affiliations',aa.apply_reviewed_associations(dict(p,url=p['url']+'v2')))
            self.assertNotIn('author_affiliations',aa.apply_reviewed_associations(dict(p,authors=['Other Person'])))
    def test_footnote_marker_does_not_change_author_identity(self):
        html='<div class="ltx_authors"><div class="ltx_role_author"><span class="ltx_personname">Jane Doe<span class="ltx_note">footnotemark: 1</span></span><span class="ltx_contact ltx_role_affiliation">University A</span></div></div>'
        q=aa.from_arxiv_html(html,{'authors':['Doe, Jane'],'affiliations':['University A']})
        self.assertEqual(q['author_affiliations'],{'Doe, Jane':[1]})
