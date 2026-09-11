import io
import json
import unittest
import zipfile
from publication_audit import scan_bytes, safe_findings

ORG = 'gra' + 'dient'

class AuditTests(unittest.TestCase):
    def test_corporate_address_detected_without_echoing_value(self):
        text = f'contact=user@{ORG}.ru'
        rows = scan_bytes(text.encode(), 'fixture.txt')
        self.assertIn('corporate-reference', {r['kind'] for r in rows})
        self.assertNotIn(text, json.dumps(rows))
        self.assertNotIn('user@', json.dumps(rows))

    def test_cyrillic_company_reference(self):
        value = ''.join(map(chr, [1043, 1088, 1072, 1076, 1080, 1077, 1085, 1090]))
        rows = scan_bytes(('ООО ' + value).encode(), 'notes.md')
        self.assertTrue(any(r['kind'] == 'corporate-reference' for r in rows))

    def test_benign_css_not_company(self):
        rows = scan_bytes(f'background: linear-{ORG}(red, blue);'.encode(), 'style.css')
        self.assertTrue(any(r['kind'] == 'lexical-reference' for r in rows))
        self.assertFalse(any(r['kind'] == 'corporate-reference' for r in rows))

    def test_utf16_corporate_metadata(self):
        rows = scan_bytes(f'CompanyName={ORG}.ru'.encode('utf-16le'), 'app.exe')
        self.assertTrue(any(r['kind'] == 'corporate-reference' for r in rows))

    def test_embedded_docx_metadata(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('docProps/app.xml', '<Company>' + ORG + '</Company>')
        rows = scan_bytes(data.getvalue(), 'document.docx')
        self.assertTrue(any(r['kind'] == 'corporate-reference' and 'docProps' in r['source'] for r in rows))

    def test_private_key_marker_is_redacted(self):
        marker = '-----BEGIN ' + 'PRIVATE KEY-----'
        rows = scan_bytes(marker.encode(), 'fixture.txt')
        self.assertTrue(any(r['kind'] == 'private-key-marker' for r in rows))
        self.assertNotIn(marker, json.dumps(rows))

    def test_sanitizes_gitleaks_metadata_and_values(self):
        rows = safe_findings([{'RuleID':'example', 'File':'src/app.rs', 'StartLine':1,
                              'Commit':'a'*40, 'Secret':'do-not-echo', 'Match':'do-not-echo',
                              'Author':'sensitive', 'Email':'person@private.test', 'Message':'private'}])
        result = json.dumps(rows)
        for bad in ['do-not-echo', 'sensitive', 'person@', 'private']:
            self.assertNotIn(bad, result)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['rule'], 'example')

if __name__ == '__main__':
    unittest.main()
