import unittest
from unittest.mock import patch
from publisher_metadata import parse_authors, enrich_publisher, publisher_url

class PublisherTests(unittest.TestCase):
    def test_explicit_groups_replace_stale_version_and_map_multiple_units(self):
        p={'title':'A study','doi':'10.1101/123','url':'https://www.biorxiv.org/content/10.1101/123v3','authors':['Old']}
        text='<meta name="citation_title" content="A study"><meta name="citation_doi" content="10.1101/123"><meta name="citation_author" content="A One"><meta name="citation_author_institution" content="Lab 1"><meta name="citation_author_institution" content="Lab 2"><meta name="citation_author" content="B Two"><meta name="citation_author_institution" content="Lab 2">'
        out=parse_authors(text,p,p['url'])
        self.assertEqual(out['authors'],['A One','B Two'])
        self.assertEqual(out['author_affiliations'],{'A One':[1,2],'B Two':[2]})
        self.assertEqual(publisher_url(p),p['url'])
    def test_ambiguous_flat_institutions_not_assigned_to_last_author(self):
        text='<meta name="citation_title" content="A study"><meta name="citation_author" content="A"><meta name="citation_author" content="B"><meta name="citation_author_institution" content="Lab">'
        self.assertEqual(parse_authors(text,{'title':'A study'},'https://www.nature.com')['author_affiliations'],{})
    def test_wrong_identity_rejected(self):
        with self.assertRaises(ValueError):parse_authors('<meta name="citation_title" content="Other work">',{'title':'A study'},'https://www.nature.com')
    def test_network_failure_keeps_existing_metadata(self):
        p={'title':'Study','url':'https://www.biorxiv.org/content/10.1101/123v3','authors':['A'],'affiliations':['Lab']}
        with patch('publisher_metadata._Budget.fetch',side_effect=TimeoutError):out=enrich_publisher(p)
        self.assertEqual(out['authors'],['A']);self.assertEqual(out['affiliations'],['Lab'])
        self.assertEqual(out['author_metadata_error'],'TimeoutError')
