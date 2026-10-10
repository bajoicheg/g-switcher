"""Read-only execution strategy recommendations using the existing budget ledger."""
from __future__ import annotations

import budget
import quality_levels
from parallel_task_planner import validate_write_path, portable_path_key, overlaps


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(label + ' fields mismatch')


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(label + ' must be nonempty unpadded text')


def _path(value):
    _text(value, 'scope')
    validate_write_path(value)


def _overlap(left, right):
    return overlaps(left, right)


def _batch(tasks, assessments):
    compatible = [task for task in tasks if task['small_reversible'] and not task['urgent']
                  and assessments[task['id']]['effective_level'] != 'FULL'
                  and set(task['quality_assessment']['risk_categories']) <=
                  {'local_reversible', 'documentation', 'presentation'}]
    if len(compatible) < 2:
        return {'eligible': False, 'task_ids': [], 'effective_level': None,
                'mandatory_check_ids': [], 'reason': 'fewer than two compatible low-risk changes'}
    mandatory = list(dict.fromkeys(check for task in compatible
                                   for check in assessments[task['id']]['mandatory_check_ids']))
    return {'eligible': True, 'task_ids': [task['id'] for task in compatible],
            'effective_level': max((assessments[task['id']]['effective_level'] for task in compatible),
                                   key=quality_levels.LEVELS.get),
            'mandatory_check_ids': mandatory,
            'reason': 'one shared candidate and aggregate check; required gates retained'}


def evaluate(request):
    """Recommend only; simulated reservations never mutate the supplied ledger."""
    _fields(request, ('schema', 'tasks', 'ledger', 'agent_reservations'), 'strategy')
    if request['schema'] != 'execution-strategy/v1': raise ValueError('strategy schema mismatch')
    tasks = request['tasks']
    if not isinstance(tasks, list) or not tasks: raise ValueError('tasks must be a nonempty list')
    ids, scopes, assessments = set(), [], {}
    for task in tasks:
        _fields(task, ('id', 'scopes', 'depends_on', 'small_reversible', 'urgent',
                       'quality_assessment'), 'task')
        _text(task['id'], 'task.id')
        if task['id'] in ids: raise ValueError('duplicate task id')
        ids.add(task['id'])
        if not isinstance(task['scopes'], list) or not task['scopes']:
            raise ValueError('scopes must be a nonempty list')
        for path in task['scopes']: _path(path)
        if len({portable_path_key(path) for path in task['scopes']}) != len(task['scopes']):
            raise ValueError('duplicate portable scope')
        scopes.append(task['scopes'])
        for field in ('small_reversible', 'urgent'):
            if type(task[field]) is not bool: raise ValueError(field + ' must be boolean')
        assessments[task['id']] = quality_levels.evaluate(task['quality_assessment'])
    for task in tasks:
        dependencies = task['depends_on']
        if not isinstance(dependencies, list): raise ValueError('depends_on must be a list')
        for dependency in dependencies: _text(dependency, 'depends_on')
        if len(dependencies) != len(set(dependencies)) or not set(dependencies) <= ids or task['id'] in dependencies:
            raise ValueError('invalid task dependency')
    ledger = request['ledger']
    budget.validate_ledger(ledger)
    raw_reservations = request['agent_reservations']
    if not isinstance(raw_reservations, list): raise ValueError('agent_reservations must be a list')
    reservations = {}
    event_ids, bindings = set(), set()
    replay = False
    for item in raw_reservations:
        _fields(item, ('task_id', 'event'), 'agent reservation')
        task_id, event = item['task_id'], item['event']
        if task_id not in ids or task_id in reservations: raise ValueError('invalid reservation task id')
        if not isinstance(event, dict) or event.get('kind') != 'agent_start':
            raise ValueError('only agent_start reservations are accepted')
        decision = budget.decide(ledger, event)
        binding = tuple(event[key] for key in ('operation_key', 'attempt_id', 'kind'))
        if event['event_id'] in event_ids or binding in bindings:
            raise ValueError('each agent task requires a unique reservation')
        event_ids.add(event['event_id']); bindings.add(binding)
        replay |= decision['already_recorded']
        reservations[task_id] = event
    batch = _batch(tasks, assessments)
    common = {'schema': 'execution-strategy-result/v1', 'task_quality': assessments,
              'batch_candidate': batch, 'integrator': 'single',
              'authorizes_external_start': False, 'authorizes_product_write': False,
              'authorizes_release': False, 'agent_task_ids': []}
    if replay:
        return {**common, 'action': 'WAIT', 'reasons': ['reconcile recorded agent reservation before another start']}
    independent = all(not task['depends_on'] for task in tasks)
    independent &= all(not any(_overlap(a, b) for a in scopes[i] for b in scopes[j])
                       for i in range(len(scopes)) for j in range(i + 1, len(scopes)))
    if len(tasks) < 2 or not independent:
        return {**common, 'action': 'SINGLE', 'reasons': ['task scopes overlap or depend on each other']}
    if len(reservations) != len(tasks):
        return {**common, 'action': 'SINGLE', 'reasons': ['agent reservations missing']}
    simulated = ledger
    for task in tasks:
        event = reservations[task['id']]
        decision = budget.decide(simulated, event)
        if decision['already_recorded']:
            return {**common, 'action': 'WAIT', 'reasons': ['reconcile an existing agent reservation']}
        if not decision['allow_reservation']:
            return {**common, 'action': 'SINGLE', 'reasons': decision['reasons']}
        simulated = budget.apply_event(simulated, event)
    return {**common, 'action': 'PARALLEL', 'reasons': ['disjoint independent scopes and sequential budget admissions'],
            'agent_task_ids': [task['id'] for task in tasks]}
