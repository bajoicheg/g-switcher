"""Typed, read-only observations of completed work; never a budget ledger."""
from __future__ import annotations

import math

PHASES = ('startup', 'implementation', 'validation', 'wait')
DELIVERY = ('delivered', 'escaped_defects')


def _fields(data, names, label):
    if not isinstance(data, dict) or set(data) != set(names):
        raise ValueError(f'{label} fields mismatch')


def _number(value, label, *, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{label} must be a finite nonnegative number')


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f'{label} must be nonempty unpadded text')


def _observation(data, label, *, integer=False):
    _fields(data, ('value', 'unknown_reason'), label)
    value, reason = data['value'], data['unknown_reason']
    if value is None:
        _text(reason, label + '.unknown_reason')
    else:
        _number(value, label + '.value', integer=integer)
        if reason is not None: raise ValueError(label + '.unknown_reason must be null when observed')
    return dict(data)


def measure(request):
    """Validate the observation and retain unknown values with their reasons."""
    _fields(request, ('schema', 'observation_ref', 'comparison_group', 'elapsed_seconds',
                      'tokens', 'budget_ref', 'phases', 'delivery'), 'operation')
    if request['schema'] != 'operation-observation/v1': raise ValueError('operation schema mismatch')
    _text(request['observation_ref'], 'observation_ref')
    _text(request['comparison_group'], 'comparison_group')
    _number(request['elapsed_seconds'], 'elapsed_seconds')
    tokens = request['tokens']
    _fields(tokens, ('value', 'provenance', 'source', 'basis'), 'tokens')
    provenance = tokens['provenance']
    if provenance == 'unknown':
        if any(tokens[k] is not None for k in ('value', 'source', 'basis')):
            raise ValueError('unknown tokens must not include a value or provenance')
    elif provenance in ('measured', 'estimated'):
        _number(tokens['value'], 'tokens.value', integer=True)
        _text(tokens['source'], 'tokens.source')
        if provenance == 'estimated': _text(tokens['basis'], 'tokens.basis')
        elif tokens['basis'] is not None: raise ValueError('measured tokens must not include an estimate basis')
    else:
        raise ValueError('invalid token provenance')
    if request['budget_ref'] is not None: _text(request['budget_ref'], 'budget_ref')
    _fields(request['phases'], PHASES, 'phases')
    _fields(request['delivery'], DELIVERY, 'delivery')
    phases = {key: _observation(request['phases'][key], key) for key in PHASES}
    delivery = {key: _observation(request['delivery'][key], key, integer=True) for key in DELIVERY}
    return {'schema': 'operation-measurement/v1', 'observation_ref': request['observation_ref'],
            'comparison_group': request['comparison_group'],
            'elapsed_seconds': request['elapsed_seconds'],
            'rounded_minutes': math.floor(request['elapsed_seconds'] / 60 + 0.5),
            'tokens': dict(tokens), 'budget_ref': request['budget_ref'],
            'phases': phases, 'delivery': delivery}


def render(request):
    """Return a compact Russian suffix for a completed operation."""
    report = measure(request)
    tokens = report['tokens']
    suffix = f"{report['rounded_minutes']} мин"
    if tokens['value'] is not None:
        prefix = '≈' if tokens['provenance'] == 'estimated' else ''
        suffix += f"; {prefix}{tokens['value']} токенов"
    return '(' + suffix + ')'


def _delta(before, after):
    return {'before': before, 'after': after,
            'delta': after - before if before is not None and after is not None else None}


def compare(before, after):
    """Compare a named work/window/environment group, without inferred gains."""
    first, second = measure(before), measure(after)
    if first['comparison_group'] != second['comparison_group']:
        raise ValueError('observations belong to different comparison groups')
    token_delta = _delta(first['tokens']['value'], second['tokens']['value'])
    if not first['tokens']['provenance'] == second['tokens']['provenance'] == 'measured':
        token_delta['delta'] = None
    token_delta['before_provenance'] = first['tokens']['provenance']
    token_delta['after_provenance'] = second['tokens']['provenance']
    return {'schema': 'operation-comparison/v1',
            'comparison_group': first['comparison_group'],
            'before_ref': first['observation_ref'], 'after_ref': second['observation_ref'],
            'elapsed_seconds': _delta(first['elapsed_seconds'], second['elapsed_seconds']),
            'tokens': token_delta,
            'phases': {key: _delta(first['phases'][key]['value'], second['phases'][key]['value'])
                       for key in PHASES},
            'delivery': {key: _delta(first['delivery'][key]['value'], second['delivery'][key]['value'])
                         for key in DELIVERY}}
