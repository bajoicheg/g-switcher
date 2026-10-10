"""Shared metadata contract; release-specific guidance tests cover behavior."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def test_version_manifest_and_core_are_consistent(self):
        version = (ROOT / "VERSION").read_text().strip()
        # Strongest version floor formerly repeated in guidance tests.
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (2, 11, 3))
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["version"], version)
        self.assertIn("v" + version, (ROOT / "SKILL.md").read_text())


if __name__ == "__main__":
    unittest.main()

