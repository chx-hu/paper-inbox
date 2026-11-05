import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import zotero_bridge as zotero


class ZoteroCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = Path(self.tmp.name) / 'auth.json'
        self.auth.write_text(json.dumps({'server_id': 'server-one', 'key': 'test-key'}))
        self.patches = [
            patch.object(zotero, 'AUTH_FILE', self.auth),
            patch.object(zotero, 'find_existing', return_value={'key': 'PAPER123', 'collections': ['AI123456']}),
            patch.object(zotero, '_get', return_value=[{'key': 'AI123456', 'data': {'name': zotero.COLLECTION}}]),
            patch.object(zotero, '_local_request'),
            patch.object(zotero, '_post', side_effect=AssertionError('Connector mutation is forbidden')),
        ]
        self.mocks = [mock.start() for mock in self.patches]
        self.request = self.mocks[3]
        self.paper = {'title': 'A paper', 'url': 'https://arxiv.org/abs/1234.5678'}
        self.headers = {'Zotero-Server-ID': 'server-one'}
        self.addCleanup(self.tmp.cleanup)
        for mock in self.patches:
            self.addCleanup(mock.stop)

    def row(self, collections, version=7):
        return {'key': 'PAPER123', 'version': version, 'data': {'collections': collections,
                'tags': [{'tag': 'my-tag'}], 'title': 'A paper'}}, self.headers

    def test_remove_preserves_all_other_collections_and_fields(self):
        self.request.side_effect = [self.row(['OTHER001', 'AI123456', 'OTHER002']),
                                    (None, self.headers), self.row(['OTHER001', 'OTHER002'], 8)]
        result = zotero.remove_from_collection(self.paper)
        self.assertEqual(result['status'], 'removed')
        self.assertEqual(self.request.call_args_list[1].args,
                         ('/api/users/0/items/PAPER123', 'PATCH',
                          {'version': 7, 'collections': ['OTHER001', 'OTHER002']},
                          {'Zotero-API-Key': 'test-key', 'Zotero-Server-ID': 'server-one'}))
        self.assertNotIn('test-key', json.dumps(result))

    def test_remove_last_collection_preserves_library_item(self):
        self.request.side_effect = [self.row(['AI123456']), (None, self.headers), self.row([], 8)]
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'removed')
        self.assertEqual(self.request.call_args_list[1].args[2], {'version': 7, 'collections': []})

    def test_already_removed_is_idempotent_without_permission(self):
        self.auth.unlink()
        self.request.return_value = self.row(['OTHER001'])
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'not_member')
        self.assertEqual(self.request.call_count, 1)

    def test_authorization_needed_does_not_prompt_or_write(self):
        self.auth.unlink()
        self.request.return_value = self.row(['AI123456'])
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'authorization_required')
        self.assertEqual(self.request.call_count, 1)

    def test_wrong_server_credentials_are_never_used(self):
        self.headers['Zotero-Server-ID'] = 'another-library-instance'
        self.request.return_value = self.row(['AI123456'])
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'authorization_required')
        self.assertEqual(self.request.call_count, 1)

    def test_expected_key_mismatch_never_changes_item(self):
        result = zotero.remove_from_collection(dict(self.paper, zotero_key='DIFFERENT'))
        self.assertEqual(result['status'], 'pending')
        self.request.assert_not_called()

    def test_conflict_reloads_and_preserves_new_collection(self):
        self.request.side_effect = [self.row(['AI123456']),
            HTTPError('local', 412, 'changed', {}, None),
            self.row(['AI123456', 'NEWCOL01'], 8), (None, self.headers), self.row(['NEWCOL01'], 9)]
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'removed')
        self.assertEqual(self.request.call_args_list[3].args[2], {'version': 8, 'collections': ['NEWCOL01']})

    def test_conflicts_are_bounded(self):
        self.request.side_effect = [entry for _ in range(3) for entry in
            [self.row(['AI123456']), HTTPError('local', 409, 'changed', {}, None)]]
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'pending')
        self.assertEqual(self.request.call_count, 6)

    def test_expired_key_is_authorization_required(self):
        self.request.side_effect = [self.row(['AI123456']), HTTPError('local', 401, 'expired', {}, None)]
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'authorization_required')

    def test_restart_does_not_require_connector_session(self):
        with patch.object(zotero, '_sessions', side_effect=AssertionError('Session unavailable after restart')):
            self.request.side_effect = [self.row(['AI123456']), (None, self.headers), self.row([], 8)]
            self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'removed')

    def test_duplicate_collection_names_do_not_choose_arbitrarily(self):
        self.mocks[2].return_value *= 2
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'pending')
        self.request.assert_not_called()

    def test_missing_server_id_reports_unsupported(self):
        self.headers.clear()
        self.request.return_value = self.row(['AI123456'])
        self.assertEqual(zotero.remove_from_collection(self.paper)['status'], 'unsupported')
        self.assertEqual(self.request.call_count, 1)

    def test_refavorite_adds_collection_and_retains_others(self):
        self.request.side_effect = [self.row(['OTHER001']), (None, self.headers),
                                    self.row(['OTHER001', 'AI123456'], 8)]
        self.assertEqual(zotero.add_to_collection(self.paper)['status'], 'saved')
        self.assertEqual(self.request.call_args_list[1].args[2],
                         {'version': 7, 'collections': ['OTHER001', 'AI123456']})

    def test_refavorite_is_idempotent(self):
        self.request.return_value = self.row(['AI123456', 'OTHER001'])
        self.assertEqual(zotero.add_to_collection(self.paper)['status'], 'saved')
        self.assertEqual(self.request.call_count, 1)

    def test_explicit_authorize_persists_private_token_and_returns_metadata(self):
        self.request.side_effect = [('Nothing to see here.', self.headers),
                                    ({'key': 'secret', 'remember': True}, self.headers)]
        result = zotero.authorize_local_writes()
        self.assertEqual(result['status'], 'authorized')
        self.assertTrue(result['persistent'])
        self.assertEqual(stat.S_IMODE(self.auth.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.auth.read_text()), {'server_id': 'server-one', 'key': 'secret'})
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(self.request.call_args_list[1].args,
            ('/api/local/authorize', 'POST', {'appName': 'Paper Inbox'}, {'Zotero-Server-ID': 'server-one'}))


class ZoteroTrashTests(unittest.TestCase):
    setUp = ZoteroCollectionTests.setUp

    def row(self, deleted=False, version=7, title='A paper', doi=''):
        return {'key': 'PAPER123', 'version': version, 'data': {
            'title': title, 'DOI': doi, 'deleted': int(deleted),
            'collections': ['AI123456', 'OTHER001'], 'tags': [{'tag': 'my-tag'}]}}, self.headers

    def test_trash_only_changes_deleted_field(self):
        self.request.side_effect = [self.row(), (None, self.headers), self.row(True, 8)]
        result = zotero.trash_paper(dict(self.paper, zotero_key='PAPER123'))
        self.assertEqual(result['status'], 'trashed')
        self.assertEqual(self.request.call_args_list[1].args,
            ('/api/users/0/items/PAPER123', 'PATCH', {'version': 7, 'deleted': 1},
             {'Zotero-API-Key': 'test-key', 'Zotero-Server-ID': 'server-one'}))
        self.mocks[1].assert_not_called()
        self.assertNotIn('test-key', json.dumps(result))

    def test_restore_uses_same_key_and_changes_deleted_only(self):
        self.request.side_effect = [self.row(True), (None, self.headers), self.row(False, 8)]
        result = zotero.restore_paper(dict(self.paper, zotero_key='PAPER123'))
        self.assertEqual(result, {'status': 'restored', 'key': 'PAPER123',
                                'message': '已从 Zotero 回收站恢复原文献'})
        self.assertEqual(self.request.call_args_list[1].args[2], {'version': 7, 'deleted': 0})

    def test_trash_without_known_key_resolves_existing_once(self):
        self.request.return_value = self.row(True)
        self.assertEqual(zotero.trash_paper(self.paper)['status'], 'trashed')
        self.mocks[1].assert_called_once_with(self.paper)

    def test_restore_requires_saved_key_never_guesses(self):
        self.assertEqual(zotero.restore_paper(self.paper)['status'], 'not_found')
        self.request.assert_not_called()
        self.mocks[1].assert_not_called()

    def test_trash_already_deleted_is_idempotent_without_permission(self):
        self.auth.unlink()
        self.request.return_value = self.row(True)
        self.assertEqual(zotero.trash_paper(dict(self.paper, zotero_key='PAPER123'))['status'], 'trashed')
        self.assertEqual(self.request.call_count, 1)

    def test_wrong_identity_refuses_trash(self):
        self.request.return_value = self.row(title='Another paper')
        self.assertEqual(zotero.trash_paper(dict(self.paper, zotero_key='PAPER123'))['status'], 'pending')
        self.assertEqual(self.request.call_count, 1)

    def test_mismatched_doi_refuses_even_matching_title(self):
        self.request.return_value = self.row(doi='10.1234/different')
        result = zotero.trash_paper(dict(self.paper, zotero_key='PAPER123', doi='10.1234/expected'))
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(self.request.call_count, 1)

    def test_missing_key_after_permanent_external_removal_does_not_import(self):
        self.request.side_effect = HTTPError('local', 404, 'gone', {}, None)
        self.assertEqual(zotero.restore_paper(dict(self.paper, zotero_key='PAPER123'))['status'], 'not_found')
        self.assertEqual(self.request.call_count, 1)
        self.mocks[1].assert_not_called()

    def test_conflict_reloads_current_version(self):
        self.request.side_effect = [self.row(), HTTPError('local', 412, 'changed', {}, None),
            self.row(False, 8), (None, self.headers), self.row(True, 9)]
        self.assertEqual(zotero.trash_paper(dict(self.paper, zotero_key='PAPER123'))['status'], 'trashed')
        self.assertEqual(self.request.call_args_list[3].args[2], {'version': 8, 'deleted': 1})

    def test_wrong_server_never_receives_key(self):
        self.headers['Zotero-Server-ID'] = 'different'
        self.request.return_value = self.row()
        self.assertEqual(zotero.trash_paper(dict(self.paper, zotero_key='PAPER123'))['status'], 'authorization_required')
        self.assertEqual(self.request.call_count, 1)

    def test_invalid_key_refuses_path_injection(self):
        self.assertEqual(zotero.trash_paper(dict(self.paper, zotero_key='../items'))['status'], 'pending')
        self.request.assert_not_called()

    def test_known_key_find_includes_trashed_item(self):
        row, _ = self.row(True)
        self.mocks[2].side_effect = [row, []]
        # Bypass only the test's find_existing stub to exercise the real entry.
        self.patches[1].stop()
        found = zotero.find_existing(dict(self.paper, zotero_key='PAPER123'))
        self.assertEqual(found['key'], 'PAPER123')
        self.assertTrue(found['deleted'])
        self.assertEqual(self.mocks[2].call_args_list[0].args,
                         ('/api/users/0/items/PAPER123',))


if __name__ == '__main__':
    unittest.main()
