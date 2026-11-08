import argparse
from contextlib import nullcontext
import datetime as dt
import io
import json
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import app_settings
import collector
import server


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'sources.json'
        self.infrastructure = {'retrieval_python': sys.executable, 'project': '/existing/runtime', 'zotero_db': '/existing/library',
                               'lookback_days': 1, 'schedule_utc_hour': 22,
                               'schedule_utc_minute': 0, 'max_per_source': 10}
        self.path.write_text(json.dumps(self.infrastructure))
        self.patches = [patch.object(app_settings, 'SOURCES_FILE', self.path),
                        patch.object(server, 'DB', self.root / 'inbox.sqlite')]
        for patcher in self.patches:
            patcher.start()
        server.init_db()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp.cleanup()

    def test_clean_checkout_displays_defaults_without_creating_user_config(self):
        self.path.unlink()
        self.assertEqual(app_settings.get_settings(), app_settings.DEFAULTS)
        self.assertFalse(self.path.exists())
        self.assertEqual(server.snapshot()['app_settings'], app_settings.DEFAULTS)
        self.assertFalse(self.path.exists())
        with self.assertRaisesRegex(RuntimeError, 'setup.sh'):
            app_settings.retrieval_python()

    def test_unconfigured_update_reports_setup_step_without_spawning(self):
        self.path.unlink()
        with patch.object(server, 'CACHE', self.root), patch.object(server, 'today', return_value='2026-11-05'), patch.object(server.subprocess, 'Popen') as spawn, patch('fulltext.load_config', return_value={}), patch.dict(server.STATUS, updating=False):
            server.run_update()
            self.assertIn('setup.sh', server.STATUS['message'])
        spawn.assert_not_called()

    def test_settings_can_be_saved_before_runtime_setup_without_fake_paths(self):
        self.path.unlink()
        app_settings.save_settings(dict(app_settings.DEFAULTS, language='en'))
        config = json.loads(self.path.read_text())
        self.assertNotIn('retrieval_python', config)
        self.assertEqual(config['language'], 'en')
        with self.assertRaisesRegex(RuntimeError, 'setup.sh'):
            app_settings.retrieval_python()

    def test_missing_interpreter_has_clear_repair_message(self):
        config = dict(self.infrastructure, retrieval_python=str(self.root / 'missing-python'))
        self.path.write_text(json.dumps(config))
        with self.assertRaisesRegex(RuntimeError, 'setup.sh'):
            app_settings.retrieval_python()

    def test_invalid_config_has_clear_setup_message(self):
        for contents in ('{broken', '[]', 'null'):
            self.path.write_text(contents)
            with self.assertRaisesRegex(RuntimeError, 'setup.sh'):
                app_settings.load_config()

    def test_defaults_and_save_preserve_infrastructure(self):
        self.assertEqual(app_settings.get_settings(), app_settings.DEFAULTS)
        value = dict(app_settings.DEFAULTS, daily_limit=35, enabled_sources=['arXiv'])
        self.assertEqual(app_settings.save_settings(value), value)
        config = json.loads(self.path.read_text())
        self.assertEqual({key: config[key] for key in self.infrastructure}, self.infrastructure)
        self.assertEqual(server.snapshot()['app_settings'], value)

    def test_invalid_counts_queries_and_sources_rejected(self):
        invalid = [dict(app_settings.DEFAULTS, daily_limit=value) for value in (True, 0, 51, 1.5, '10')]
        invalid += [dict(app_settings.DEFAULTS, arxiv_query=value) for value in ('', 'a\nb', 'x' * 513)]
        invalid += [dict(app_settings.DEFAULTS, enabled_sources=value) for value in ([], ['arXiv', 'arXiv'], ['unknown'])]
        invalid += [dict(app_settings.DEFAULTS, project='/replacement')]
        for value in invalid:
            with self.assertRaises(ValueError):
                app_settings.save_settings(value)
        self.assertEqual(json.loads(self.path.read_text()), self.infrastructure)

    def test_post_settings_does_not_start_update_or_reading(self):
        value = dict(app_settings.DEFAULTS, daily_limit=12)
        handler = object.__new__(server.Handler)
        body = json.dumps(value).encode()
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.path = '/api/app-settings'
        handler.authorized = lambda: True
        handler.reply = Mock()
        with patch.object(server, 'run_update') as update, patch.object(server.reading_dispatch, 'process_pending') as reading:
            handler.do_POST()
        update.assert_not_called()
        reading.assert_not_called()
        self.assertEqual(handler.reply.call_args.args[0]['app_settings'], value)

    def test_ingest_filters_cached_sources_and_retains_existing_papers(self):
        app_settings.save_settings(dict(app_settings.DEFAULTS, daily_limit=2, enabled_sources=['arXiv']))
        with server.connect() as conn:
            conn.execute('INSERT INTO papers(id,data,day,favorite) VALUES(?,?,?,1)',
                         ('old', json.dumps({'title': 'Retained journal paper', 'source': '期刊'}), '2026-11-04'))
        papers = [{'url': 'https://example.org/' + str(i), 'title': str(i), 'score': i,
                   'source': source, 'abstract': 'A'} for i, source in enumerate(['arXiv', 'bioRxiv', '期刊', 'arXiv', 'arXiv'])]
        path = self.root / 'candidates.json'
        path.write_text(json.dumps({'schedule_date_shanghai': '2026-11-05', 'papers': papers}))
        with patch.object(server, 'summarize'), patch.object(server, 'enrich', side_effect=lambda paper: paper):
            selected = server.ingest(path)
        self.assertEqual({paper['title'] for paper in selected}, {'3', '4'})
        with server.connect() as conn:
            self.assertEqual(conn.execute('SELECT favorite FROM papers WHERE id="old"').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM papers').fetchone()[0], 3)

    def test_summary_provider_preserves_retrieval_cache_and_validates_effort(self):
        original=dict(app_settings.DEFAULTS)
        chosen=dict(original,summary_provider='openai',summary_model='gpt-6.1-sol',summary_effort='medium')
        self.assertEqual(app_settings.retrieval_fingerprint(original),app_settings.retrieval_fingerprint(chosen))
        self.assertEqual(app_settings.validate(chosen)['summary_provider'],'openai')
        with self.assertRaises(ValueError):app_settings.validate(dict(chosen,summary_effort='none'))
        with self.assertRaises(ValueError):app_settings.validate(dict(chosen,summary_effort='ultra'))

    def test_settings_fingerprint_keeps_default_and_changed_caches_separate(self):
        original = dict(self.infrastructure, **app_settings.DEFAULTS)
        changed = dict(original, arxiv_query='q-bio.QM', daily_limit=20)
        default_path = app_settings.candidate_path(self.root, '2026-11-05', original)
        changed_path = app_settings.candidate_path(self.root, '2026-11-05', changed)
        self.assertEqual(default_path.name, 'candidates-v2.json')
        self.assertNotEqual(default_path, changed_path)
        default_path.parent.mkdir(parents=True)
        default_path.write_text('original material')
        changed_path.write_text('new query material')
        self.assertEqual(default_path.read_text(), 'original material')
        self.assertEqual(app_settings.candidate_path(self.root, '2026-11-05', original), default_path)

    def test_next_update_retrieves_changed_query_without_overwriting_old_cache(self):
        config = dict(self.infrastructure, **app_settings.DEFAULTS)
        default_path = app_settings.candidate_path(self.root / 'runs', '2026-11-05', config)
        default_path.parent.mkdir(parents=True)
        default_path.write_text('old candidate material')
        app_settings.save_settings(dict(app_settings.DEFAULTS, arxiv_query='q-bio.QM'))
        changed_path = app_settings.candidate_path(self.root / 'runs', '2026-11-05', app_settings.load_config())
        def retrieve(*args, **kwargs):
            changed_path.write_text('{"papers":[]}')
            return SimpleNamespace(poll=lambda: 0, returncode=0)
        with patch.object(server, 'CACHE', self.root), patch.object(server, 'today', return_value='2026-11-05'), patch.object(server.subprocess, 'Popen', side_effect=retrieve) as spawn, patch('fulltext.load_config', return_value={}), patch.object(server, 'ingest') as ingest, patch.dict(server.STATUS, updating=False):
            server.run_update()
        spawn.assert_called_once()
        ingest.assert_called_once_with(changed_path)
        self.assertEqual(default_path.read_text(), 'old candidate material')

    def test_language_and_actual_journal_options_persist(self):
        initial = app_settings.get_settings()
        self.assertEqual(initial['language'], 'zh-Hans')
        self.assertEqual(initial['journals'], app_settings.JOURNAL_GROUPS['xx'])
        options = server.snapshot()['journal_options']
        self.assertEqual(next(item['name'] for item in options if item['id'] == 'nature_methods'), 'Nature Methods')
        selected = dict(initial, language='en', journals=['nature_methods', 'science'])
        saved = app_settings.save_settings(selected)
        self.assertEqual(saved['language'], 'en')
        self.assertEqual(set(saved['journals']), {'science', 'nature_methods'})
        self.assertEqual(app_settings.get_settings(), saved)

    def test_language_does_not_invalidate_retrieval_but_journal_selection_does(self):
        original = dict(self.infrastructure, **app_settings.DEFAULTS)
        english = dict(original, language='en')
        chosen = dict(original, journals=['nature_methods'])
        self.assertEqual(app_settings.retrieval_fingerprint(original), app_settings.retrieval_fingerprint(english))
        self.assertEqual(app_settings.candidate_filename(original), app_settings.candidate_filename(english))
        self.assertNotEqual(app_settings.retrieval_fingerprint(original), app_settings.retrieval_fingerprint(chosen))

    def test_unknown_language_and_journals_rejected(self):
        for changes in ({'language': 'fr'}, {'journals': ['imaginary_journal']}, {'journals': []}, {'journals': ['nature', 'nature']}):
            with self.assertRaises(ValueError):
                app_settings.save_settings(dict(app_settings.DEFAULTS, **changes))
        disabled = dict(app_settings.DEFAULTS, journals=[], enabled_sources=['arXiv'])
        self.assertEqual(app_settings.save_settings(disabled)['journals'], [])

    def test_legacy_group_resolves_real_journals_and_old_request_keeps_language(self):
        legacy = dict(self.infrastructure, journal_group='rr')
        self.assertEqual(app_settings.from_config(legacy)['journals'], app_settings.JOURNAL_GROUPS['rr'])
        app_settings.save_settings(dict(app_settings.DEFAULTS, language='en'))
        old_request = {key: value for key, value in app_settings.DEFAULTS.items() if key not in ('language', 'journals')}
        old_request['journal_group'] = 'rr'
        saved = app_settings.save_settings(old_request)
        self.assertEqual(saved['language'], 'en')
        self.assertEqual(saved['journals'], app_settings.JOURNAL_GROUPS['rr'])

    def test_collector_fetches_only_explicitly_selected_journals(self):
        config = dict(self.infrastructure, **app_settings.DEFAULTS)
        config.update(enabled_sources=['Journals'], journals=['science'])
        choices = [SimpleNamespace(key='nature', name='Nature'), SimpleNamespace(key='science', name='Science')]
        paper = SimpleNamespace(title='Selected paper', summary='A', score=1, paper_url='https://example.org/paper',
                                journal='Science', published_at='2026-11-04')
        fetch = Mock(return_value=[paper])
        journal = SimpleNamespace(SUPPORTED_JOURNALS=choices, DEFAULT_FETCH_PER_JOURNAL=10,
                                  _build_session=lambda: nullcontext(object()), _retrieve_journal_papers=fetch)
        blocked = Mock(side_effect=AssertionError('disabled preprint source fetched'))
        logger = SimpleNamespace(add=Mock(return_value=1), remove=Mock())
        schedule = SimpleNamespace(get_scheduled_reference_utc=lambda: dt.datetime(2026, 11, 4, 22, tzinfo=dt.timezone.utc),
                                   iso_target_dates_utc=lambda days: ['2026-11-04'])
        modules = {'schedule_window': schedule, 'loguru': SimpleNamespace(logger=logger),
                   'biorxiv_demo': SimpleNamespace(get_arxiv_paper=blocked, get_biorxiv_paper=blocked),
                   'journal': journal, 'recommender': SimpleNamespace(rerank_paper=lambda a, b, c, corpus: (a, b, c))}
        with patch.dict('sys.modules', modules), patch.object(collector, 'BASE', self.root), patch.object(collector, 'setup'), patch.object(collector, 'read_corpus', return_value=[{'data': {'dateAdded': '2026-01-01'}}]), patch('builtins.print'):
            collector.run(config, argparse.Namespace(check=False, force=False))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1].key, 'science')
        result = json.loads(app_settings.candidate_path(self.root / 'cache/runs', '2026-11-05', config).read_text())
        self.assertEqual(result['papers'][0]['journal_key'], 'science')
        blocked.assert_not_called()

    def test_collector_disabled_sources_never_fetched_and_large_limit_supported(self):
        config = dict(self.infrastructure, **app_settings.DEFAULTS)
        config.update(daily_limit=35, enabled_sources=['arXiv'])
        papers = [SimpleNamespace(title=str(i), summary='A', score=i, arxiv_id=str(i), authors=[]) for i in range(55)]
        arxiv = Mock(return_value=papers)
        bio = Mock(side_effect=AssertionError('disabled source was fetched'))
        rerank = Mock(side_effect=lambda a, b, c, corpus: (a, b, c))
        logger = SimpleNamespace(add=Mock(return_value=1), remove=Mock())
        schedule = SimpleNamespace(get_scheduled_reference_utc=lambda: dt.datetime(2026, 11, 4, 22, tzinfo=dt.timezone.utc),
                                   iso_target_dates_utc=lambda days: ['2026-11-04'])
        journal = SimpleNamespace()
        modules = {'schedule_window': schedule, 'loguru': SimpleNamespace(logger=logger),
                   'biorxiv_demo': SimpleNamespace(get_arxiv_paper=arxiv, get_biorxiv_paper=bio),
                   'journal': journal, 'recommender': SimpleNamespace(rerank_paper=rerank)}
        with patch.dict('sys.modules', modules), patch.object(collector, 'BASE', self.root), patch.object(collector, 'setup'), patch.object(collector, 'read_corpus', return_value=[{'data': {'dateAdded': '2026-01-01'}}]), patch('builtins.print'):
            collector.run(config, argparse.Namespace(check=False, force=False))
        arxiv.assert_called_once_with(config['arxiv_query'])
        bio.assert_not_called()
        self.assertEqual(len(rerank.call_args.args), 4)
        self.assertEqual(rerank.call_args.args[1:3], ([], []))
        result = json.loads(app_settings.candidate_path(self.root / 'cache/runs', '2026-11-05', config).read_text())
        self.assertEqual(len(result['papers']), 35)
        self.assertFalse(result['sources']['bioRxiv']['enabled'])
        self.assertFalse(result['sources']['期刊']['enabled'])


if __name__ == '__main__':
    unittest.main()
