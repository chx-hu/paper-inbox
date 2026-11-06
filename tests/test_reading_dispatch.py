import json
import sys
import app_settings
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reading_dispatch as reading
import server


class FakeClient:
    def __init__(self, completed=None, failure=None):
        self.calls = []
        self.completed = completed
        self.failure = failure

    def rpc(self, method, params):
        self.calls.append((method, params))
        if self.failure == method:
            raise ConnectionError('uncertain transport')
        if method == 'thread/start':
            return {'thread': {'id': 'thread-1'}}
        if method == 'turn/start':
            return {'turn': {'id': 'turn-1'}}
        if method == 'thread/read':
            return {'thread': {'turns': [self.completed] if self.completed else [
                {'id': 'turn-1', 'status': 'inProgress', 'items': []}]}}
        return {}


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        import zotero_bridge as zotero
        config = self.root / 'sources.json'
        config.write_text(json.dumps(dict(app_settings.DEFAULTS, retrieval_python=sys.executable)))
        self.patchers = [patch.object(app_settings, 'SOURCES_FILE', config), patch.object(zotero, 'probe', return_value={'available': True}), patch.object(reading, 'QUEUE_DIR', self.root / 'v4'),
                         patch.object(reading, 'LEGACY_QUEUE_DIR', self.root / 'v3'),
                         patch.object(reading, 'PROJECT_DIR', self.root),
                         patch.object(server, 'DB', self.root / 'inbox.sqlite'),
                         patch.object(reading, 'INBOX_DB', self.root / 'inbox.sqlite')]
        for patcher in self.patchers:
            patcher.start()
        server.init_db()
        self.paper = {'id': 'paper-1', 'title': 'A named paper', 'doi': '10.1/test', 'url': 'https://example.org/paper'}
        with server.connect() as conn:
            conn.execute('INSERT INTO papers(id,data,day,favorite) VALUES(?,?,?,1)', ('paper-1', json.dumps(self.paper), '2026-11-05'))

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def path(self):
        return reading.QUEUE_DIR / (reading.job_id(self.paper) + '.json')

    def receipt_data(self, **overrides):
        value = {'full_text_read': True, 'all_main_panels_read': True,
                 'coverage': [{'figure': 'Figure 1', 'panels': ['a', 'b'], 'complete': True}],
                 'method_name': 'TestMethod',
                 'method_evidence': {'quote': 'We introduce TestMethod.', 'locator': 'Introduction paragraph 2',
                                     'source_url': self.paper['url']}}
        value.update(overrides)
        return value

    def receipt(self, **overrides):
        return '完整的逐图中文报告\n```reading_receipt\n' + json.dumps(self.receipt_data(**overrides)) + '\n```'

    def write_receipt(self, **overrides):
        job = json.loads(self.path().read_text())
        receipt_path = Path(job['receipt_path'])
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(self.receipt_data(**overrides)), encoding='utf-8')

    def clean_report(self):
        return '正文与 Figure 1a、b 的中文精读报告。\n\n## Take-home message\n- 方法解决了论文提出的问题。'

    def test_settings_default_persist_validate(self):
        self.assertEqual(reading.get_settings(), {'model': 'gpt-6-astra', 'effort': 'high'})
        reading.save_settings({'model': 'gpt-6.1-sol', 'effort': 'medium'})
        self.assertEqual(reading.get_settings()['model'], 'gpt-6.1-sol')
        for invalid in ({'model': 'unknown', 'effort': 'high'}, {'model': 'gpt-6-astra', 'effort': 'none'}, {}):
            with self.assertRaises(ValueError):
                reading.save_settings(invalid)

    def test_upgrade_preserves_legacy_settings_until_new_selection(self):
        legacy_settings = {'model': 'gpt-6.1-sol', 'effort': 'medium'}
        legacy_path = reading.LEGACY_QUEUE_DIR / 'settings.json'
        reading._write(legacy_path, legacy_settings)
        legacy_bytes = legacy_path.read_bytes()
        self.assertEqual(reading.get_settings(), legacy_settings)
        reading.enqueue(self.paper)
        job = json.loads(self.path().read_text())
        self.assertEqual((job['model'], job['effort']), ('gpt-6.1-sol', 'medium'))
        selected = {'model': 'gpt-6-astra', 'effort': 'high'}
        reading.save_settings(selected)
        self.assertEqual(reading.get_settings(), selected)
        self.assertEqual(legacy_path.read_bytes(), legacy_bytes)

    def test_upgrade_reuses_existing_legacy_job_and_keeps_it_visible(self):
        legacy_path = reading.LEGACY_QUEUE_DIR / (reading.job_id(self.paper) + '.json')
        legacy_job = {'schema_version': 3, 'status': 'running', 'message': '旧精读任务执行中',
                      'thread_id': 'legacy-thread', 'model': 'gpt-6-astra', 'effort': 'high'}
        reading._write(legacy_path, legacy_job)
        original = legacy_path.read_bytes()
        result = reading.enqueue(self.paper, {'model': 'gpt-6.1-sol', 'effort': 'medium'})
        self.assertEqual(result['thread_id'], 'legacy-thread')
        self.assertEqual(result['status'], 'running')
        self.assertFalse(self.path().exists())
        self.assertEqual(legacy_path.read_bytes(), original)
        self.assertEqual(reading.reading_for(self.paper), result)
        self.assertEqual(server.snapshot()['papers'][0]['reading'], result)
        second_paper = dict(self.paper, id='paper-2', doi='10.1/second')
        reading.enqueue(second_paper)
        second_path = reading.QUEUE_DIR / (reading.job_id(second_paper) + '.json')
        new_job = json.loads(second_path.read_text())
        self.assertEqual(new_job['schema_version'], 4)
        self.assertTrue(new_job['receipt_path'])
        self.assertFalse((reading.LEGACY_QUEUE_DIR / second_path.name).exists())
        self.assertEqual(legacy_path.read_bytes(), original)

    def test_upgrade_dispatches_each_queue_with_its_worker_mode(self):
        reading._write(reading.LEGACY_QUEUE_DIR / 'legacy.json', {'status': 'running'})
        reading.enqueue(self.paper)
        with patch.object(reading.subprocess, 'Popen') as launch:
            result = reading.process_pending()
        self.assertEqual(result['status'], 'dispatching')
        self.assertEqual(launch.call_count, 2)
        legacy_command = launch.call_args_list[0].args[0]
        current_command = launch.call_args_list[1].args[0]
        self.assertIn('--worker', legacy_command)
        self.assertIn('--legacy', legacy_command)
        self.assertIn('--worker', current_command)
        self.assertNotIn('--legacy', current_command)
        self.assertNotEqual(reading.QUEUE_DIR, reading.LEGACY_QUEUE_DIR)
        self.assertTrue((reading.QUEUE_DIR / '.worker.lock').exists())
        self.assertTrue((reading.LEGACY_QUEUE_DIR / '.worker.lock').exists())

    def test_live_legacy_worker_lock_does_not_block_new_queue(self):
        reading._write(reading.LEGACY_QUEUE_DIR / 'legacy.json', {'status': 'running'})
        reading.enqueue(self.paper)
        with (reading.LEGACY_QUEUE_DIR / '.worker.lock').open('a+') as lock:
            reading.fcntl.flock(lock, reading.fcntl.LOCK_EX | reading.fcntl.LOCK_NB)
            with patch.object(reading.subprocess, 'Popen') as launch:
                result = reading.process_pending()
            self.assertEqual(result['status'], 'dispatching')
            launch.assert_called_once()
            self.assertNotIn('--legacy', launch.call_args.args[0])

    def test_local_favorite_durable_outbox_independent_of_dispatch_failure(self):
        with patch.object(reading, 'enqueue', side_effect=OSError('disk full')), patch.object(reading, 'process_pending'):
            server.action('paper-1', 'favorite')
            server.dispatch_reading_requests()
        snapshot = server.snapshot()
        self.assertTrue(snapshot['papers'][0]['favorite'])
        self.assertEqual(snapshot['papers'][0]['reading']['status'], 'pending')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        self.assertTrue(self.path().exists())

    def test_repeat_favorite_and_unfavorite_keep_single_original_request(self):
        server.action('paper-1', 'favorite')
        reading.save_settings({'model': 'gpt-6.1-sol', 'effort': 'medium'})
        server.action('paper-1', 'unfavorite')
        server.action('paper-1', 'favorite')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        self.assertEqual(json.loads(self.path().read_text())['model'], 'gpt-6-astra')
        self.assertEqual(len(list(reading.QUEUE_DIR.glob('*.json'))), 2)  # settings and one job
        with server.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM reading_requests_v3').fetchone()[0], 1)

    def test_no_historical_favorites_replay(self):
        with server.connect() as conn:
            conn.execute('UPDATE papers SET favorite=1')
        old_queue = self.root / 'reading_queue'
        old_queue.mkdir()
        (old_queue / 'old.json').write_text('{"status":"pending"}')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        self.assertFalse(self.path().exists())

    def test_alias_identity_is_idempotent_and_prompt_has_no_zotero_snapshot(self):
        reading.enqueue(self.paper)
        alias = dict(self.paper, doi='https://doi.org/10.1/TEST')
        reading.enqueue(alias)
        self.assertEqual(len(list(reading.QUEUE_DIR.glob('*.json'))), 1)
        prompt = json.loads(self.path().read_text())['prompt']
        self.assertIn(reading.SKILL_PATH, prompt)
        self.assertNotIn('all_main_panels_read', prompt)
        self.assertNotIn('reading_receipt', prompt)
        self.assertIn('Take-home message', prompt)
        self.assertIn('以正文为主', prompt)
        job = json.loads(self.path().read_text())
        self.assertEqual(Path(job['receipt_path']), self.root / '.paper-inbox' / (reading.job_id(self.paper) + '.json'))
        self.assertIn(job['receipt_path'], job['completion_instructions'])
        self.assertIn('all_main_panels_read', job['completion_instructions'])
        self.assertNotIn('本地 Zotero PDF', prompt)

    def test_submission_uses_official_protocol_and_exact_settings(self):
        reading.enqueue(self.paper)
        client = FakeClient()
        reading._run_one(self.path(), client)
        self.assertEqual([method for method, params in client.calls], [
            'thread/start', 'turn/start', 'thread/name/set', 'thread/read'])
        start = client.calls[0][1]
        self.assertFalse(start['ephemeral'])
        self.assertEqual(start['sandbox'], 'workspace-write')
        self.assertEqual(start['cwd'], str(self.root))
        job = json.loads(self.path().read_text())
        self.assertEqual(start['developerInstructions'], job['completion_instructions'])
        self.assertNotIn('all_main_panels_read', job['prompt'])
        turn = next(params for method, params in client.calls if method == 'turn/start')
        self.assertEqual((turn['model'], turn['effort']), ('gpt-6-astra', 'high'))
        self.assertEqual(turn['input'][1]['type'], 'skill')
        self.assertEqual(json.loads(self.path().read_text())['turn_id'], 'turn-1')

    def test_unknown_thread_creation_is_never_retried(self):
        reading.enqueue(self.paper)
        client = FakeClient(failure='thread/start')
        with self.assertRaises(ConnectionError):
            reading._run_one(self.path(), client)
        retry = FakeClient()
        reading._run_one(self.path(), retry)
        self.assertFalse(retry.calls)
        self.assertEqual(json.loads(self.path().read_text())['status'], 'submission_unknown')

    def test_uncertain_turn_submission_recovers_original_without_second_turn(self):
        reading.enqueue(self.paper)
        with self.assertRaises(ConnectionError):
            reading._run_one(self.path(), FakeClient(failure='turn/start'))
        retry = FakeClient()
        reading._run_one(self.path(), retry)
        self.assertEqual([method for method, _ in retry.calls], ['thread/read'])
        self.assertEqual(json.loads(self.path().read_text())['turn_id'], 'turn-1')

    def test_uncertain_turn_with_empty_history_stops_without_resubmission(self):
        reading.enqueue(self.paper)
        with self.assertRaises(ConnectionError):
            reading._run_one(self.path(), FakeClient(failure='turn/start'))
        client = FakeClient()
        original = client.rpc
        def empty_history(method, params):
            if method == 'thread/read':
                client.calls.append((method, params))
                return {'thread': {'turns': []}}
            return original(method, params)
        client.rpc = empty_history
        reading._run_one(self.path(), client)
        self.assertEqual([method for method, _ in client.calls], ['thread/read'])
        self.assertEqual(json.loads(self.path().read_text())['status'], 'submission_unknown')

    def test_failed_rename_retries_only_rename(self):
        reading.enqueue(self.paper)
        reading._run_one(self.path(), FakeClient())
        self.write_receipt()
        turn = {'id': 'turn-1', 'status': 'completed', 'items': [
            {'type': 'agentMessage', 'text': self.clean_report()}]}
        with self.assertRaises(ConnectionError):
            reading._finish(FakeClient(failure='thread/name/set'), self.path(), turn)
        self.assertTrue(json.loads(self.path().read_text())['rename_pending'])
        retry = FakeClient()
        reading._run_one(self.path(), retry)
        self.assertEqual([method for method, _ in retry.calls], ['thread/name/set'])
        self.assertFalse(json.loads(self.path().read_text())['rename_pending'])

    def test_completion_extracts_supported_method_and_renames(self):
        reading.enqueue(self.paper)
        reading._run_one(self.path(), FakeClient())
        self.write_receipt()
        turn = {'id': 'turn-1', 'status': 'completed', 'items': [
            {'type': 'agentMessage', 'phase': 'final_answer', 'text': self.clean_report()}]}
        client = FakeClient(completed=turn)
        reading._run_one(self.path(), client)
        job = json.loads(self.path().read_text())
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['method_name'], 'TestMethod')
        self.assertEqual(client.calls[-1], ('thread/name/set', {'threadId': 'thread-1', 'name': 'TestMethod'}))
        report = Path(job['report_path']).read_text()
        self.assertEqual(report, self.clean_report())
        self.assertNotIn('reading_receipt', report)
        self.assertTrue(report.endswith('- 方法解决了论文提出的问题。'))
        import zotero_bridge as zotero
        with patch.object(zotero, 'save_paper', return_value={'status': 'saved', 'key': 'ABCDEFGH', 'message': '已加入 AI 文献收藏'}) as save:
            reading._sync_zotero(self.path())
        save.assert_called_once()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'saved')

    def test_incomplete_or_unsupported_method_never_renames(self):
        reading.enqueue(self.paper)
        reading._run_one(self.path(), FakeClient())
        for overrides in ({'full_text_read': False}, {'all_main_panels_read': False},
                          {'method_name': 'Invented'}):
            self.write_receipt(**overrides)
            turn = {'id': 'turn-1', 'status': 'completed', 'items': [
                {'type': 'agentMessage', 'text': self.clean_report()}]}
            client = FakeClient(completed=turn)
            reading._finish(client, self.path(), turn)
            self.assertFalse(client.calls)
            self.assertNotIn('method_name', json.loads(self.path().read_text()))

    def test_legacy_job_still_accepts_inline_receipt(self):
        reading.enqueue(self.paper)
        job = json.loads(self.path().read_text())
        job.pop('receipt_path')
        job.pop('completion_instructions')
        job.update(thread_id='thread-legacy')
        reading._write(self.path(), job)
        turn = {'id': 'turn-legacy', 'status': 'completed', 'items': [
            {'type': 'agentMessage', 'text': self.receipt()}]}
        client = FakeClient()
        reading._finish(client, self.path(), turn)
        saved = json.loads(self.path().read_text())
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['method_name'], 'TestMethod')
        self.assertEqual(client.calls, [('thread/name/set', {'threadId': 'thread-legacy', 'name': 'TestMethod'})])

    def test_new_job_never_uses_inline_receipt_when_sidecar_missing_or_invalid(self):
        import zotero_bridge as zotero
        reading.enqueue(self.paper)
        job = json.loads(self.path().read_text())
        receipt_path = Path(job['receipt_path'])
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        for raw in (None, '{broken JSON', '[]', 'null', 'x' * 100001, b'\xff'):
            with self.subTest(raw_kind=type(raw).__name__, raw_size=len(raw) if raw else 0):
                if receipt_path.exists():
                    receipt_path.unlink()
                if isinstance(raw, bytes):
                    receipt_path.write_bytes(raw)
                elif raw is not None:
                    receipt_path.write_text(raw, encoding='utf-8')
                turn = {'id': 'turn-1', 'status': 'completed', 'items': [
                    {'type': 'agentMessage', 'text': self.receipt()}]}
                client = FakeClient()
                reading._finish(client, self.path(), turn)
                job = json.loads(self.path().read_text())
                self.assertEqual(job['status'], 'incomplete')
                self.assertNotIn('method_name', job)
                self.assertFalse(client.calls)
                with patch.object(zotero, 'save_paper') as save:
                    reading._sync_zotero(self.path())
                save.assert_not_called()

    def test_non_object_receipt_marks_report_incomplete(self):
        reading.enqueue(self.paper)
        receipt_path = Path(json.loads(self.path().read_text())['receipt_path'])
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        for value in ('[]', 'null', 'true', '"unexpected"'):
            self.assertIsNone(reading._receipt('```reading_receipt\n' + value + '\n```'))
            receipt_path.write_text(value, encoding='utf-8')
            turn = {'id': 'turn-1', 'status': 'completed', 'items': [
                {'type': 'agentMessage', 'phase': 'final_answer', 'text': self.clean_report()}]}
            reading._finish(FakeClient(), self.path(), turn)
            job = json.loads(self.path().read_text())
            self.assertEqual(job['status'], 'incomplete')
            self.assertFalse(reading._zotero_due(job))

    def test_paper_error_keeps_other_turns_on_same_connection(self):
        reading.enqueue(self.paper)
        second_paper = dict(self.paper, id='paper-2', doi='10.1/second')
        reading.enqueue(second_paper)
        second_path = reading.QUEUE_DIR / (reading.job_id(second_paper) + '.json')
        client = FakeClient()
        client.closed = False
        client.events = []
        client.initialize = lambda: None
        def close():
            client.closed = True
        client.close = close
        def receive(timeout):
            raise reading.queue.Empty()
        client.receive = receive
        visited = []
        def run(path, active_client):
            self.assertIs(active_client, client)
            self.assertFalse(client.closed)
            visited.append(path)
            if path == self.path():
                raise ValueError('malformed paper response')
            reading._update(path, status='incomplete')
        with patch.object(reading, 'AppServer', return_value=client), patch.object(reading, '_run_one', side_effect=run):
            reading._worker()
        self.assertEqual(set(visited), {self.path(), second_path})
        self.assertEqual(json.loads(self.path().read_text())['status'], 'failed')
        self.assertEqual(json.loads(second_path.read_text())['status'], 'incomplete')
        self.assertTrue(client.closed)

    def test_rename_error_preserves_completed_read_without_permanent_retry(self):
        reading.enqueue(self.paper)
        reading._update(self.path(), status='completed', rename_pending=True, thread_id='thread-1', method_name='TestMethod')
        client = FakeClient(failure='thread/name/set')
        client.initialize = lambda: None
        client.events = []
        client.close = lambda: None
        def receive(timeout):
            raise reading.queue.Empty()
        client.receive = receive
        def rejected(method, params):
            raise RuntimeError('name rejected')
        client.rpc = rejected
        with patch.object(reading, 'AppServer', return_value=client):
            reading._worker()
        job = json.loads(self.path().read_text())
        self.assertEqual(job['status'], 'completed')
        self.assertFalse(job['rename_pending'])
        self.assertIn('name rejected', job['last_error'])

    def completed_job(self):
        reading.enqueue(self.paper)
        reading._update(self.path(), status='completed', reading_receipt=self.receipt_data(),
                        zotero_status='pending', thread_id='thread-1')

    def test_zotero_only_after_complete_read(self):
        import zotero_bridge as zotero
        reading.enqueue(self.paper)
        reading._update(self.path(), status='incomplete')
        with patch.object(zotero, 'save_paper') as save:
            reading._sync_zotero(self.path())
        save.assert_not_called()

    def test_zotero_closed_preserves_read_and_retries_without_model(self):
        import zotero_bridge as zotero
        self.completed_job()
        with patch.object(zotero, 'save_paper', return_value={'status': 'pending', 'message': '启动 Zotero 后重试'}):
            reading._sync_zotero(self.path())
        job = json.loads(self.path().read_text())
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['zotero_status'], 'pending')
        self.assertGreater(job['zotero_next_retry'], 0)
        reading._update(self.path(), zotero_next_retry=0)
        with patch.object(zotero, 'save_paper', return_value={'status': 'saved', 'key': 'ABCDEFGH', 'message': '已加入 AI 文献收藏'}) as save:
            reading._sync_zotero(self.path())
        self.assertFalse(save.call_args.kwargs['attach_pdf'])
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'saved')

    def test_uncertain_zotero_submission_never_reposts_metadata(self):
        import zotero_bridge as zotero
        self.completed_job()
        def uncertain(paper, on_submit, attach_pdf):
            on_submit({'sessionID': 'session-1', 'parentItemID': 'item-1',
                       'collection_key': 'COLLECT1', 'collection_target': 'C12'})
            return {'status': 'pending', 'message': 'timeout'}
        with patch.object(zotero, 'save_paper', side_effect=uncertain):
            reading._sync_zotero(self.path())
        reading._update(self.path(), zotero_next_retry=0)
        with patch.object(zotero, 'find_existing', return_value=None), patch.object(zotero, 'save_paper') as save:
            reading._sync_zotero(self.path())
        save.assert_not_called()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'submission_unknown')
        reading._update(self.path(), zotero_next_retry=0)
        with patch.object(zotero, 'find_existing', return_value={'key': 'ABCDEFGH', 'collections': ['COLLECT1']}), patch.object(zotero, 'save_paper') as save:
            reading._sync_zotero(self.path())
        save.assert_not_called()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'saved')

    def test_existing_item_uses_safe_collection_add_without_duplicate(self):
        import zotero_bridge as zotero
        self.completed_job()
        with patch.object(zotero, 'save_paper', return_value={'status': 'existing', 'key': 'ABCDEFGH', 'in_collection': False}), patch.object(zotero, 'add_to_collection', return_value={'status': 'saved', 'key': 'ABCDEFGH', 'in_collection': True, 'message': '已加入收藏分类'}) as add:
            reading._sync_zotero(self.path())
        self.assertEqual(add.call_args.args[0]['zotero_key'], 'ABCDEFGH')
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'saved')

    def test_arxiv_canonical_dedup_handles_pdf_and_versions(self):
        import zotero_bridge as zotero
        row = {'key': 'ABCDEFGH', 'data': {'title': 'Different title', 'url': 'https://arxiv.org/pdf/2611.12345v2', 'collections': []}}
        def get(path):
            return [] if path.endswith('/children') else [row]
        with patch.object(zotero, '_get', side_effect=get):
            found = zotero.find_existing({'title': 'Current title', 'url': 'https://arxiv.org/abs/2611.12345v3'})
        self.assertEqual(found['key'], 'ABCDEFGH')

    def test_zotero_offline_requests_background_launch_once(self):
        import zotero_bridge as zotero
        self.completed_job()
        with patch.object(zotero, 'save_paper', return_value={'status': 'pending', 'message': '待同步'}), patch.object(zotero, 'probe', return_value={'available': False}), patch.object(reading.subprocess, 'run') as launch:
            launch.return_value.returncode = 0
            reading._sync_zotero(self.path())
            self.assertTrue(json.loads(self.path().read_text())['zotero_launch_attempted'])
            reading._update(self.path(), zotero_next_retry=0)
            reading._sync_zotero(self.path())
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(launch.call_args.args[0], ['open', '-g', '-a', 'Zotero'])

    def test_connector_receipt_precedes_save_and_pdf_is_optional(self):
        import zotero_bridge as zotero
        self.completed_job()
        found = {'key': 'ABCDEFGH', 'collections': ['COLLECT1'], 'has_pdf': False}
        def post(path, payload, **kwargs):
            if path == '/connector/getSelectedCollection':
                return {'libraryID': 1}
            if path == '/connector/saveItems':
                job = json.loads(self.path().read_text())
                self.assertEqual(job['zotero_submission']['sessionID'], payload['sessionID'])
                self.assertEqual(job['zotero_status'], 'saving')
                self.assertEqual(payload['items'][0]['title'], self.paper['title'])
            return {}
        with patch.object(zotero, 'find_existing', side_effect=[None, found]), patch.object(zotero, '_collection', return_value={'key': 'COLLECT1', 'collectionID': 12, 'libraryID': 1}), patch.object(zotero, '_post', side_effect=post), patch.object(zotero, '_remember'), patch.object(zotero, '_download_pdf') as download:
            reading._sync_zotero(self.path())
        download.assert_not_called()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'saved')

    def test_unpersisted_empty_thread_is_preserved_on_restart(self):
        reading.enqueue(self.paper)
        reading._update(self.path(), status='thread_created', thread_id='empty-thread')
        client = FakeClient()
        def no_rollout(method, params):
            client.calls.append((method, params))
            raise RuntimeError('no rollout found for thread id')
        client.rpc = no_rollout
        reading._run_one(self.path(), client)
        self.assertEqual(client.calls, [('thread/resume', {'threadId': 'empty-thread'})])
        self.assertEqual(json.loads(self.path().read_text())['status'], 'submission_unknown')

    def test_all_verified_effort_options_are_accepted(self):
        for model in ('gpt-6-astra', 'gpt-6.1-sol'):
            for effort in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
                self.assertEqual(reading.validate_settings({'model': model, 'effort': effort})['effort'], effort)

    def test_summary_extraction_respects_sections_and_ignores_receipt(self):
        report = ('## 2. Motivation\n研究问题。已有困难。\n## Methods\n不应提取这里。\n'
                  '## 6. Take-home message\n主要发现。证据边界。第三句。第四句。\n'
                  '## 附录\n不应带入附录。\n```reading_receipt\n'
                  '{"motivation":"污染字段"}\n```\n')
        result = reading._report_summaries(report)
        self.assertEqual(result['motivation'], '研究问题。 已有困难。')
        self.assertEqual(result['take_home_message'], '主要发现。 证据边界。 第三句。')
        self.assertNotIn('污染', str(result))
        self.assertEqual(reading._report_summaries('只有摘要，不含对应小节。'), {})

    def test_receipt_summaries_are_validated_and_persisted(self):
        reading.enqueue(self.paper)
        receipt = self.receipt_data(motivation='研究问题。已有困难。', take_home_message='主要发现。证据边界。')
        self.write_receipt(**receipt)
        turn = {'id': 'turn-1', 'status': 'completed', 'items': [{'type': 'agentMessage', 'text': '报告正文'}]}
        reading._update(self.path(), thread_id='thread-1')
        reading._finish(FakeClient(), self.path(), turn)
        job = json.loads(self.path().read_text())
        self.assertEqual(job['motivation'], receipt['motivation'])
        self.assertEqual(job['take_home_message'], receipt['take_home_message'])
        self.assertEqual(reading._summary_text({'not': 'string'}, 2), '')
        self.assertEqual(reading._summary_text('K_D 和 method_v2。', 2), 'K_D 和 method_v2。')
        self.assertEqual(reading._summary_text('一。二。三。', 2), '')

    def test_bilingual_receipt_survives_completion_and_api(self):
        reading.enqueue(self.paper)
        translations = dict(motivation_zh='现有方法缺少记忆。', motivation_en='Existing methods lack memory.',
                            take_home_message_zh='结构化记忆改善优化。', take_home_message_en='Structured memory improves optimization.')
        self.write_receipt(**self.receipt_data(**translations))
        reading._update(self.path(), thread_id='thread-1')
        reading._finish(FakeClient(), self.path(), {'id': 'turn-1', 'status': 'completed', 'items': [{'type': 'agentMessage', 'text': '报告正文'}]})
        job = json.loads(self.path().read_text())
        response = reading._response(job)
        for key, value in translations.items():
            self.assertEqual(job[key], value)
            self.assertEqual(response[key], value)
        self.assertEqual(response['motivation'], translations['motivation_zh'])
        self.assertIn('motivation_en', reading.completion_instructions(self.paper))

    def test_older_completed_summary_fallback_reads_actual_report_only(self):
        report = self.root / 'report.md'
        report.write_text('## Motivation\n真实报告动机。\n## Take-home message\n真实发现。真实边界。')
        result = reading._response({'status': 'completed', 'report_path': str(report)})
        self.assertEqual(result['motivation'], '真实报告动机。')
        self.assertEqual(result['take_home_message'], '真实发现。 真实边界。')
        result = reading._response({'status': 'completed', 'paper': {'abstract': '不可推断内容'}})
        self.assertEqual(result['motivation'], '')

    def test_unfavorite_intent_stops_late_postread_save_and_trashes_item(self):
        import zotero_bridge as zotero
        self.completed_job()
        server.action('paper-1', 'unfavorite')
        with patch.object(zotero, 'save_paper') as save, patch.object(zotero, 'trash_paper', return_value={'status': 'trashed', 'key': 'ABCDEFGH'}) as trash:
            reading._sync_zotero(self.path())
        save.assert_not_called()
        trash.assert_called_once()
        self.assertEqual(json.loads(self.path().read_text())['status'], 'completed')
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'trashed')

    def test_unfavorite_during_inflight_save_compensates_and_does_not_reread(self):
        import zotero_bridge as zotero
        self.completed_job()
        def saved_then_unstar(*args, **kwargs):
            server.action('paper-1', 'unfavorite')
            return {'status': 'saved', 'key': 'ABCDEFGH'}
        with patch.object(zotero, 'save_paper', side_effect=saved_then_unstar), patch.object(zotero, 'trash_paper', return_value={'status': 'trashed'}) as trash:
            reading._sync_zotero(self.path())
        trash.assert_called_once()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'trashed')

    def test_refavorite_reuses_reading_and_resyncs_existing_zotero_item(self):
        import zotero_bridge as zotero
        self.completed_job()
        reading._update(self.path(), zotero_status='removed')
        server.action('paper-1', 'favorite')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        job = json.loads(self.path().read_text())
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['thread_id'], 'thread-1')
        with patch.object(zotero, 'save_paper', return_value={'status': 'existing', 'key': 'ABCDEFGH', 'in_collection': False}), patch.object(zotero, 'add_to_collection', return_value={'status': 'saved', 'key': 'ABCDEFGH'}) as add:
            reading._sync_zotero(self.path())
        add.assert_called_once()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'saved')

    def test_stale_outbox_delivery_cannot_override_newer_intent(self):
        reading.enqueue(self.paper)
        reading.set_favorite(self.paper, False, reading.DEFAULT_SETTINGS, 3)
        reading.set_favorite(self.paper, True, reading.DEFAULT_SETTINGS, 2)
        self.assertFalse(json.loads(self.path().read_text())['desired_favorite'])

    def test_intent_changed_during_delivery_remains_pending(self):
        server.action('paper-1', 'favorite')
        original = reading.set_favorite
        def changed(*args, **kwargs):
            original(*args, **kwargs)
            server.action('paper-1', 'unfavorite')
        with patch.object(reading, 'set_favorite', side_effect=changed), patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        with server.connect() as conn:
            row = conn.execute('SELECT * FROM reading_requests_v3').fetchone()
        self.assertEqual((row['desired'], row['delivered'], row['revision']), (0, 0, 2))

    def test_unknown_save_is_still_monitored_after_unfavorite(self):
        import zotero_bridge as zotero
        self.completed_job()
        reading._update(self.path(), zotero_submission={'sessionID': 'uncertain'})
        server.action('paper-1', 'unfavorite')
        with patch.object(zotero, 'trash_paper', return_value={'status': 'not_found'}):
            reading._sync_zotero(self.path())
        job = json.loads(self.path().read_text())
        self.assertEqual(job['zotero_status'], 'trash_pending')
        self.assertGreater(job['zotero_next_retry'], 0)

    def test_unfavorite_without_read_job_never_starts_reading(self):
        server.action('paper-1', 'unfavorite')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        job = json.loads(self.path().read_text())
        self.assertEqual(job['status'], 'not_requested')
        self.assertIsNone(job['thread_id'])
        server.action('paper-1', 'favorite')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        self.assertEqual(json.loads(self.path().read_text())['status'], 'pending')

    def test_collection_authorization_failure_is_durable_without_prompt(self):
        import zotero_bridge as zotero
        self.completed_job()
        server.action('paper-1', 'unfavorite')
        with patch.object(zotero, 'trash_paper', return_value={'status': 'authorization_required', 'message': '等待本地写入授权'}), patch.object(zotero, 'authorize_local_writes') as authorize:
            reading._sync_zotero(self.path())
        authorize.assert_not_called()
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'authorization_required')

    def test_crossref_enrichment_retains_explicit_author_indices(self):
        message = {'author': [
            {'given': 'Alex', 'family': 'One', 'affiliation': [{'name': 'Institute A'}]},
            {'given': 'Bea', 'family': 'Two', 'affiliation': [{'name': 'Institute B'}]}]}
        with patch.object(server, 'fetch_json', return_value={'message': message}):
            paper = server.enrich({'title': 'Paper', 'url': 'https://doi.org/10.1/test'})
        self.assertEqual(paper['author_affiliations'], {'Alex One': [1], 'Bea Two': [2]})
        self.assertEqual(paper['affiliations'], ['Institute A', 'Institute B'])

    def test_outbox_migration_preserves_prior_unfavorite_intent(self):
        with server.connect() as conn:
            conn.execute('UPDATE papers SET favorite=0')
            conn.execute('DROP TABLE reading_requests_v3')
            conn.execute('CREATE TABLE reading_requests_v3(paper_id TEXT PRIMARY KEY,paper TEXT NOT NULL,settings TEXT NOT NULL,delivered INTEGER DEFAULT 0,error TEXT DEFAULT "")')
            conn.execute('INSERT INTO reading_requests_v3(paper_id,paper,settings,delivered) VALUES(?,?,?,1)',
                         ('paper-1', json.dumps(self.paper), json.dumps(reading.DEFAULT_SETTINGS)))
        server.init_db()
        with server.connect() as conn:
            row = conn.execute('SELECT desired,delivered,revision FROM reading_requests_v3').fetchone()
            self.assertEqual(tuple(row), (0, 0, 1))
            self.assertEqual(conn.execute('SELECT favorite FROM papers').fetchone()[0], 0)

    def test_direct_existing_job_obeys_local_unfavorite_without_outbox(self):
        import zotero_bridge as zotero
        self.completed_job()
        with server.connect() as conn:
            conn.execute('UPDATE papers SET favorite=0 WHERE id="paper-1"')
            self.assertEqual(conn.execute('SELECT count(*) FROM reading_requests_v3').fetchone()[0], 0)
        with patch.object(zotero, 'save_paper') as save, patch.object(zotero, 'trash_paper', return_value={'status': 'trashed'}) as trash:
            reading._sync_zotero(self.path())
        save.assert_not_called()
        trash.assert_called_once()
        self.assertEqual(json.loads(self.path().read_text())['status'], 'completed')

    def test_old_membership_removal_receipts_reconcile_to_library_trash(self):
        import zotero_bridge as zotero
        self.completed_job()
        server.action('paper-1', 'unfavorite')
        for status in ('removed', 'not_member'):
            reading._update(self.path(), zotero_status=status, zotero_next_retry=0)
            self.assertTrue(reading._zotero_due(json.loads(self.path().read_text())))
            with patch.object(zotero, 'trash_paper', return_value={'status': 'trashed', 'key': 'ABCDEFGH'}) as trash:
                reading._sync_zotero(self.path())
            trash.assert_called_once()
            self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'trashed')

    def test_refavorite_restores_exact_trashed_key_without_duplicate_or_reread(self):
        import zotero_bridge as zotero
        self.completed_job()
        reading._update(self.path(), zotero_status='trashed', zotero_key='ABCDEFGH')
        server.action('paper-1', 'favorite')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
        with patch.object(zotero, 'restore_paper', return_value={'status': 'restored', 'key': 'ABCDEFGH'}) as restore, patch.object(zotero, 'add_to_collection', return_value={'status': 'saved', 'key': 'ABCDEFGH'}) as add, patch.object(zotero, 'save_paper') as create:
            reading._sync_zotero(self.path())
        create.assert_not_called()
        self.assertEqual(restore.call_args.args[0]['zotero_key'], 'ABCDEFGH')
        self.assertEqual(add.call_args.args[0]['zotero_key'], 'ABCDEFGH')
        job = json.loads(self.path().read_text())
        self.assertEqual((job['status'], job['thread_id'], job['zotero_key'], job['zotero_status']),
                         ('completed', 'thread-1', 'ABCDEFGH', 'saved'))

    def test_restore_failure_preserves_key_and_never_creates_replacement(self):
        import zotero_bridge as zotero
        self.completed_job()
        reading._update(self.path(), zotero_status='trashed', zotero_key='ABCDEFGH')
        with patch.object(zotero, 'restore_paper', return_value={'status': 'authorization_required'}), patch.object(zotero, 'save_paper') as create, patch.object(zotero, 'add_to_collection') as add:
            reading._sync_zotero(self.path())
        create.assert_not_called()
        add.assert_not_called()
        job = json.loads(self.path().read_text())
        self.assertEqual(job['zotero_key'], 'ABCDEFGH')
        self.assertEqual(job['zotero_status'], 'authorization_required')

    def test_unfavorite_while_restoring_returns_same_key_to_trash(self):
        import zotero_bridge as zotero
        self.completed_job()
        reading._update(self.path(), zotero_status='trashed', zotero_key='ABCDEFGH')
        def restored_then_unstar(paper):
            server.action('paper-1', 'unfavorite')
            return {'status': 'restored', 'key': 'ABCDEFGH'}
        with patch.object(zotero, 'restore_paper', side_effect=restored_then_unstar), patch.object(zotero, 'trash_paper', return_value={'status': 'trashed', 'key': 'ABCDEFGH'}) as trash, patch.object(zotero, 'add_to_collection') as add:
            reading._sync_zotero(self.path())
        add.assert_not_called()
        self.assertEqual(trash.call_args.args[0]['zotero_key'], 'ABCDEFGH')
        self.assertEqual(json.loads(self.path().read_text())['zotero_status'], 'trashed')

    def test_outbox_retry_after_enqueue_before_delivery_mark_is_idempotent(self):
        server.action('paper-1', 'favorite')
        with patch.object(reading, 'process_pending'):
            server.dispatch_reading_requests()
            with server.connect() as conn:
                conn.execute('UPDATE reading_requests_v3 SET delivered=0')
            server.dispatch_reading_requests()
        self.assertEqual(len(list(reading.QUEUE_DIR.glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
