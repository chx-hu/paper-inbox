import unittest
from unittest.mock import patch
from publisher_metadata import parse_authors, enrich_publisher, publisher_url, enrich_europepmc

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
    def test_bmc_uses_verified_springer_article_route(self):
        for doi in ('10.1186/s13059-026-04333-2','10.1186/s13073-026-01826-4'):
            self.assertEqual(publisher_url({'url':'https://doi.org/'+doi}), 'https://link.springer.com/article/'+doi)
    def test_doi_identity_handles_revised_titles_without_relaxing_wrong_dois(self):
        text='<meta name="citation_title" content="Revised title"><meta name="citation_doi" content="10.1101/123"><meta name="citation_author" content="Jane Doe"><meta name="citation_author_institution" content="Lab">'
        self.assertEqual(parse_authors(text,{'title':'Old title','doi':'10.1101/123'},'https://www.biorxiv.org')['authors'],['Jane Doe'])
        with self.assertRaises(ValueError):parse_authors(text,{'title':'Revised title','doi':'10.1101/456'},'https://www.biorxiv.org')
    def test_europepmc_exact_doi_and_author_nested_units(self):
        import json
        p={'doi':'10.1016/j.test','authors':['Jane Doe'],'affiliations':[]}
        response={'resultList':{'result':[{'doi':'10.1016/j.test','authorList':{'author':[{'firstName':'Jane','lastName':'Doe','authorAffiliationDetailsList':{'authorAffiliation':[{'affiliation':'University A'}]}}]}}]}}
        with patch('publisher_metadata._Budget.fetch',return_value=(json.dumps(response),'https://www.ebi.ac.uk/europepmc')):
            q=enrich_europepmc(p)
        self.assertEqual(q['author_affiliations'],{'Jane Doe':[1]})
        self.assertEqual(q['affiliations'],['University A'])
        response['resultList']['result'][0]['doi']='10.1016/j.other'
        with patch('publisher_metadata._Budget.fetch',return_value=(json.dumps(response),'https://www.ebi.ac.uk/europepmc')):
            self.assertEqual(enrich_europepmc(p),p)
    def test_wrong_identity_rejected(self):
        with self.assertRaises(ValueError):parse_authors('<meta name="citation_title" content="Other work">',{'title':'A study'},'https://www.nature.com')
    def test_network_failure_keeps_existing_metadata(self):
        p={'title':'Study','url':'https://www.biorxiv.org/content/10.1101/123v3','authors':['A'],'affiliations':['Lab']}
        with patch('publisher_metadata._Budget.fetch',side_effect=TimeoutError):out=enrich_publisher(p)
        self.assertEqual(out['authors'],['A']);self.assertEqual(out['affiliations'],['Lab'])
        self.assertEqual(out['author_metadata_error'],'TimeoutError')
