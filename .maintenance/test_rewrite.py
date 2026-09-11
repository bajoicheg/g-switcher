import unittest
import rewrite_history as m

class RewriteTests(unittest.TestCase):
    def fixture(self):
        return ('prefix\nfn parses_user_dictionary_without_recording_history() {\n'
                'let s = "Корпорация\\nCompany\\nКорпорация";\n'
                'assert_eq!(words, ["Корпорация", "Company"]);\n    }\nsuffix\n').encode()
    def test_replaces_only_audited_test(self):
        data = self.fixture()
        actual = m.sanitize_test(data)
        self.assertIn('"Пример\\nExample\\nПример"'.encode(), actual)
        self.assertIn('assert_eq!(words, ["Пример", "Example"]);'.encode(), actual)
        self.assertTrue(actual.startswith(b'prefix\n'))
        self.assertTrue(actual.endswith(b'suffix\n'))
    def test_unexpected_extra_occurrence_is_rejected(self):
        with self.assertRaises(ValueError):
            m.sanitize_test(self.fixture() + b'Company\n')
    def test_wrong_structure_is_rejected(self):
        with self.assertRaises(ValueError):
            m.sanitize_test(b'ordinary unrelated file')
    def test_branch_race_is_rejected(self):
        with self.assertRaises(ValueError):
            m.require_same_refs({'refs/heads/main':'a'}, {'refs/heads/main':'b'})
    def test_new_branch_is_rejected(self):
        with self.assertRaises(ValueError):
            m.require_same_refs({'refs/heads/main':'a'}, {'refs/heads/main':'a', 'refs/heads/other':'b'})
    def test_identical_refs_pass(self):
        m.require_same_refs({'refs/heads/main':'a'}, {'refs/heads/main':'a'})

if __name__ == '__main__': unittest.main()
