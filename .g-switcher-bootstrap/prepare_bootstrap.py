"""Encode observer-prepared admission using the unchanged pinned CDC serializer."""
import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parent / 'word-hang-task/cdc2121/scripts'))
from git_document_store import canonical

head = sys.argv[1]
assert re.fullmatch(r'[0-9a-f]{40}', head)
intent = json.loads((root / 'host-launch-intent.json').read_text())
def digest(name):
    return hashlib.sha256((root / name).read_bytes()).hexdigest()

document = {'schema': 'word-host-bootstrap-admission/v1', 'state': 'prepared', 'host_admission': None,
    'host_head': head, 'intent_sha256': digest('host-launch-intent.json'),
    'operation_key': intent['host_reservation']['operation_key'], 'source_base': intent['base'],
    'prior_generation': intent['prior_generation'], 'prior_release_revision': intent['prior_release_revision'],
    'budget_ledger': intent['budget_ledger'], 'spec_review_sha256': digest('host-launch-spec-a6.md'),
    'quality_review_sha256': digest('host-launch-quality-a6.md'),
    'product_spec_review_sha256': digest('spec-review.md'),
    'product_quality_review_sha256': digest('product-quality-review.md'), 'cdc_version': '2.12.1'}
encoded = canonical(document)
assert canonical(json.loads(encoded)) == encoded
(root / 'bootstrap-admission-a6.json').write_text(encoded, encoding='utf-8')
print('Canonical admission SHA256 ' + hashlib.sha256(encoded.encode()).hexdigest())
