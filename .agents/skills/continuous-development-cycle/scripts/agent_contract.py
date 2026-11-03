"""Strict provider-neutral worker input. Validation grants no execution authority."""
from __future__ import annotations

import copy
import re

from parallel_task_planner import portable_path_key, validate_write_path

SCHEMA = 'cdc-agent-task/v1'
PROVIDERS = frozenset(('codex', 'gemini', 'kimi'))
FIELDS = frozenset((
    'schema', 'task_id', 'project_id', 'repository', 'base_sha', 'branch', 'worktree',
    'objective', 'acceptance_criteria', 'allowed_files', 'allowed_operations',
    'provider', 'model', 'role', 'execution_profile', 'security_classification',
    'budget', 'limits', 'dependencies', 'required_tests', 'review', 'artifacts', 'review_of',
))
SHA = re.compile(r'[0-9a-f]{40}')
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


def _fields(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(name + ' fields mismatch')


def _text(value, name, *, multiline=False):
    permitted = '\n\t' if multiline else ''
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or any((ord(char) < 32 and char not in permitted) or ord(char) == 127 for char in value)):
        raise ValueError(name + ' must be nonempty text without controls or padding')
    return value


def _texts(value, name, *, nonempty=False, multiline=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(name + ' must be a list' + (' with entries' if nonempty else ''))
    for entry in value:
        _text(entry, name + ' entry', multiline=multiline)
    if len(value) != len(set(value)):
        raise ValueError(name + ' contains duplicates')
    return value


def _path(value, name):
    _text(value, name)
    validate_write_path(value)
    if any(part.casefold() == '.git' for part in value.split('/')):
        raise ValueError(name + ' cannot name Git metadata')
    return value


def _sha(value, name):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError(name + ' requires a full lowercase SHA')


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(name + ' must be an integer >= ' + str(minimum))


def validate_task(value):
    """Return detached validated input; the original native admission remains required.

    v1 accepts only synthetic/public material, one admitted agent start and no
    retry. Paths are relative portable paths. Provider selection is separate from
    the existing native compute backend and never modifies its permissions.
    """
    _fields(value, FIELDS, 'agent task')
    if value['schema'] != SCHEMA:
        raise ValueError('agent task schema mismatch')
    for name in ('task_id', 'project_id', 'model'):
        _text(value[name], name)
    if not isinstance(value['repository'], str) or not REPOSITORY.fullmatch(value['repository']):
        raise ValueError('repository must be owner/name')
    if any(part in ('.', '..') for part in value['repository'].split('/')):
        raise ValueError('repository contains traversal')
    _sha(value['base_sha'], 'base_sha')
    if value['role'] == 'reviewer':
        if value['branch'] is not None or value['worktree'] is not None:
            raise ValueError('reviewer uses the native detached journal worktree, with null branch/worktree')
    else:
        branch = _text(value['branch'], 'branch')
        if branch.startswith('refs/') and not branch.startswith('refs/heads/'):
            raise ValueError('branch must name a heads ref')
        branch = branch.removeprefix('refs/heads/')
        _path(branch, 'branch')
        if (branch.split('/')[0].casefold() in {'main', 'master', 'release', 'releases', 'protected'}
                or '..' in branch or '@{' in branch or branch == '@'
                or any(char in branch for char in ' ~^:?*[\\')
                or any(part.startswith('.') or part.endswith('.lock') for part in branch.split('/'))):
            raise ValueError('branch is protected or invalid')
        _path(value['worktree'], 'worktree')
    _text(value['objective'], 'objective', multiline=True)
    _texts(value['acceptance_criteria'], 'acceptance_criteria', nonempty=True, multiline=True)
    files = _texts(value['allowed_files'], 'allowed_files')
    for path in files:
        _path(path, 'allowed file')
    keys = [portable_path_key(path) for path in files]
    if len(keys) != len(set(keys)):
        raise ValueError('allowed_files contains portable aliases')
    operations = _texts(value['allowed_operations'], 'allowed_operations', nonempty=True)
    if not set(operations) <= {'read', 'edit'}:
        raise ValueError('unsupported allowed operation')
    if not isinstance(value['provider'], str) or value['provider'] not in PROVIDERS:
        raise ValueError('unsupported model provider')
    if value['security_classification'] not in ('synthetic', 'public'):
        raise ValueError('v1 requires synthetic or public material')
    if value['role'] == 'developer':
        if value['execution_profile'] != 'workspace-write' or set(operations) != {'read', 'edit'} or not files:
            raise ValueError('developer requires scoped workspace-write read/edit profile')
        if value['review_of'] is not None:
            raise ValueError('developer cannot declare review_of')
    elif value['role'] == 'reviewer':
        if value['execution_profile'] != 'read-only' or operations != ['read'] or files:
            raise ValueError('reviewer requires read-only profile and no write claim')
        review_of = value['review_of']
        _fields(review_of, ('base_sha', 'head_sha', 'developer_provider', 'test_evidence'), 'review_of')
        _sha(review_of['base_sha'], 'review_of.base_sha')
        _sha(review_of['head_sha'], 'review_of.head_sha')
        if review_of['head_sha'] != value['base_sha']:
            raise ValueError('reviewer base must equal proposed head')
        if (not isinstance(review_of['developer_provider'], str) or review_of['developer_provider'] not in PROVIDERS
                or review_of['developer_provider'] == value['provider']):
            raise ValueError('review requires an independent provider')
        _texts(review_of['test_evidence'], 'review_of.test_evidence', nonempty=True)
    else:
        raise ValueError('unsupported agent role')
    _fields(value['budget'], ('agent_starts', 'tokens', 'cost_units'), 'budget')
    _integer(value['budget']['agent_starts'], 'agent_starts')
    if value['budget']['agent_starts'] != 1 or value['budget']['tokens'] is not None:
        raise ValueError('v1 requires one start and unknown token usage; null is not an allowance')
    _integer(value['budget']['cost_units'], 'cost_units', minimum=1)
    _fields(value['limits'], ('timeout_seconds', 'retry_limit'), 'limits')
    _integer(value['limits']['timeout_seconds'], 'timeout_seconds', minimum=1)
    _integer(value['limits']['retry_limit'], 'retry_limit')
    if value['limits']['retry_limit'] != 0:
        raise ValueError('v1 forbids automatic retry')
    _texts(value['dependencies'], 'dependencies')
    if value['task_id'] in value['dependencies']:
        raise ValueError('task cannot depend on itself')
    if not isinstance(value['required_tests'], list):
        raise ValueError('required_tests must contain argument arrays')
    if value['role'] == 'reviewer' and value['required_tests']:
        raise ValueError('reviewer required_tests must be empty; inspect developer test evidence')
    for argv in value['required_tests']:
        if not isinstance(argv, list) or not argv:
            raise ValueError('required test must be a nonempty argument array')
        for argument in argv:
            _text(argument, 'required test argument')
    _fields(value['review'], ('required', 'provider', 'max_iterations'), 'review')
    review = value['review']
    if (type(review['required']) is not bool or not isinstance(review['provider'], str)
            or review['provider'] not in PROVIDERS or review['provider'] == value['provider']):
        raise ValueError('review requires boolean required and opposite provider')
    _integer(review['max_iterations'], 'max_iterations')
    if review['max_iterations'] != 1:
        raise ValueError('v1 permits one review iteration')
    _fields(value['artifacts'], ('directory',), 'artifacts')
    _path(value['artifacts']['directory'], 'artifacts.directory')
    return copy.deepcopy(value)
