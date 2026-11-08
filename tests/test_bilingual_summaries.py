import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import bilingual_summaries as summaries

ENGLISH = 'Problem: The study addresses protein stability.\n\nMethods: It uses a sequence model.\n\nResults: Prediction accuracy improves.'
CHINESE = '问题：研究蛋白质稳定性。\n\n方法：使用序列模型。\n\n结果：预测准确率提高。'

class BilingualSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def output(self, command, **kwargs):
        data = {'papers':[{'id':'p','summary_en':ENGLISH}]}
        Path(command[command.index('-o') + 1]).write_text(json.dumps(data))
    def test_translation_cache_and_source_changes(self):
        paper={'id':'p','title':'Study','summary':CHINESE}
        with patch('bilingual_summaries.subprocess.run', side_effect=self.output) as run:
            summaries.ensure_bilingual([paper], '2026-11-08', self.cache)
            self.assertEqual(paper['summary_zh'],CHINESE)
            self.assertEqual(paper['summary_en'],ENGLISH)
            self.assertEqual(paper['summary_en_source_hash'],summaries.source_hash(CHINESE))
            fresh={'id':'p','summary':CHINESE}
            summaries.ensure_bilingual([fresh], '2026-11-09', self.cache)
            self.assertEqual(fresh['summary_en'],ENGLISH)
            self.assertEqual(run.call_count,1)
            fresh['summary']=CHINESE+'\n'
            summaries.ensure_bilingual([fresh], '2026-11-09', self.cache)
            self.assertEqual(run.call_count,2)
    def test_mismatched_ids_do_not_publish_translation(self):
        def wrong(command, **kwargs):
            Path(command[command.index('-o')+1]).write_text(json.dumps({'papers':[{'id':'wrong','summary_en':ENGLISH}]}))
        paper={'id':'p','summary':CHINESE}
        with patch('bilingual_summaries.subprocess.run',side_effect=wrong):
            with self.assertRaises(ValueError):summaries.ensure_bilingual([paper],'2026-11-08',self.cache)
        self.assertNotIn('summary_en',paper)
        self.assertFalse((self.cache/'summary-translations.json').exists())
    def test_missing_abstract_is_translated_without_model(self):
        paper={'id':'p','summary':'原摘要未获取'}
        with patch('bilingual_summaries.subprocess.run', side_effect=AssertionError('no model needed')):
            summaries.ensure_bilingual([paper],'2026-11-08',self.cache)
        self.assertEqual(paper['summary_en'],'Original abstract unavailable.')
    def test_paragraphs_language_sentence_count_and_urls(self):
        summaries.validate_english(ENGLISH,CHINESE)
        for invalid in [ENGLISH.replace('Problem:','问题：'),ENGLISH+'\n\nExtra: New findings.',ENGLISH.replace('Prediction accuracy improves.','One. Two. Three. Four.')]:
            with self.assertRaises(ValueError):summaries.validate_english(invalid)
        with self.assertRaises(ValueError):summaries.validate_english(ENGLISH,CHINESE+' https://example.org/code')
        summaries.validate_english(ENGLISH+' https://example.org/code',CHINESE+' https://example.org/code')
