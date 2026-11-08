import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError

import summary_api as api
from bilingual_summaries import source_hash

ZH='问题：研究蛋白质结构预测。\n\n方法：训练一个模型。\n\n结果：预测得到改善。'
EN='Problem: The study examines protein structure prediction.\n\nMethods: A model was trained.\n\nResults: Predictions improved.'

class SummaryAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cache=Path(self.tmp.name)
        self.paper={'id':'paper-1','title':'A study','abstract':'A model predicts structures.'}
    def tearDown(self):self.tmp.cleanup()
    def output(self, items=None):
        return {'papers':items if items is not None else [{'id':'paper-1','summary_zh':ZH,'summary_en':EN}]}
    def response(self, payload):
        obj=Mock();obj.__enter__=Mock(return_value=obj);obj.__exit__=Mock(return_value=False)
        obj.read.return_value=json.dumps(payload).encode();return obj
    def test_existing_bilingual_pair_does_not_read_credentials_or_call_api(self):
        p=dict(self.paper,summary=ZH,summary_zh=ZH,summary_en=EN,
               summary_source_hash=source_hash(self.paper['abstract']),summary_en_source_hash=source_hash(ZH))
        with patch.object(api,'read_api_key',side_effect=AssertionError('credentials forbidden')),patch.object(api,'_request',side_effect=AssertionError('API forbidden')):
            api.ensure_summaries([p],'2026-11-08',self.cache)
        self.assertEqual(p['summary'],ZH)
    def test_generated_pair_is_cached_and_reused_without_key(self):
        p=dict(self.paper)
        with patch.object(api,'_request',return_value=self.output()) as request:
            api.ensure_summaries([p],'2026-11-08',self.cache,effort='low')
        request.assert_called_once();self.assertEqual(p['summary_en'],EN)
        self.assertEqual(p['summary_en_source_hash'],source_hash(ZH))
        again=dict(self.paper)
        with patch.object(api,'_request',side_effect=AssertionError('cached API forbidden')):
            api.ensure_summaries([again],'2026-11-09',self.cache,effort='low')
        self.assertEqual(again['summary'],ZH)
        with patch.object(api,'_request',return_value=self.output()) as changed:
            api.ensure_summaries([dict(self.paper)],'2026-11-09',self.cache,effort='medium')
        changed.assert_called_once()
    def test_mismatched_ids_are_not_saved_or_applied(self):
        p=dict(self.paper)
        bad=self.output([{'id':'other','summary_zh':ZH,'summary_en':EN}])
        with patch.object(api,'_request',return_value=bad),self.assertRaises(api.SummaryAPIError):
            api.ensure_summaries([p],'2026-11-08',self.cache)
        self.assertNotIn('summary',p);self.assertFalse((self.cache/'summary-api-cache.json').exists())
    def test_missing_abstract_needs_no_api(self):
        p=dict(self.paper,abstract='')
        with patch.object(api,'_request',side_effect=AssertionError('API forbidden')):
            api.ensure_summaries([p],'2026-11-08',self.cache)
        self.assertEqual(p['summary'],'原摘要未获取');self.assertEqual(p['summary_en'],'Original abstract unavailable.')
    def test_availability_never_reads_password(self):
        completed=subprocess.CompletedProcess([],0,stdout='metadata',stderr='')
        with patch.dict(os.environ,{},clear=True),patch.object(api.subprocess,'run',return_value=completed) as call:
            self.assertTrue(api.credentials_available())
        self.assertNotIn('-w',call.call_args.args[0])
    def test_environment_key_precedes_keychain_and_is_not_cached(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-credential-do-not-use'},clear=True),patch.object(api,'_keychain',side_effect=AssertionError('keychain forbidden')):
            self.assertEqual(api.read_api_key(),'test-credential-do-not-use')
        self.assertFalse(list(self.cache.iterdir()))
    def test_official_responses_payload_and_no_raw_response_cache(self):
        payload={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.output())}]}]}
        with patch.object(api,'read_api_key',return_value='test-credential-do-not-use'),patch.object(api._OPENER,'open',return_value=self.response(payload)) as opened:
            result=api._request([self.paper],'gpt-5.4-mini','medium')
        req=opened.call_args.args[0];body=json.loads(req.data)
        self.assertEqual(req.full_url,'https://api.openai.com/v1/responses')
        self.assertFalse(body['store']);self.assertEqual(body['reasoning'],{'effort':'medium'})
        self.assertTrue(body['text']['format']['strict']);self.assertEqual(body['text']['format']['type'],'json_schema')
        self.assertEqual(result,self.output());self.assertNotIn('test-credential',json.dumps(body))
    def test_401_is_not_retried_and_error_never_contains_response_secret(self):
        err=HTTPError(api.ENDPOINT,401,'unauthorized',{},io.BytesIO(b'test-private-response-value'))
        with patch.object(api,'read_api_key',return_value='test-credential-do-not-use'),patch.object(api._OPENER,'open',side_effect=err) as opened,patch.object(api.time,'sleep') as sleep:
            with self.assertRaises(api.SummaryAPIError) as caught:api._request([self.paper],'gpt-5.4-mini','none')
        self.assertNotIn('test-private',str(caught.exception));self.assertNotIn('test-credential',str(caught.exception))
        opened.assert_called_once();sleep.assert_not_called()
    def test_429_retry_delay_is_bounded(self):
        err=HTTPError(api.ENDPOINT,429,'limited',{'Retry-After':'500'},io.BytesIO(b'private'))
        with patch.object(api,'read_api_key',return_value='test-credential-do-not-use'),patch.object(api._OPENER,'open',side_effect=err) as opened,patch.object(api.time,'sleep') as sleep:
            with self.assertRaises(api.SummaryAPIError):api._request([self.paper],'gpt-5.4-mini','none')
        self.assertEqual(opened.call_count,3);self.assertEqual([x.args[0] for x in sleep.call_args_list],[5,5])
    def test_malformed_or_refused_output_has_no_raw_content(self):
        for payload in (["private-response"], {'status':'completed','output':[{'content':[{'type':'refusal','refusal':'private-response'}]}]}):
            with patch.object(api,'read_api_key',return_value='test-credential-do-not-use'),patch.object(api._OPENER,'open',return_value=self.response(payload)):
                with self.assertRaises(api.SummaryAPIError) as caught:api._request([self.paper],'gpt-5.4-mini','none')
            self.assertNotIn('private-response',str(caught.exception))
    def test_network_failure_is_sanitized(self):
        with patch.object(api,'read_api_key',return_value='test-credential-do-not-use'),patch.object(api._OPENER,'open',side_effect=URLError('private-details')):
            with self.assertRaises(api.SummaryAPIError) as caught:api._request([self.paper],'gpt-5.4-mini','none')
        self.assertNotIn('private-details',str(caught.exception))
    def test_model_specific_efforts_and_invalid_api_fields(self):
        api._validate_settings('gpt-6-astra','max');api._validate_settings('gpt-6-luna','none')
        with self.assertRaises(ValueError):api._validate_settings('gpt-5.4-mini','max')
        with self.assertRaises(ValueError):api._validate_settings('gpt-6.1-sol','none')
        with self.assertRaises(ValueError):api._validate_settings('https://other.example','low')
    def test_omitted_source_url_and_overlong_paragraph_rejected(self):
        with self.assertRaises(ValueError):api._validate_pair(ZH,EN,'Code https://example.org/code')
        with self.assertRaises(ValueError):api.validate_chinese(ZH.replace('训练一个模型。','一。二。三。四。'))
    def test_missing_key_is_actionable_without_password_details(self):
        with patch.dict(os.environ,{},clear=True),patch.object(api,'_keychain',return_value=''):
            with self.assertRaises(api.SummaryAPIError) as caught:api.read_api_key()
        self.assertIn('设置',str(caught.exception))
