import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import validate_package


class LeanPackageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(validate_package, 'validate_lean_templates'),
                        'package must validate the executable lean entry templates')

    def test_packaged_templates_execute_through_real_composed_contracts(self):
        validate_package.validate_lean_templates(ROOT)

    def test_unknown_token_fixture_cannot_smuggle_a_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'templates', root / 'templates')
            fixture = root / 'templates/operation-observation.json'
            data = json.loads(fixture.read_text()); data['tokens']['value'] = 100
            fixture.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                validate_package.validate_lean_templates(root)

    def test_missing_mandatory_core_gate_cannot_turn_template_green(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'templates', root / 'templates')
            fixture = root / 'templates/development-assessment.json'
            data = json.loads(fixture.read_text())
            data['quality']['mandatory_check_ids'] = []
            fixture.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                validate_package.validate_lean_templates(root)


if __name__ == '__main__':
    unittest.main()
