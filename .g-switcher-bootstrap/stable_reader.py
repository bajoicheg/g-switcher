"""Bounded immutable snapshot reads under concurrent legitimate Git CAS updates."""
import base64
import json


def read_document(api, ref, *, attempts=12):
    for _ in range(attempts):
        revision = api('git/ref/' + ref)['object']['sha']
        payload = api('contents/document.json?ref=' + revision)
        value = json.loads(base64.b64decode(payload['content']))
        if api('git/ref/' + ref)['object']['sha'] == revision:
            return revision, value
    raise RuntimeError('Coordination changed throughout bounded snapshot read')


def read_lease_document(api, *, attempts=12):
    for _ in range(attempts):
        revision = api('git/ref/heads/cdc/coordination')['object']['sha']
        payload = api('contents/lease.json?ref=' + revision)
        value = json.loads(base64.b64decode(payload['content']))
        if api('git/ref/heads/cdc/coordination')['object']['sha'] == revision:
            return revision, value
    raise RuntimeError('Lease changed throughout bounded snapshot read')
