"""Portable real-Git equivalence and bounded cold-history transport checks."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from git_document_store import GitDocumentStore, MAX_BYTES, canonical
from git_remote_identity import remote_identity
import unknown_recovery as native


class DocumentHistoryBatchTests(unittest.TestCase):
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

    def test_cold_history_uses_bounded_batches_and_matches_individual_reads(self):
        revisions = []
        for number in range(35):
            revisions.append(self.commit(canonical({'n':number, 'text':'über\n'}).encode(),
                                         parent=revisions[-1] if revisions else None))
        self.git('update-ref', self.store.ref, revisions[-1])
        expected = [(rev, self.store._read_document_object(rev)) for rev in revisions]
        with patch('subprocess.run', wraps=subprocess.run) as run:
            actual = native._history(self.store)
        self.assertEqual(actual, expected)
        # Includes fresh endpoint/fetch/head/ancestry checks; previously 132 calls in this fixture.
        self.assertLess(run.call_count, 85)

    def test_batch_preserves_document_rejections(self):
        invalid = [b'{"a":1,"a":1}\n', b'{ "a": 1 }\n', b'[]\n', b'{"x":NaN}\n',
                   b'not json\n', b'{"x":"\xff"}\n',
                   json.dumps({'x':'x'*MAX_BYTES}).encode()]
        for payload in invalid:
            with self.subTest(payload=payload[:30]):
                rev = self.commit(payload)
                with self.assertRaises((ValueError, UnicodeError)):
                    list(self.store._read_document_objects([rev]))
        extra = self.commit(b'{}\n', extra=True)
        with self.assertRaises(ValueError):
            list(self.store._read_document_objects([extra]))

    def test_valid_head_cannot_hide_invalid_original_document(self):
        for payload, extra in [(b'{"a":1,"a":1}\n', False), (b'{}\n', True)]:
            with self.subTest(extra=extra):
                original = self.commit(payload, extra=extra)
                current = self.commit(b'{"valid":"current"}\n', parent=original)
                self.git('update-ref', self.store.ref, current)
                with self.assertRaises(ValueError):
                    native._history(self.store)

    def test_batch_order_detachment_and_legacy_newline_normalization(self):
        first = self.commit(b'{"nested":["original"]}\n\n')
        second = self.commit(b'{"n":2}')
        result = list(self.store._read_document_objects([first, second, first]))
        self.assertEqual(result, [self.store._read_document_object(r) for r in [first, second, first]])
        result[0]['nested'].append('changed')
        self.assertEqual(result[2], {'nested':['original']})

    def test_batch_reads_genuine_commit_and_blob_despite_replacements(self):
        original = self.commit(b'{"value":"original"}\n')
        replacement = self.commit(b'{"value":"counterfeit"}\n')
        self.git('replace', original, replacement)
        original_blob = self.git('rev-parse', replacement + ':document.json')
        # A replacement on a directly requested blob must also be ignored.
        genuine_blob = self.git('hash-object', '-w', '--stdin', data=b'{"value":"original"}\n')
        self.git('replace', genuine_blob, original_blob)
        self.assertEqual(list(self.store._read_document_objects([original])), [{'value':'original'}])

    def test_sha256_tree_entries_are_read_without_sha1_assumptions(self):
        other = self.repo / 'sha256'
        other.mkdir()
        self.repo = other
        self.git('init', '--object-format=sha256', '.')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('remote', 'add', 'origin', str(other))
        store = GitDocumentStore(other, 'origin', self.store.ref, remote_identity(other, 'origin'))
        revision = self.commit(b'{"value":"sha256"}\n')
        self.assertEqual(len(revision), 64)
        self.assertEqual(list(store._read_document_objects([revision])), [{'value':'sha256'}])

    def test_batch_rejects_changed_truncated_and_extra_protocol_bytes(self):
        from types import SimpleNamespace
        oid = '1' * 40
        header = (oid + ' blob 3').encode()
        for raw in [header + b'\n{}', header + b'\n{}\n\nextra',
                    (oid + ' tree 3').encode() + b'\n{}\n\n']:
            with self.subTest(raw=raw), patch('subprocess.run', side_effect=[
                    SimpleNamespace(returncode=0, stdout=header + b'\n'),
                    SimpleNamespace(returncode=0, stdout=raw)]):
                with self.assertRaises(ValueError):
                    self.store._batch_objects([oid], 'blob', MAX_BYTES)

    def test_missing_and_noncommit_revisions_fail(self):
        blob = self.git('hash-object', '-w', '--stdin', data=b'{}\n')
        for revision in ['0'*40, blob, 'HEAD:document.json', 'bad\nrequest']:
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                list(self.store._read_document_objects([revision]))


if __name__ == '__main__':
    unittest.main()
