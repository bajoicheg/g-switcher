"""Authenticate one known terminal pre-compute failure; resolve its preserved claim."""
import base64
import hashlib
import io
import zipfile
from github_api import api, REPO
from admission import BASE, RESULT


def logs_text(job_id):
    data = api('actions/jobs/' + str(job_id) + '/logs', binary=True)
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            data = b'\n'.join(z.read(n) for n in z.namelist() if not n.endswith('/'))
    return data.decode('utf-8-sig', errors='replace')


def reconcile(repo, lease_store, handle, pinned, at, document_store, leasev2):
    prior = pinned['prior_failed_validation']
    store = document_store(repo, 'origin', prior['operation_ref'], pinned['coordination_store_id'],
                            protected_refs=['refs/heads/release/2.0.1','refs/heads/cdc/coordination'])
    revision, document = store.read()
    lease_revision, lease = lease_store.read()
    guard = lease['external_guard']
    assert guard == pinned['prior_external_guard']
    assert document['intent'] == guard['intent']
    assert document['submission_claim'] == guard['submission_claim']
    assert document['child_admission'] == prior['child_admission']
    assert document['windows_head'] == prior['windows_head']
    child = api('actions/runs/' + str(prior['run_id']) + '/attempts/1')
    assert child['id'] == prior['run_id'] and child['run_attempt'] == 1
    assert child['head_sha'] == prior['windows_head']
    assert child['display_title'] == 'Word diagnostic ' + guard['intent']['attempt_id']
    assert child['status'] == 'completed' and child['conclusion'] == 'failure'
    jobs = api('actions/runs/' + str(child['id']) + '/attempts/1/jobs?per_page=100')
    assert jobs['total_count'] == 1
    job = jobs['jobs'][0]
    assert job['id'] == prior['job_id'] and job['status'] == 'completed' and job['conclusion'] == 'failure'
    steps = {s['name']:s for s in job['steps']}
    assert steps['Checkout exact source base']['conclusion'] == 'success'
    assert steps['Admit exact one-use child and load verified bundle']['conclusion'] == 'failure'
    product_names = [s['name'] for s in pinned['windows_contract']['steps']]
    assert len(product_names) == 26 and all(steps[n]['conclusion'] == 'skipped' for n in product_names)
    source = api('contents/.g-switcher-bootstrap/windows_bundle_gate.py?ref=' + prior['windows_head'])
    assert hashlib.sha256(base64.b64decode(source['content'])).hexdigest() == prior['gate_sha256']
    logs = logs_text(job['id'])
    assert 'line 45, in read_lease' in logs and 'AssertionError' in logs
    assert "assert api('git/ref/heads/cdc/coordination')['object']['sha'] == ref" in logs
    assert 'WORD_BUNDLE_GATE_PASS' not in logs
    assert guard['intent']['binding']['candidate_sha'] == RESULT
    assert guard['intent']['source_ref'] == 'refs/heads/release/2.0.1'
    task = {'task_id':str(child['id'])+':1','task_url':child['html_url'],
            'operation_key':guard['operation_key'],'attempt_id':guard['intent']['attempt_id'],
            'binding':guard['intent']['binding'],'state':'terminal','conclusion':'setup_failed',
            'evidence_refs':[child['html_url'],'https://github.com/'+REPO+'/actions/runs/'+str(child['id'])+'/job/'+str(job['id'])]}
    observation = {'schema':'operation-observation/v1','operation_key':guard['operation_key'],
                   'observed_at_utc':at(),'lookup_complete':True,'tasks':[task]}
    document.update(state='terminal_setup_failed_before_candidate_admission',terminal_observation=observation,
        terminal_proof={'run':child,'job':job,'all_26_product_steps_skipped':True,
                        'audited_gate_sha256':prior['gate_sha256'],'candidate_loaded':False,
                        'candidate_validation_succeeded':False,'requested_binding_only':True})
    revision=store.compare_and_swap(revision,document)
    assert store.read()==(revision,document)
    lease_revision,lease=lease_store.read()
    assert lease['external_guard']==guard
    assert api('git/ref/heads/release/2.0.1')['object']['sha']==BASE
    cleared=leasev2.clear_guard(lease,handle['owner_id'],handle['generation'],handle['invocation_id'],
                               at(),observation,'git:'+revision+':document.json')
    new_revision=lease_store.compare_and_swap(lease_revision,cleared)
    assert lease_store.read()==(new_revision,cleared) and cleared['external_guard'] is None
    assert any(x['grant_id']==guard['submission_claim']['grant_id'] for x in cleared['submission_resolutions'])
    return {'terminal_setup_failure':True,'prior_candidate_loaded':False,'claim_resolved':True,
            'evidence_reference':'git:'+revision+':document.json','lease_revision':new_revision}
