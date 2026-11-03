"""Provider-neutral facade over existing native CDC authority; never a scheduler.

Result records describe observed execution only. Native acceptance, integration,
lease release and publication retain their original independent gates.
"""
from __future__ import annotations
from datetime import datetime
import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path
import subprocess
import sys

from agent_contract import validate_task
from agent_cli_adapters import build_command, parse_events, validate_cli_variant, cli_configuration
from git_object_integrity import git_object_environment
from managed_executor_runtime import ManagedExecutorRuntime, LocalCommandBackend
from managed_executor_store import GitManagedExecutorStore
from project_budget_store import GitProjectBudgetStore

MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_DIFF_BYTES = 1024 * 1024


def _digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _git(root, *args, limit=MAX_DIFF_BYTES):
    # Git is deterministic; output and exit status are preserved for this local
    # observation. No credential-bearing remote operations occur here.
    proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                          env=git_object_environment(), timeout=20)
    if proc.returncode or len(proc.stdout) > limit:
        raise ValueError('local Git observation failed or exceeded evidence bound')
    return proc.stdout.decode('utf-8', errors='strict')


def _clean_review_snapshot(cwd):
    """Verify raw tracked bytes, modes and all untracked/ignored files.

    Git status alone trusts assume-unchanged/skip-worktree and is insufficient.
    v1 blocks submodules, unusual modes and snapshots exceeding 64 MiB.
    """
    if _git(cwd, 'status', '--porcelain', '--ignored', '--untracked-files=all').strip():
        return False
    flags = _git(cwd, 'ls-files', '-v', '-z').split('\0')
    if any(row and not row.startswith('H ') for row in flags):
        return False
    entries = _git(cwd, 'ls-tree', '-r', '-z', 'HEAD').split('\0')
    consumed = 0
    root = Path(cwd).resolve()
    for entry in entries:
        if not entry:
            continue
        header, path = entry.split('\t', 1)
        mode, kind, oid = header.split()
        if kind != 'blob' or mode not in {'100644','100755','120000'}:
            return False
        file = root / path
        if not file.parent.resolve().is_relative_to(root):
            return False
        info = file.lstat()
        if mode == '120000':
            if not stat.S_ISLNK(info.st_mode):
                return False
            raw = os.fsencode(os.readlink(file))
        else:
            if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_LOG_BYTES
                    or bool(info.st_mode & 0o111) != (mode == '100755')):
                return False
            raw = file.read_bytes()
        consumed += len(raw)
        if consumed > 64*1024*1024:
            return False
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if actual != oid:
            return False
    return True


def _json_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate evidence field')
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError('nonfinite evidence value')


def _review_verdict(message):
    try:
        value = json.loads(message, object_pairs_hook=_json_unique, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError):
        return {'verdict': 'blocked', 'findings': [], 'reason': 'invalid_review_json'}
    if (not isinstance(value, dict) or set(value) != {'verdict', 'findings'}
            or not isinstance(value['verdict'], str)
            or value['verdict'] not in {'approved', 'changes_requested', 'blocked'}
            or not isinstance(value['findings'], list)):
        return {'verdict': 'blocked', 'findings': [], 'reason': 'invalid_review_shape'}
    for finding in value['findings']:
        if (not isinstance(finding, dict) or set(finding) != {'path', 'line', 'severity', 'message'}
                or not isinstance(finding['path'], str) or not finding['path']
                or type(finding['line']) is not int or finding['line'] < 1
                or not isinstance(finding['severity'], str)
                or finding['severity'] not in {'critical', 'high', 'medium', 'low'}
                or not isinstance(finding['message'], str) or not finding['message'].strip()):
            return {'verdict': 'blocked', 'findings': [], 'reason': 'invalid_review_finding'}
    if ((value['verdict'] == 'approved' and value['findings'])
            or (value['verdict'] == 'changes_requested' and not value['findings'])):
        return {'verdict': 'blocked', 'findings': [], 'reason': 'contradictory_review'}
    return value


class AgentWorker:
    def __init__(self, runtime, contract, executable, *, project_id, repository, model_budget_binding,
                 cli_variant=None):
        if (type(runtime) is not ManagedExecutorRuntime
                or type(runtime.backend) is not LocalCommandBackend
                or type(runtime.store) is not GitManagedExecutorStore):
            raise ValueError('original native runtime/store/local backend required')
        self.runtime = runtime
        self.contract = validate_task(contract)
        self.executable = executable
        validate_cli_variant(self.contract['provider'], cli_variant)
        self.cli_variant = cli_variant
        self.cli_configuration_digest = _digest(cli_configuration(self.contract['provider'], executable, cli_variant))
        self.project_id, self.repository = project_id, repository
        self.model_budget_binding = copy.deepcopy(model_budget_binding)
        self.model_budget_binding_digest = _digest(self.model_budget_binding)
        self.plan_digest = _digest(runtime.plan)
        self.contract_digest = _digest(self.contract)
        self._bind()

    def _bind(self):
        c, plan = self.contract, self.runtime.plan
        if _digest(cli_configuration(c['provider'], self.executable, self.cli_variant)) != self.cli_configuration_digest:
            raise ValueError('immutable provider CLI configuration changed')
        if _digest(c) != self.contract_digest or _digest(plan) != self.plan_digest:
            raise ValueError('immutable contract or native plan changed')
        tasks = [t for t in plan['tasks'] if t['id'] == c['task_id']]
        if len(tasks) != 1:
            raise ValueError('task not registered in original native plan')
        task = tasks[0]
        expected_role = 'writer' if c['role'] == 'developer' else 'read_only'
        if (c['project_id'] != self.project_id or c['repository'] != self.repository
                or c['base_sha'] != plan['base_sha'] or task['role'] != expected_role
                or c['branch'] != task['branch'] or c['worktree'] != task['worktree']
                or c['allowed_files'] != task['write_paths'] or c['dependencies'] != task['dependencies']
                or c['limits']['timeout_seconds'] != task['max_runtime_seconds']
                or c['budget']['cost_units'] != task['max_cost_units']):
            raise ValueError('agent contract differs from admitted native task')
        if c['role'] == 'reviewer' and c['review_of']['head_sha'] != plan['base_sha']:
            raise ValueError('reviewer must inspect exact proposed head')
        return task

    def _command(self, attempt_id):
        self._bind()
        context = None
        if self.contract['role'] == 'reviewer':
            review = self.contract['review_of']
            base, head = review['base_sha'], review['head_sha']
            if _git(self.runtime.repo_root, 'merge-base', base, head).strip() != base:
                raise ValueError('review base must be ancestor of proposed head')
            context = _git(self.runtime.repo_root, 'diff', '--no-ext-diff', '--no-textconv', '--binary', base, head, '--')
        provider_argv = build_command(self.contract, self.executable, review_context=context,
                                      cli_variant=self.cli_variant)
        identity = self.runtime._identity(self.contract['task_id'], attempt_id)
        directory = self.runtime.journal.directory(identity)
        checks = self.contract['required_tests'] if self.contract['role'] == 'developer' else []
        return [sys.executable, '-B', str(Path(__file__).with_name('agent_check_runner.py').resolve()),
                '--evidence-dir', str(directory), '--tests-json', json.dumps(checks, separators=(',', ':')),
                '--', *provider_argv]

    def operation_key(self, attempt_id):
        self._bind()
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise ValueError('original attempt identity required')
        binding = {'contract': self.contract_digest, 'native_plan': self.plan_digest,
                   'model_budget_binding': self.model_budget_binding_digest, 'attempt_id': attempt_id}
        if self.cli_variant is not None:
            binding['cli_variant'] = self.cli_variant
        if self.contract['provider'] == 'kimi':
            binding['cli_configuration'] = self.cli_configuration_digest
        return _digest(binding)

    def start(self, expected_revision, attempt_id, *, reservation_token,
              model_budget_store, reservation_event):
        """Require original charged model reservation; native CAS grants the launch.

        The host constructs/authenticates the existing budget store registration.
        A budget observation or an envelope alone never grants native authority.
        """
        argv = self._command(attempt_id)
        if (type(model_budget_store) is not GitProjectBudgetStore
                or model_budget_store.binding != self.model_budget_binding
                or model_budget_store.store_id != self.runtime.plan['coordination_store_id']):
            raise ValueError('registered original model budget custody required')
        event = copy.deepcopy(reservation_event)
        receipt = model_budget_store.observe_event(event)
        ledger = receipt['ledger']
        if (model_budget_store.binding['repository'] != self.repository
                or not receipt['already_recorded'] or event['type'] != 'reserve'
                or event['kind'] != 'agent_start' or event['attempt_id'] != attempt_id
                or event['operation_key'] != self.operation_key(attempt_id)
                or event['scope'] != 'agent-task:' + self.contract_digest
                or reservation_token != event['event_id']
                or event['cost']['tokens'] != self.contract['budget']['tokens']
                or event['cost']['elapsed_seconds'] != self.contract['limits']['timeout_seconds']
                or any(e['type'] == 'outcome' and e['reservation_id'] == event['event_id'] for e in ledger['events'])):
            raise ValueError('original unclosed charged model reservation mismatch')
        _, state = self.runtime.store.read()
        current = next(t for t in state['tasks'] if t['id'] == self.contract['task_id'])
        if current['attempt_ids']:
            raise ValueError('v1 forbids retry; observe original attempt without replay')
        return self.runtime.start(expected_revision, self.contract['task_id'], attempt_id,
                                  reservation_token=reservation_token, argv=argv)

    def _request(self, attempt_id):
        request = self.runtime._request(self.contract['task_id'], attempt_id)
        if request is not None and request['argv'] != self._command(attempt_id):
            raise ValueError('original launch contract/provider/prompt substituted')
        return request

    def get_status(self, attempt_id):
        self._bind(); self._request(attempt_id)
        return self.runtime.observe(self.contract['task_id'], attempt_id)

    def cancel_execution(self, attempt_id):
        self._bind(); self._request(attempt_id)
        return self.runtime.cancel(self.contract['task_id'], attempt_id)

    def collect_result(self, attempt_id):
        observation = self.get_status(attempt_id)
        request = self._request(attempt_id)
        status = observation['status']
        directory = Path(request['journal_directory']) if request else None
        parsed = {'status':'unknown', 'session_id':None, 'usage':None,
                  'final_message':None, 'error':'provider_output_unavailable'}
        if directory is not None:
            path = directory / 'stdout.log'
            try:
                if path.stat().st_size > MAX_LOG_BYTES:
                    parsed['error'] = 'provider_output_exceeds_bound'
                else:
                    parsed = parse_events(self.contract['provider'], path.read_text(encoding='utf-8'),
                                          cli_variant=self.cli_variant)
            except (OSError, UnicodeError):
                pass
        if status == 'succeeded':
            status = parsed['status']
        review, commit = None, None
        if directory is not None and observation.get('quiescent'):
            cwd = Path(request['cwd'])
            try:
                commit = _git(cwd, 'rev-parse', 'HEAD').strip()
                if self.contract['role'] == 'reviewer':
                    if (commit != self.contract['review_of']['head_sha']
                            or not _clean_review_snapshot(cwd)):
                        review = {'verdict':'blocked','findings':[],'reason':'review_snapshot_modified'}
                    elif status == 'succeeded':
                        review = _review_verdict(parsed['final_message'])
                    else:
                        review = {'verdict':'blocked','findings':[],'reason':'review_execution_incomplete'}
            except (ValueError, UnicodeError, OSError):
                if self.contract['role'] == 'reviewer':
                    review = {'verdict':'blocked','findings':[],'reason':'review_snapshot_unavailable'}
        checks = []
        if directory is not None and observation.get('quiescent'):
            try:
                payload = (directory / 'checks.json').read_bytes()
                if len(payload) > MAX_LOG_BYTES:
                    raise ValueError('check receipt exceeds bound')
                check_receipt = json.loads(payload, object_pairs_hook=_json_unique, parse_constant=_invalid_constant)
                if (not isinstance(check_receipt, dict)
                        or check_receipt.get('schema') != 'cdc-agent-checks/v1'
                        or not isinstance(check_receipt.get('checks'), list)):
                    raise ValueError('invalid check receipt')
                checks = check_receipt['checks']
                expected = self.contract['required_tests'] if self.contract['role'] == 'developer' else []
                if status == 'succeeded' and (check_receipt.get('provider_exit_code') != 0
                        or type(check_receipt.get('provider_exit_code')) is not int
                        or check_receipt.get('status') != ('passed' if expected else 'not_run')
                        or check_receipt.get('error')):
                    raise ValueError('provider/check receipt contradicts success')
                for index, row in enumerate(checks):
                    if not isinstance(row, dict):
                        raise ValueError('invalid check entry')
                    for stream in ('stdout', 'stderr'):
                        expected_path = directory / ('check-' + str(index) + '.' + stream + '.log')
                        if row.get(stream) != str(expected_path) or expected_path.is_symlink() or not expected_path.is_file():
                            raise ValueError('check output reference changed or unavailable')
                    if status == 'succeeded' and (type(row.get('exit_code')) is not int
                            or not isinstance(row.get('started_at'), str)
                            or not isinstance(row.get('completed_at'), str) or row.get('error')):
                        raise ValueError('incomplete actual check observation')
                    for name in ('started_at','completed_at'):
                        if not isinstance(row.get(name), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', row[name]):
                            raise ValueError('check requires observed UTC timestamp')
                    started = datetime.fromisoformat(row['started_at'].replace('Z','+00:00'))
                    completed = datetime.fromisoformat(row['completed_at'].replace('Z','+00:00'))
                    if completed < started:
                        raise ValueError('check observation timestamp regresses')
                if ([row['argv'] for row in checks] != expected[:len(checks)]
                        or len(checks) > len(expected)
                        or (status == 'succeeded' and (len(checks) != len(expected)
                            or any(row['exit_code'] != 0 for row in checks)))):
                    raise ValueError('incomplete or substituted deterministic checks')
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                if status == 'succeeded':
                    status = 'unknown'
                    parsed['error'] = 'deterministic_check_evidence_unavailable'
        if review is not None and review['verdict'] == 'approved' and status != 'succeeded':
            review = {'verdict':'blocked','findings':[],'reason':'review_evidence_incomplete'}
        error = observation.get('failure') or parsed['error']
        if status == 'unknown' and not error:
            error = 'provider_terminal_evidence_missing'
        if status in {'running','starting','awaiting_release'}:
            error = None
        return {'schema':'cdc-agent-result/v1', 'task_id':self.contract['task_id'],
                'attempt_id':attempt_id, 'contract_digest':self.contract_digest,
                'provider':self.contract['provider'], 'model':self.contract['model'], 'cli_variant':self.cli_variant,
                'status':status, 'native_status':observation['status'],
                'started_at':observation.get('started_at_utc'), 'completed_at':observation.get('finished_at_utc'),
                'exit_code':observation.get('exit_code'), 'errors':None if not error else {'category':'execution','detail':error},
                'session_id':parsed['session_id'], 'usage':parsed['usage'],
                'observed_head_sha':commit,
                'commit_sha':commit if self.contract['role']=='developer' and commit != self.contract['base_sha'] else None,
                'pr_ref':None, 'review_of':copy.deepcopy(self.contract['review_of']),
                'test_evidence':checks, 'review':review, 'accepted':False,
                'checkpoint':{'journal_directory':str(directory) if directory else None,
                              'recovery':'observe_original_attempt_only','replay_allowed':False},
                'logs':{'stdout':str(directory/'stdout.log'),'stderr':str(directory/'stderr.log')} if directory else None}
