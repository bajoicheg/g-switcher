from pathlib import Path
import tempfile
import unittest
from repository_hygiene import check_paths
from triage_publication import classify


class HygieneTests(unittest.TestCase):
    def test_private_material_names_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.env').write_text('placeholder')
            self.assertTrue(check_paths(root, ['.env']))

    def test_public_template_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.env.example').write_text('placeholder')
            self.assertFalse(check_paths(root, ['.env.example']))

    def test_symlink_is_not_dereferenced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'link').symlink_to('/etc/passwd')
            self.assertEqual(check_paths(root, ['link'])[0]['kind'], 'unreviewed-symlink')

    def test_only_exact_documented_shortcut_is_allowed(self):
        item = {'RuleID': 'generic-api-key', 'File': 'docs/FUNCTIONAL_SPEC.md', 'Secret': 'Ctrl+Shift+F12'}
        self.assertEqual(classify(item)['classification'], 'documented-hotkey')
        item['Secret'] = 'unrecognized-value'
        self.assertEqual(classify(item)['classification'], 'requires-review')
        item['File'] = 'src/config.rs'
        item['Secret'] = 'Ctrl+Shift+F12'
        self.assertEqual(classify(item)['classification'], 'requires-review')


if __name__ == '__main__':
    unittest.main()
