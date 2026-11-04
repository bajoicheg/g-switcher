"""Stateless CLI argument/event adapters. Never starts processes or grants authority."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from agent_contract import PROVIDERS, validate_task


def validate_cli_variant(provider, cli_variant):
    if cli_variant is not None and (provider != 'gemini' or cli_variant != 'antigravity-cli'):
        raise ValueError('unsupported explicit provider CLI variant')


def cli_configuration(provider, executable, cli_variant):
    """Freeze Kimi role definitions as well as the original executable selection."""
    value = {'executable': executable, 'cli_variant': cli_variant}
    if provider == 'kimi':
        root = Path(__file__).resolve().parents[1] / 'templates'
        value['kimi_2_2_0_agents'] = {
            role: hashlib.sha256((root / ('kimi-' + role + '-v220.yaml')).read_bytes()).hexdigest()
            for role in ('developer', 'reviewer')}
    return value


def build_command(task, executable, *, review_context=None, cli_variant=None):
    """Bind the complete task and verified review diff into native argv evidence."""
    task = validate_task(task)
    validate_cli_variant(task['provider'], cli_variant)
    if (not isinstance(executable, str) or not executable.strip() or executable != executable.strip()
            or executable.startswith('-') or any(ord(char) < 32 or ord(char) == 127 for char in executable)):
        raise ValueError('explicit executable must be nonempty without controls')
    if task['role'] == 'reviewer':
        if not isinstance(review_context, str) or not review_context.strip() or '\0' in review_context:
            raise ValueError('reviewer requires verified diff context')
        if len(review_context.encode('utf-8')) > 1024 * 1024:
            raise ValueError('review context exceeds 1 MiB')
        payload = {'task': task, 'review_context': review_context}
        instructions = ('CDC REVIEW_ONLY. Review the exact supplied base/head diff and test evidence. '
                        'Read only; do not edit, commit, push, delegate, invoke CI, change authentication, '
                        'or acquire authority. Return only JSON exactly {"verdict":"approved"|'
                        '"changes_requested"|"blocked","findings":[{"path":string,"line":integer,'
                        '"severity":string,"message":string}]}. Missing evidence requires blocked.')
    else:
        if review_context is not None:
            raise ValueError('developer cannot receive review context')
        payload = task
        instructions = ('CDC DEVELOPMENT_ONLY. Follow the complete bound contract; edit only allowed_files, '
                        'run only required_tests, and preserve the exact source/branch/worktree assignment. '
                        'Do not commit, push, merge, release, delegate, invoke CI, change authentication, '
                        'acquire leases, or retry. Report actual evidence and unavailable observations.')
    if task['provider'] == 'kimi':
        # Native requests persist argv, including this first prompt line. A
        # reconstructed facade must reject changed agent bytes at the same path.
        agents = cli_configuration('kimi', executable, cli_variant)['kimi_2_2_0_agents']
        instructions += ' Kimi2.2.0 immutable role hashes: ' + json.dumps(agents, sort_keys=True, separators=(',', ':'))
    prompt = instructions + '\n' + json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                              ensure_ascii=False, allow_nan=False)
    # Linux limits one argument to roughly 128 KiB; reject before native claim.
    if len(prompt.encode('utf-8')) > 96 * 1024:
        raise ValueError('bound prompt exceeds the 96 KiB argv limit')
    if task['provider'] == 'codex':
        return [executable, 'exec', '--json', '--sandbox', task['execution_profile'],
                '--model', task['model'], '--ignore-user-config', prompt]
    if task['provider'] == 'kimi':
        agent = Path(__file__).resolve().parents[1] / 'templates' / ('kimi-' + task['role'] + '-v220.yaml')
        return [executable, '--output-format', 'stream-json', '--model', task['model'],
                '--agent-file', str(agent), '-p', prompt]
    if cli_variant == 'antigravity-cli':
        mode = 'plan' if task['role'] == 'reviewer' else 'accept-edits'
        return [executable, '--output-format', 'stream-json', '--mode', mode, '--sandbox',
                '--model', task['model'], '--disable-slash-commands', '--print-timeout',
                str(task['limits']['timeout_seconds']) + 's', '-p', prompt]
    approval = 'plan' if task['role'] == 'reviewer' else 'auto_edit'
    return [executable, '--output-format', 'stream-json', '--approval-mode', approval,
            '--model', task['model'], '--skip-trust', '-p', prompt]


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('nonfinite JSON number')


def _usage(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('usage must be an observed object or null')
    def check(item):
        if isinstance(item, dict):
            for child in item.values():
                check(child)
        elif type(item) is not int or item < 0:
            raise ValueError('usage counters must be nonnegative integers')
    check(value)
    return copy.deepcopy(value)


def _message(value):
    if not isinstance(value, str) or not value:
        raise ValueError('event message must be nonempty text')
    return value


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite JSON number')
    return number


def _antigravity_events(text):
    """Pinned Antigravity 1.3.5 single-prompt event protocol, never autodetected."""
    result = {'status': 'unknown', 'session_id': None, 'usage': None,
              'final_message': None, 'error': None}
    terminal = False
    try:
        if not isinstance(text, str):
            raise ValueError('event stream must be text')
        for line in text.splitlines():
            if not line.strip():
                continue
            event = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant,
                               parse_float=_finite_float)
            if (not isinstance(event, dict) or 'type' in event
                    or event.get('event') not in ('init', 'step_update', 'result')):
                raise ValueError('unsupported Antigravity event envelope')
            if terminal:
                raise ValueError('event follows the terminal provider event')
            kind = event['event']
            if kind == 'init':
                if result['session_id'] is not None:
                    raise ValueError('multiple conversation initializations')
                result['session_id'] = _message(event.get('conversation_id'))
                continue
            if result['session_id'] is None:
                raise ValueError('event precedes conversation initialization')
            payload = event.get(kind)
            if not isinstance(payload, dict) or payload.get('conversation_id') != result['session_id']:
                raise ValueError('conversation identity missing or changed')
            if kind == 'step_update':
                if 'usage' in payload:
                    _usage(payload['usage'])
                continue
            terminal = True
            status = payload.get('status')
            if status not in ('SUCCESS', 'ERROR', 'CANCELED', 'INTERRUPTED', 'INVALID', 'WAITING', 'RUNNING'):
                raise ValueError('unknown Antigravity result status')
            if 'num_turns' in payload and (type(payload['num_turns']) is not int or payload['num_turns'] != 1):
                raise ValueError('single-prompt result must contain exactly one turn')
            result['usage'] = _usage(payload.get('usage'))
            if payload.get('response') is not None:
                if not isinstance(payload['response'], str):
                    raise ValueError('terminal response must be text')
                result['final_message'] = payload['response']
            if payload.get('error') is not None:
                result['error'] = _message(payload['error'])
            if status == 'SUCCESS':
                if not result['final_message']:
                    raise ValueError('provider success missing final output')
                result['status'] = 'failed' if result['error'] else 'succeeded'
            elif status in ('ERROR', 'CANCELED', 'INTERRUPTED', 'INVALID'):
                result['status'] = 'failed'
                result['error'] = result['error'] or 'provider reported terminal ' + status
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        result.update(status='unknown', usage=None, error='malformed provider stream: ' + str(exc))
        return result


def _kimi_events(text):
    """Source-qualified Kimi Code2.2.0 print protocol; never execute resume hints.

    The last meta record is emitted only after the internal completed turn.
    Native exit/check/custody gates remain independently mandatory. This stream
    emits no usage counters; null is retained rather than estimated.
    """
    result = {'status': 'unknown', 'session_id': None, 'usage': None,
              'final_message': None, 'error': None}
    initialized = terminal = False
    pending, seen = set(), set()
    try:
        if not isinstance(text, str):
            raise ValueError('event stream must be text')
        for line in text.splitlines():
            if not line.strip():
                continue
            event = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant,
                               parse_float=_finite_float)
            if not isinstance(event, dict) or terminal:
                raise ValueError('invalid event or event follows terminal provider event')
            if not initialized:
                if event != {'role': 'meta', 'type': 'system.version', 'version': '2.2.0'}:
                    raise ValueError('pinned Kimi2.2.0 version must initialize stream')
                initialized = True
                continue
            role = event.get('role')
            if role == 'meta':
                if event.get('type') == 'turn.step.retrying':
                    raise ValueError('provider retry violates original no-retry contract')
                if event.get('type') != 'session.resume_hint':
                    raise ValueError('unsupported Kimi metadata')
                if pending or not result['final_message']:
                    raise ValueError('completion missing final answer or unresolved tool calls')
                result['session_id'] = _message(event.get('session_id'))
                _message(event.get('command'))
                _message(event.get('content'))
                terminal = True
                result['status'] = 'succeeded'
            elif role == 'assistant' and 'type' not in event:
                if pending:
                    raise ValueError('assistant precedes pending tool results')
                content, calls = event.get('content'), event.get('tool_calls')
                if content is not None:
                    _message(content)
                if calls is not None:
                    if not isinstance(calls, list) or not calls:
                        raise ValueError('tool calls must be a nonempty list')
                    for call in calls:
                        if not isinstance(call, dict) or call.get('type') != 'function':
                            raise ValueError('malformed tool call')
                        identity = _message(call.get('id'))
                        if identity in seen:
                            raise ValueError('duplicate tool call identity')
                        function = call.get('function')
                        if not isinstance(function, dict):
                            raise ValueError('malformed tool function')
                        _message(function.get('name'))
                        arguments = json.loads(_message(function.get('arguments')),
                            object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_finite_float)
                        if not isinstance(arguments, dict):
                            raise ValueError('tool arguments must be an object')
                        pending.add(identity)
                        seen.add(identity)
                elif content is None:
                    raise ValueError('assistant has no content or tool calls')
                # Narration that precedes tools cannot become the final review.
                result['final_message'] = content if calls is None else None
            elif role == 'tool' and 'type' not in event:
                identity = event.get('tool_call_id')
                if not isinstance(identity, str) or identity not in pending or not isinstance(event.get('content'), str):
                    raise ValueError('unexpected or malformed tool result')
                pending.remove(identity)
                result['final_message'] = None
            else:
                raise ValueError('unsupported or mixed Kimi event')
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        result.update(status='unknown', usage=None, error='malformed provider stream: ' + str(exc))
        return result


def parse_events(provider, text, *, cli_variant=None):
    """Normalize genuine JSONL evidence; process outcome is an additional native gate.

    Codex: thread.started / item.completed(agent_message) / turn.completed|failed.
    Gemini 0.64.0: init / message(assistant, content, delta) / result(success|error).
    A provider terminal event is required. Error evidence overrides success;
    malformed/ambiguous streams remain unknown even after an apparent success.
    """
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError('unsupported provider')
    validate_cli_variant(provider, cli_variant)
    if cli_variant == 'antigravity-cli':
        return _antigravity_events(text)
    if provider == 'kimi':
        return _kimi_events(text)
    result = {'status': 'unknown', 'session_id': None, 'usage': None,
              'final_message': None, 'error': None}
    terminal = None
    try:
        if not isinstance(text, str):
            raise ValueError('event stream must be text')
        for line in text.splitlines():
            if not line.strip():
                continue
            event = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
            if not isinstance(event, dict) or not isinstance(event.get('type'), str) or not event['type']:
                raise ValueError('event must be an object with a type')
            kind = event['type']
            if terminal is not None and kind != 'error':
                raise ValueError('event follows the terminal provider event')
            if kind == ('thread.started' if provider == 'codex' else 'init'):
                session = _message(event.get('thread_id' if provider == 'codex' else 'session_id'))
                if result['session_id'] is not None and result['session_id'] != session:
                    raise ValueError('session identity changed')
                result['session_id'] = session
            elif provider == 'codex' and kind == 'item.completed':
                item = event.get('item')
                if not isinstance(item, dict) or not isinstance(item.get('type'), str):
                    raise ValueError('completed item is malformed')
                if item['type'] == 'agent_message':
                    result['final_message'] = _message(item.get('text'))
                elif item['type'] == 'error':
                    result['error'] = _message(item.get('message'))
            elif provider == 'gemini' and kind == 'message':
                if event.get('role') not in ('user', 'assistant') or not isinstance(event.get('content'), str):
                    raise ValueError('Gemini message is malformed')
                if event.get('role') == 'assistant':
                    if 'delta' in event and type(event['delta']) is not bool:
                        raise ValueError('Gemini delta must be boolean')
                    content = event['content']
                    result['final_message'] = ((result['final_message'] or '') + content
                                               if event.get('delta') else content)
            elif provider == 'gemini' and kind in ('tool_use', 'tool_result'):
                # A new assistant response follows tool observations. Earlier
                # progress narration is not the final structured review answer.
                result['final_message'] = None
            elif kind == 'error':
                result['error'] = _message(event.get('message'))
            elif ((provider == 'codex' and kind in ('turn.completed', 'turn.failed'))
                  or (provider == 'gemini' and kind == 'result')):
                if terminal is not None:
                    raise ValueError('multiple terminal events')
                if provider == 'codex':
                    terminal = 'succeeded' if kind == 'turn.completed' else 'failed'
                    result['usage'] = _usage(event.get('usage'))
                else:
                    if event.get('status') not in ('success', 'error'):
                        raise ValueError('Gemini terminal status is unknown')
                    terminal = 'succeeded' if event['status'] == 'success' else 'failed'
                    result['usage'] = _usage(event.get('stats'))
                if event.get('error') is not None:
                    error = event['error']
                    if not isinstance(error, dict):
                        raise ValueError('terminal error must be an object')
                    result['error'] = _message(error.get('message'))
                if terminal == 'failed' and result['error'] is None:
                    result['error'] = 'provider reported terminal failure'
        if terminal is not None:
            result['status'] = 'failed' if result['error'] is not None else terminal
            if result['status'] == 'succeeded' and (not result['session_id'] or not result['final_message']):
                result.update(status='unknown', error='provider success missing session or final output')
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        result.update(status='unknown', usage=None, error='malformed provider stream: ' + str(exc))
        return result
