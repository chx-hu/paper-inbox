import unittest
from arxiv_pdf_metadata import parse_affiliations
class PDFMetadataTests(unittest.TestCase):
 def test_explicit_frontmatter(self):
  text="Paper title\nRui Qiao    Lei Xin    Baozhen Shan\nrqiao@bioinfor.com\nBioinformatics Solutions Inc.\nAbstract\nOther University"
  self.assertEqual(parse_affiliations(text,['Qiao, Rui','Xin, Lei']),['Bioinformatics Solutions Inc.'])
 def test_no_institution_in_body_or_without_authors(self):
  self.assertEqual(parse_affiliations('Abstract\nExample University',['Alice Smith']),[])
  self.assertEqual(parse_affiliations('Example University\nAbstract',['Alice Smith']),[])
if __name__=='__main__':unittest.main()
