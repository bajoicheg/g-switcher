"""Installation witnesses must come from actual files, not cached version labels."""
import importlib
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class ActivePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'source'
        self.saved = Path(self.tmp.name) / 'saved'
        for name, data in {
            'VERSION': '2.10.3\n',
            'manifest.json': json.dumps({'name': 'continuous-development-cycle', 'version': '2.10.3'}),
            'SKILL.md': '# Continuous Development Cycle v2.10.3\nContinue until the whole scope is complete.\n',
            'agents/openai.yaml': 'version: 2.10.3\ninterface: {display_name: CDC}\n',
            'assets/icon.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>\n',
            'scripts/run.py': 'print("real runtime")\n',
        }.items():
            p = self.source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(data)
        (self.source / 'scripts/run.py').chmod(0o755)
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True)
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        self.tree = subprocess.check_output(['git', '-C', str(self.source), 'write-tree'], text=True).strip()
        shutil.copytree(self.source, self.saved, ignore=shutil.ignore_patterns('.git'))

    def verify(self, **kw):
        if importlib.util.find_spec('active_package') is None:
            self.fail('active package verification is not implemented')
        return importlib.import_module('active_package').verify(
            self.source, self.saved, expected_version='2.10.3',
            expected_package_tree=self.tree, **kw)

    def test_exact_saved_bytes_are_verified_against_independent_git_tree(self):
        result = self.verify()
        self.assertTrue(result['matched'], result)
        self.assertEqual(result['installed_tree'], self.tree)
        self.assertEqual(result['normalizations'], [])

    def test_changed_instructions_rejected_even_when_version_labels_agree(self):
        with (self.saved / 'SKILL.md').open('a') as f:
            f.write('Stop after one milestone.\n')
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_changed_runtime_script_rejected(self):
        (self.saved / 'scripts/run.py').write_text('print("wrong runtime")\n')
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_explicit_host_metadata_normalization_preserves_runtime_identity(self):
        (self.saved / 'agents/openai.yaml').write_text('version: 2.10.3\ninterface:\n  display_name: CDC\n')
        (self.saved / 'assets/icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>\n')
        (self.saved / 'scripts/run.py').chmod(0o644)
        result = self.verify(host_normalization=True)
        self.assertTrue(result['matched'], result)
        self.assertNotEqual(result['installed_tree'], self.tree)
        self.assertEqual({x['kind'] for x in result['normalizations']},
                         {'interface_yaml_format', 'host_icon', 'executable_mode'})
        self.assertFalse(self.verify()['matched'])

    def test_host_option_cannot_change_interface_policy(self):
        (self.saved / 'agents/openai.yaml').write_text('version: 2.10.3\ninterface: {display_name: CDC}\npolicy: {implicit_invocation: false}\n')
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_host_option_cannot_hide_extra_or_missing_runtime_files(self):
        (self.saved / 'scripts/injected.py').write_text('pass\n')
        self.assertFalse(self.verify(host_normalization=True)['matched'])
        (self.saved / 'scripts/injected.py').unlink()
        (self.saved / 'scripts/run.py').unlink()
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_changed_canonical_and_installed_bytes_cannot_replace_pinned_source(self):
        for root in (self.source, self.saved):
            (root / 'scripts/run.py').write_text('print("both changed")\n')
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_version_drift_cannot_be_hidden_in_one_label(self):
        (self.saved / 'VERSION').write_text('2.3.5\n')
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_symlink_runtime_file_is_rejected(self):
        (self.saved / 'scripts/run.py').unlink()
        (self.saved / 'scripts/run.py').symlink_to(self.source / 'scripts/run.py')
        self.assertFalse(self.verify(host_normalization=True)['matched'])

    def test_unpinned_python_cache_is_rejected(self):
        p = self.saved / 'scripts/__pycache__/run.cpython-311.pyc'
        p.parent.mkdir()
        p.write_bytes(b'generated cache')
        result = self.verify()
        self.assertFalse(result['matched'], result)
        self.assertIn('unexpected:scripts/__pycache__/run.cpython-311.pyc', result['errors'])

    def test_executable_unchecked_hash_cache_cannot_bypass_source_verification(self):
        target = self.saved / 'scripts/run.py'
        unpinned = Path(self.tmp.name) / 'unpinned.py'
        unpinned.write_text('print("unpinned runtime")\n')
        cache = Path(importlib.util.cache_from_source(str(target)))
        cache.parent.mkdir(exist_ok=True)
        py_compile.compile(str(unpinned), cfile=str(cache), dfile=str(target),
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
                           doraise=True)
        observed = subprocess.check_output([sys.executable, '-B', '-c', 'import run'],
                                          cwd=target.parent, text=True)
        self.assertEqual(observed.strip(), 'unpinned runtime')
        for host in (False, True):
            with self.subTest(host_normalization=host):
                result = self.verify(host_normalization=host)
                self.assertFalse(result['matched'], result)


if __name__ == '__main__':
    unittest.main()
