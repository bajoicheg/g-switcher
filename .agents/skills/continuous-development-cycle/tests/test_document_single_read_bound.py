"""Focused real-Git single-document bounded-read regression tests.

Uses the supplied DocumentHistoryBatchTests fixture methods verbatim, without
inheriting its test methods. Existing transport tests remain unchanged.
"""
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from git_document_store import GitDocumentStore, MAX_BYTES, canonical
import git_document_store as document_store
from git_remote_identity import remote_identity


class DocumentSingleReadBoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = pathlib.Path(self.temp.name)
        self.git('init', '.')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('remote', 'add', 'origin', str(self.repo))
        self.store = GitDocumentStore(self.repo, 'origin', 'refs/heads/cdc/batch', remote_identity(self.repo, 'origin'))

    def git(self, *args, data=None):
        return subprocess.run(['git', '-C', str(self.repo), *args], input=data,
                              capture_output=True, check=True).stdout.decode().strip()

    def commit(self, payload, *, extra=False, parent=None, mode='100644'):
        blob = self.git('hash-object', '-w', '--stdin', data=payload)
        entries = f'{mode} blob {blob}\tdocument.json\n'
        if extra:
            entries += f'100644 blob {blob}\textra\n'
        tree = self.git('mktree', data=entries.encode())
        return self.git('commit-tree', tree, *(['-p', parent] if parent else []), data=b'fixture\n')

    def test_valid_reads_normalize_and_return_detached_documents(self):
        document = {'nested': {'items': [1, 'é']}}
        normalized = canonical(document).encode('utf-8')
        first = self.commit(normalized.rstrip(b'\n') + b'\r\n\r\n')
        current = self.commit(normalized.rstrip(b'\n') + b'\r\r', parent=first)
        self.git('update-ref', self.store.ref, current)
        revision, loaded = self.store.read()
        historical = self.store.read_revision(first)
        single = self.store._read_document_object(first)
        self.assertEqual(revision, current)
        self.assertEqual(loaded, document)
        self.assertEqual(historical, document)
        self.assertEqual(single, document)
        loaded['nested']['items'].append('current mutation')
        historical['nested']['items'].append('history mutation')
        self.assertEqual(single, document)
        self.assertEqual(self.store.read(), (current, document))
        self.assertEqual(self.store.read_revision(first), document)
        self.assertEqual(self.store._read_document_object(first), document)

    def test_oversized_current_and_history_stop_before_blob_body_request(self):
        payload = b'{"value":"' + b'x' * MAX_BYTES + b'"}\n'
        oversized = self.commit(payload)
        oversized_blob = self.git('rev-parse', oversized + ':document.json').encode('ascii')
        small = self.commit(b'{}\n', parent=oversized)
        real_run = subprocess.run
        real_send = document_store._ObjectPipe.send

        for channel in ('current', 'historical', 'single'):
            with self.subTest(channel=channel):
                self.git('update-ref', self.store.ref, oversized if channel == 'current' else small)
                requests = []

                def observe(args, *positional, **kwargs):
                    if 'cat-file' in args:
                        for option in ('--batch-check', '--batch'):
                            if option in args:
                                requests.append((option, kwargs.get('input', b'')))
                    return real_run(args, *positional, **kwargs)

                def observe_session(pipe, specifications, deadline):
                    option=next(value for value in ('--batch-check','--batch') if value in pipe.process.args)
                    requests.append((option, ('\n'.join(specifications)+'\n').encode('ascii')))
                    return real_send(pipe,specifications,deadline)

                with patch('git_document_store.subprocess.run', side_effect=observe), \
                        patch.object(document_store._ObjectPipe,'send',observe_session):
                    with self.assertRaises(ValueError):
                        if channel == 'current':
                            self.store.read()
                        elif channel == 'historical':
                            self.store.read_revision(oversized)
                        else:
                            self.store._read_document_object(oversized)
                checked = [request.splitlines() for option, request in requests if option == '--batch-check']
                bodies = [request.splitlines() for option, request in requests if option == '--batch']
                self.assertTrue(any(oversized_blob in request for request in checked))
                self.assertFalse(any(oversized_blob in request for request in bodies))
                self.assertTrue(bodies, 'small tree bodies should still be read')

    def test_invalid_documents_trees_and_intermediate_revision_are_denied(self):
        for payload in (b'{"x":1,"x":2}\n', b'[]\n', b'{"x":NaN}\n', b'{ "x":1}\n'):
            with self.subTest(payload=payload):
                revision = self.commit(payload)
                with self.assertRaises(ValueError):
                    self.store._read_document_object(revision)
                self.git('update-ref', self.store.ref, revision)
                with self.assertRaises(ValueError):
                    self.store.read()

        intermediate = self.commit(b'{}\n', extra=True)
        current = self.commit(b'{}\n', parent=intermediate)
        self.git('update-ref', self.store.ref, current)
        with self.assertRaises(ValueError):
            self.store.read_revision(intermediate)
        with self.assertRaises(ValueError):
            self.store._read_document_object(intermediate)

        empty_tree = self.git('mktree', data=b'')
        directory_tree = self.git('mktree', data=f'040000 tree {empty_tree}\tdocument.json\n'.encode())
        directory_commit = self.git('commit-tree', directory_tree, data=b'directory fixture\n')
        blob = self.git('hash-object', '-w', '--stdin', data=b'{}\n')
        for revision in (directory_commit, directory_tree, blob):
            with self.subTest(revision=revision):
                with self.assertRaises(ValueError):
                    self.store._read_document_object(revision)
        self.git('update-ref', self.store.ref, directory_commit)
        with self.assertRaises(ValueError):
            self.store.read()

    def test_endpoint_head_commit_kind_and_authoritative_ancestry_checks(self):
        ancestor = self.commit(b'{"version":1}\n')
        current = self.commit(b'{"version":2}\n', parent=ancestor)
        outsider = self.commit(b'{"version":3}\n')
        self.git('update-ref', self.store.ref, current)
        self.assertEqual(self.store.read_revision(ancestor), {'version': 1})
        with self.assertRaisesRegex(ValueError, 'authoritative document ancestry'):
            self.store.read_revision(outsider)
        blob = self.git('rev-parse', current + ':document.json')
        with self.assertRaisesRegex(ValueError, 'must be a commit'):
            self.store.read_revision(blob)

        with patch('git_document_store.remote_identity', return_value='sha256:' + 'f' * 64):
            with self.assertRaisesRegex(ValueError, 'identity drift'):
                self.store.read()
            with self.assertRaisesRegex(ValueError, 'identity drift'):
                self.store.read_revision(ancestor)

        real_remote_revision = self.store._remote_revision
        calls = []

        def move_head():
            calls.append(None)
            if len(calls) == 2:
                self.git('update-ref', self.store.ref, outsider)
            return real_remote_revision()

        with patch.object(self.store, '_remote_revision', side_effect=move_head):
            with self.assertRaisesRegex(ValueError, 'moved during read'):
                self.store.read()
        self.assertEqual(len(calls), 2)

        self.git('update-ref', self.store.ref, current)
        tree = self.git('rev-parse', current + '^{tree}')
        with patch.object(self.store, '_remote_revision', return_value=tree):
            with self.assertRaisesRegex(ValueError, 'must point to a commit'):
                self.store.read()


if __name__ == '__main__':
    unittest.main()
