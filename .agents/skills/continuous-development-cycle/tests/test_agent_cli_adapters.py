"""Stateless provider boundary: no process or model starts in these tests."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_contract import validate_task
from agent_cli_adapters import build_command, parse_events


def task(provider='codex', role='developer'):
    value = {
        'schema': 'cdc-agent-task/v1', 'task_id': 'example-worker',
        'project_id': 'example', 'repository': 'example/project',
        'base_sha': 'a' * 40, 'branch': 'cdc/example-worker',
        'worktree': 'worktrees/example-worker', 'objective': 'Update src/example.py',
        'acceptance_criteria': ['Actual checks pass'], 'allowed_files': ['src/example.py'],
        'allowed_operations': ['read', 'edit'], 'provider': provider,
        'model': 'explicit-model', 'role': role, 'execution_profile': 'workspace-write',
        'security_classification': 'synthetic',
        'budget': {'agent_starts': 1, 'tokens': None, 'cost_units': 1},
        'limits': {'timeout_seconds': 60, 'retry_limit': 0}, 'dependencies': [],
        'required_tests': [['python3', '-B', 'test_example.py']],
        'review': {'required': True, 'provider': 'gemini' if provider == 'codex' else 'codex',
                   'max_iterations': 1}, 'artifacts': {'directory': 'artifacts/example'},
        'review_of': None,
    }
    if role == 'reviewer':
        value.update(execution_profile='read-only', allowed_operations=['read'], allowed_files=[],
                     branch=None, worktree=None, required_tests=[])
        value['review_of'] = {'base_sha': 'b' * 40, 'head_sha': 'a' * 40,
                              'developer_provider': value['review']['provider'],
                              'test_evidence': ['evidence:tests-passed']}
    return value


def stream(*events):
    return '\n'.join(json.dumps(event) for event in events) + '\n'


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(validate_task), 'the strict agent contract is not implemented')

    def test_valid_contract_is_detached_and_both_provider_directions_work(self):
        for provider in ('codex', 'gemini'):
            for role in ('developer', 'reviewer'):
                original = task(provider, role)
                validated = validate_task(original)
                validated['acceptance_criteria'].append('mutated')
                self.assertEqual(original['acceptance_criteria'], ['Actual checks pass'])

    def test_published_example_is_a_consumable_contract(self):
        path = Path(__file__).resolve().parents[1] / 'templates' / 'agent-task-v1.json'
        self.assertEqual(validate_task(json.loads(path.read_text()))['schema'], 'cdc-agent-task/v1')

    def test_published_developer_and_reviewer_examples_match_native_plans(self):
        from managed_executor_pool import validate_plan
        root = Path(__file__).resolve().parents[1] / 'templates'
        for role, name in [('developer', 'agent-task-v1.json'),
                           ('reviewer', 'agent-review-task-v1.json')]:
            with self.subTest(role=role):
                envelope = validate_task(json.loads((root / name).read_text()))
                plan = json.loads((root / ('agent-' + role + '-pool-v1.json')).read_text())
                validate_plan(plan)
                native = plan['tasks'][0]
                self.assertEqual(plan['base_sha'], envelope['base_sha'])
                self.assertEqual(native['id'], envelope['task_id'])
                self.assertEqual(native['role'], 'writer' if role == 'developer' else 'read_only')
                for source, target in [('branch','branch'), ('worktree','worktree'),
                                       ('write_paths','allowed_files'), ('dependencies','dependencies')]:
                    self.assertEqual(native[source], envelope[target])
                self.assertEqual(native['max_runtime_seconds'], envelope['limits']['timeout_seconds'])
                self.assertEqual(native['max_cost_units'], envelope['budget']['cost_units'])

    def test_extra_fields_at_every_object_boundary_are_rejected(self):
        for field in (None, 'budget', 'limits', 'review', 'artifacts', 'review_of'):
            value = task(role='reviewer')
            target = value if field is None else value[field]
            target['allow_network'] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_task(value)

    def test_missing_fields_and_wrong_types_are_rejected(self):
        for field, bad in [('schema', 'agent-task/v2'), ('base_sha', 'short'),
                           ('provider', 'other'), ('model', ''), ('role', 'owner'),
                           ('repository', 'https://github.com/a/b'), ('objective', ''),
                           ('acceptance_criteria', []), ('dependencies', ['example-worker']),
                           ('required_tests', [['python3', '']])]:
            value = task(); value[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_task(value)
        value = task(); del value['model']
        with self.assertRaises(ValueError): validate_task(value)

    def test_traversal_and_portable_aliases_are_rejected(self):
        for bad in ('../outside', '/tmp/outside', 'a/../b', 'a\\b', '.git/config',
                    'src//file', 'src/CON', 'src/name.', 'src/secret\x00'):
            for field in ('worktree', 'allowed_files', 'artifacts'):
                value = task()
                if field == 'allowed_files': value[field] = [bad]
                elif field == 'artifacts': value[field]['directory'] = bad
                else: value[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    validate_task(value)
        value = task(); value['allowed_files'] = ['src/One', 'SRC/one']
        with self.assertRaises(ValueError): validate_task(value)

    def test_protected_or_invalid_branches_are_rejected(self):
        for branch in ('main', 'refs/heads/main', 'master', 'release/current',
                       'releases/v1', 'refs/tags/v1', '../other', 'a..b', 'cdc/x.lock'):
            value = task(); value['branch'] = branch
            with self.subTest(branch=branch), self.assertRaises(ValueError): validate_task(value)

    def test_permissions_and_sensitive_classifications_fail_closed(self):
        for provider in ('codex', 'gemini'):
            for classification in ('private', 'sensitive', 'secret'):
                value = task(provider); value['security_classification'] = classification
                with self.assertRaises(ValueError): validate_task(value)
        for field, bad in [('allowed_operations', ['read', 'edit', 'push']),
                           ('allowed_operations', ['read', 'read']),
                           ('execution_profile', 'danger-full-access')]:
            value = task(); value[field] = bad
            with self.assertRaises(ValueError): validate_task(value)
        value = task(role='reviewer'); value['allowed_operations'].append('edit')
        with self.assertRaises(ValueError): validate_task(value)

    def test_original_single_start_and_no_retry_are_mandatory(self):
        for parent, field, bad in [('budget', 'agent_starts', 2), ('budget', 'agent_starts', True),
                                   ('budget', 'tokens', 0), ('budget', 'cost_units', 0),
                                   ('limits', 'timeout_seconds', False), ('limits', 'retry_limit', 1)]:
            value = task(); value[parent][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError): validate_task(value)

    def test_reviewer_cannot_silently_discard_required_test_commands(self):
        value = task(role='reviewer')
        value['required_tests'] = [['python3', '-c', "print('must actually run')"]]
        with self.assertRaisesRegex(ValueError, 'reviewer.*required_tests'):
            validate_task(value)

    def test_review_binds_independent_provider_and_exact_proposed_head(self):
        for role in ('developer', 'reviewer'):
            value = task(role=role); value['review']['provider'] = value['provider']
            with self.assertRaises(ValueError): validate_task(value)
        for field, bad in [('head_sha', 'c' * 40), ('base_sha', 'bad'),
                           ('developer_provider', 'codex'), ('test_evidence', [])]:
            value = task(role='reviewer'); value['review_of'][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError): validate_task(value)
        value = task(); value['review_of'] = task(role='reviewer')['review_of']
        with self.assertRaises(ValueError): validate_task(value)
        for field in ('branch', 'worktree'):
            value = task(role='reviewer'); value[field] = 'cdc/reviewer'
            with self.assertRaises(ValueError): validate_task(value)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(build_command), 'CLI adapters are not implemented')

    def test_codex_argv_uses_explicit_sandbox_model_and_entire_bound_contract(self):
        value = task(); argv = build_command(value, '/opt/provider/codex')
        self.assertEqual(argv[:7], ['/opt/provider/codex', 'exec', '--json', '--sandbox',
                                   'workspace-write', '--model', 'explicit-model'])
        self.assertEqual(json.loads(argv[-1].split('\n', 1)[1]), value)
        self.assertNotIn('--yolo', argv)
        self.assertNotIn('--full-auto', argv)
        self.assertNotIn('resume', argv)
        changed = task(); changed['budget']['cost_units'] = 2
        self.assertNotEqual(argv, build_command(changed, '/opt/provider/codex'))

    def test_bound_profiles_are_noninteractive_without_unrelated_user_config(self):
        self.assertIn('--ignore-user-config',build_command(task(),'codex'))
        self.assertIn('--skip-trust',build_command(task('gemini'),'gemini'))

    def test_gemini_uses_explicit_policy_and_review_profile(self):
        for role, approval in [('developer', 'auto_edit'), ('reviewer', 'plan')]:
            value = task('gemini', role)
            context = 'diff --git a/src/example.py b/src/example.py\n+proposed' if role == 'reviewer' else None
            argv = build_command(value, '/opt/provider/gemini', review_context=context)
            self.assertEqual(argv[:7], ['/opt/provider/gemini', '--output-format', 'stream-json',
                                       '--approval-mode', approval, '--model', 'explicit-model'])
            self.assertEqual(argv[7], '--skip-trust')
            self.assertEqual(argv[8], '-p')
            payload = json.loads(argv[-1].split('\n', 1)[1])
            if role == 'reviewer':
                self.assertEqual(payload, {'task': value, 'review_context': context})
            else:
                self.assertEqual(payload, value)
            self.assertNotIn('--yolo', argv)
        self.assertEqual(build_command(task(role='reviewer'), 'codex', review_context='diff')[4], 'read-only')

    def test_reviewer_requires_actual_diff_and_developer_cannot_inject_review_context(self):
        with self.assertRaises(ValueError): build_command(task(role='reviewer'), 'codex')
        with self.assertRaises(ValueError): build_command(task(), 'codex', review_context='diff')
        with self.assertRaises(ValueError): build_command(task(role='reviewer'), 'codex', review_context='')

    def test_oversize_prompt_is_rejected_before_native_claim(self):
        with self.assertRaises(ValueError):
            build_command(task(role='reviewer'), 'codex', review_context='x' * (96 * 1024))

    def test_malicious_executable_and_invalid_contract_cannot_build_command(self):
        for executable in ('', '--yolo', 'codex\x00hidden'):
            with self.assertRaises(ValueError): build_command(task(), executable)
        value = task(); value['provider'] = 'arbitrary'
        with self.assertRaises(ValueError): build_command(value, 'codex')


class EventTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(parse_events), 'provider event parser is not implemented')

    def test_codex_real_shapes_preserve_session_message_and_actual_usage(self):
        observed = parse_events('codex', stream(
            {'type': 'thread.started', 'thread_id': 'thread-actual'},
            {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'id': 'item-1', 'type': 'agent_message', 'text': 'Done'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 11, 'cached_input_tokens': 2, 'output_tokens': 3}}))
        self.assertEqual(observed, {'status': 'succeeded', 'session_id': 'thread-actual',
                         'usage': {'input_tokens': 11, 'cached_input_tokens': 2, 'output_tokens': 3},
                         'final_message': 'Done', 'error': None})

    def test_gemini_real_shapes_assemble_deltas_and_preserve_actual_stats(self):
        stats = {'input_tokens': 11, 'output_tokens': 3, 'total_tokens': 14,
                 'cached': 2, 'input': 9, 'duration_ms': 22, 'tool_calls': 0, 'models': {}}
        observed = parse_events('gemini', stream(
            {'type': 'init', 'session_id': 'gemini-actual', 'model': 'explicit-model'},
            {'type': 'message', 'role': 'user', 'content': 'ignored'},
            {'type': 'message', 'role': 'assistant', 'content': 'Do', 'delta': True},
            {'type': 'message', 'role': 'assistant', 'content': 'ne', 'delta': True},
            {'type': 'result', 'status': 'success', 'stats': stats}))
        self.assertEqual(observed, {'status': 'succeeded', 'session_id': 'gemini-actual',
                                   'usage': stats, 'final_message': 'Done', 'error': None})

    def test_success_terminal_without_session_or_final_message_stays_unknown(self):
        for provider, event in [('codex',{'type':'turn.completed'}),('gemini',{'type':'result','status':'success'})]:
            self.assertEqual(parse_events(provider,stream(event))['status'],'unknown')

    def test_missing_terminal_event_stays_unknown(self):
        for provider, event in [('codex', {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}}),
                                ('gemini', {'type': 'message', 'role': 'assistant', 'content': 'Done'})]:
            self.assertEqual(parse_events(provider, stream(event))['status'], 'unknown')
            self.assertIsNone(parse_events(provider, stream(event))['usage'])

    def test_gemini_final_message_excludes_pre_tool_narration(self):
        observed = parse_events('gemini', stream(
            {'type': 'message', 'role': 'assistant', 'content': 'Checking files', 'delta': True},
            {'type': 'tool_use', 'tool_id': 'actual-1', 'tool_name': 'read_file', 'parameters': {}},
            {'type': 'tool_result', 'tool_id': 'actual-1', 'status': 'success', 'output': 'actual'},
            {'type': 'message', 'role': 'assistant', 'content': '{"verdict":"approved","findings":[]}', 'delta': True},
            {'type': 'result', 'status': 'success'}))
        self.assertEqual(observed['final_message'], '{"verdict":"approved","findings":[]}')

    def test_errors_override_a_success_terminal(self):
        for provider, failure, success in [
            ('codex', {'type': 'error', 'message': 'provider disconnected'}, {'type': 'turn.completed'}),
            ('gemini', {'type': 'error', 'severity': 'error', 'message': 'quota'}, {'type': 'result', 'status': 'success'})]:
            observed = parse_events(provider, stream(failure, success))
            self.assertEqual(observed['status'], 'failed')
            self.assertIsNotNone(observed['error'])

    def test_terminal_failures_are_preserved_without_invented_usage(self):
        for provider, event in [('codex', {'type': 'turn.failed', 'error': {'message': 'unavailable'}}),
                                ('gemini', {'type': 'result', 'status': 'error', 'error': {'message': 'unavailable'}})]:
            observed = parse_events(provider, stream(event))
            self.assertEqual(observed['status'], 'failed')
            self.assertIsNone(observed['usage'])

    def test_malformed_or_ambiguous_streams_are_unknown_even_after_success(self):
        terminal = '{"type":"turn.completed"}\n'
        for text in ('', 'plain output', '[]\n', '{}\n', terminal + '{broken',
                     terminal + '{"type":"turn.completed"}\n',
                     '{"type":"turn.completed","type":"turn.failed"}\n',
                     '{"type":"turn.completed","usage":{"input_tokens":NaN}}\n',
                     '{"type":"turn.completed","usage":{"input_tokens":-1}}\n',
                     terminal + '{"type":"turn.started"}\n',
                     '{"type":"thread.started","thread_id":"a"}\n'
                     '{"type":"thread.started","thread_id":"b"}\n' + terminal):
            with self.subTest(text=text): self.assertEqual(parse_events('codex', text)['status'], 'unknown')
        self.assertEqual(parse_events('gemini', '{"type":"result","status":"READY"}\n')['status'], 'unknown')

    def test_unsupported_provider_is_rejected(self):
        with self.assertRaises(ValueError): parse_events('other', '')




class KimiAdapterTests(unittest.TestCase):
    def events(self):
        return [
            {'role': 'meta', 'type': 'system.version', 'version': '2.2.0'},
            {'role': 'assistant', 'content': 'Reading first.', 'tool_calls': [
                {'type': 'function', 'id': 'read-1', 'function': {
                    'name': 'Read', 'arguments': '{"file_path":"src/example.py"}'}}]},
            {'role': 'tool', 'tool_call_id': 'read-1', 'content': 'actual contents'},
            {'role': 'assistant', 'content': '{"verdict":"approved","findings":[]}'},
            {'role': 'meta', 'type': 'session.resume_hint', 'session_id': 'kimi-actual',
             'command': 'kimi -r kimi-actual', 'content': 'To resume this session: kimi -r kimi-actual'},
        ]

    def test_contract_accepts_all_distinct_provider_pairs(self):
        for provider in ('codex', 'gemini', 'kimi'):
            for opposite in ('codex', 'gemini', 'kimi'):
                for role in ('developer', 'reviewer'):
                    value = task(provider, role)
                    value['review']['provider'] = opposite
                    if value['review_of']:
                        value['review_of']['developer_provider'] = opposite
                    with self.subTest(provider=provider, opposite=opposite, role=role):
                        if provider == opposite:
                            with self.assertRaises(ValueError): validate_task(value)
                        else:
                            self.assertEqual(validate_task(value), value)

    def test_headless_command_binds_trusted_role_agent_and_complete_task(self):
        for role in ('developer', 'reviewer'):
            value = task('kimi', role)
            context = 'diff --git a/a b/a\n+actual' if role == 'reviewer' else None
            argv = build_command(value, '/opt/provider/kimi', review_context=context)
            self.assertEqual(argv[:5], ['/opt/provider/kimi', '--output-format', 'stream-json',
                                       '--model', 'explicit-model'])
            self.assertEqual(argv[5], '--agent-file')
            self.assertEqual(Path(argv[6]).name, 'kimi-' + role + '-v220.yaml')
            self.assertTrue(Path(argv[6]).is_file())
            self.assertEqual(argv[7], '-p')
            payload = json.loads(argv[-1].split('\n', 1)[1])
            self.assertEqual(payload, {'task': value, 'review_context': context} if context else value)
            self.assertTrue(set(argv).isdisjoint({'--yolo', '--auto', '--plan', '--continue', '--resume'}))

    def test_pinned_completed_turn_preserves_session_and_unknown_usage(self):
        self.assertEqual(parse_events('kimi', stream(*self.events())), {
            'status': 'succeeded', 'session_id': 'kimi-actual', 'usage': None,
            'final_message': '{"verdict":"approved","findings":[]}', 'error': None})

    def test_tool_only_assistant_and_empty_tool_output_are_supported(self):
        events = self.events()
        del events[1]['content']
        events[2]['content'] = ''
        self.assertEqual(parse_events('kimi', stream(*events))['status'], 'succeeded')

    def test_role_profiles_exclude_shell_delegation_and_reviewer_edits(self):
        import yaml
        root = Path(__file__).resolve().parents[1] / 'templates'
        for role, tools in [('developer', ['Read', 'Glob', 'Grep', 'Write', 'Edit']),
                            ('reviewer', ['Read', 'Glob', 'Grep'])]:
            text = (root / ('kimi-' + role + '-v220.yaml')).read_text()
            _, metadata, body = text.split('---', 2)
            profile = yaml.safe_load(metadata)
            self.assertEqual(profile['tools'], tools)
            self.assertEqual(profile['subagents'], [])
            self.assertTrue(profile['description'] and body.strip())

    def test_missing_wrong_or_duplicate_version_and_terminal_are_unknown(self):
        cases = [self.events()[1:], self.events()[:-1], self.events() + [self.events()[-1]],
                 [self.events()[0], *self.events()], self.events() + [self.events()[3]]]
        events = self.events(); events[0]['version'] = '2.2.1'; cases.append(events)
        events = self.events(); events[-1]['session_id'] = ''; cases.append(events)
        events = self.events(); events[3]['content'] = ''; cases.append(events)
        for events in cases:
            with self.subTest(events=events):
                self.assertEqual(parse_events('kimi', stream(*events))['status'], 'unknown')

    def test_tool_progress_pending_or_forged_tool_results_cannot_be_final_answer(self):
        cases = []
        events = self.events(); del events[3]; cases.append(events)
        events = self.events(); del events[2]; cases.append(events)
        events = self.events(); events[2]['tool_call_id'] = 'unrequested'; cases.append(events)
        events = self.events(); events[1]['tool_calls'] *= 2; cases.append(events)
        events = self.events(); events[1]['tool_calls'][0]['function']['arguments'] = 'bad'; cases.append(events)
        for events in cases:
            with self.subTest(events=events):
                self.assertEqual(parse_events('kimi', stream(*events))['status'], 'unknown')

    def test_retry_and_mixed_or_malformed_stream_cannot_succeed(self):
        events = self.events()
        retry = {'role': 'meta', 'type': 'turn.step.retrying', 'failed_attempt': 1,
                 'next_attempt': 2, 'max_attempts': 10, 'delay_ms': 1000,
                 'error_name': 'ExampleError', 'error_message': 'retry forbidden'}
        for text in (stream(events[0], retry, *events[1:]),
                     stream(*events) + '{broken',
                     stream(events[0], {'type': 'turn.completed'}, *events[1:]),
                     stream(*events).replace('"version": "2.2.0"',
                                            '"version": "2.2.0", "version": "2.2.0"'),
                     stream(*events).replace('"version": "2.2.0"',
                                            '"version": "2.2.0", "untrusted": NaN')):
            with self.subTest(text=text):
                self.assertNotEqual(parse_events('kimi', text)['status'], 'succeeded')


class AntigravityAdapterTests(unittest.TestCase):
    def command(self, value, **kwargs):
        try:
            return build_command(value, '/opt/provider/agy', cli_variant='antigravity-cli', **kwargs)
        except TypeError as error:
            self.fail('explicit host CLI variant is unavailable: '+str(error))

    def parse(self, text):
        try:
            return parse_events('gemini', text, cli_variant='antigravity-cli')
        except TypeError as error:
            self.fail('explicit variant event parser is unavailable: '+str(error))

    def test_noninteractive_argv_preserves_bound_prompt_and_role_permissions(self):
        for role, mode in [('developer','accept-edits'),('reviewer','plan')]:
            value=task('gemini',role)
            context='diff --git a/a b/a\n+synthetic' if role=='reviewer' else None
            argv=self.command(value,review_context=context)
            self.assertEqual(argv[:-1],['/opt/provider/agy','--output-format','stream-json',
                '--mode',mode,'--sandbox','--model','explicit-model','--disable-slash-commands',
                '--print-timeout','60s','-p'])
            payload=json.loads(argv[-1].split('\n',1)[1])
            self.assertEqual(payload,{'task':value,'review_context':context} if context else value)

    def test_variant_is_explicit_and_restricted_to_google_provider(self):
        original=build_command(task('gemini'),'/opt/provider/agy')
        self.assertIn('--approval-mode',original)
        for provider,variant in [('codex','antigravity-cli'),('gemini','autodetect'),('gemini',False)]:
            with self.subTest(provider=provider,variant=variant),self.assertRaises(ValueError):
                build_command(task(provider),'provider',cli_variant=variant)
            with self.subTest(provider=provider,variant=variant),self.assertRaises(ValueError):
                parse_events(provider,'',cli_variant=variant)

    def events(self, status='SUCCESS', **fields):
        result={'conversation_id':'conversation-actual','status':status,'response':'Final only','num_turns':1}
        result.update(fields)
        return [{'event':'init','conversation_id':'conversation-actual',
                 'init':{'cwd':'/synthetic/worktree','tools':[],'permission_mode':'request-review'}},
                {'event':'step_update','step_update':{'conversation_id':'conversation-actual',
                 'step_index':3,'state':'DONE','step_type':'agent_response','text_delta':'Progress',
                 'duration_seconds':6.28,'usage':{'input_tokens':3,'output_tokens':1}}},
                {'event':'result','result':result}]

    def test_terminal_response_is_authoritative_and_usage_is_observed_only(self):
        events=self.events(usage={'input_tokens':7,'output_tokens':2})
        observed=self.parse(stream(*events))
        self.assertEqual(observed,{'status':'succeeded','session_id':'conversation-actual',
            'usage':{'input_tokens':7,'output_tokens':2},'final_message':'Final only','error':None})
        self.assertIsNone(self.parse(stream(*self.events()))['usage'])
        self.assertEqual(parse_events('gemini',stream(*events))['status'],'unknown')

    def test_non_success_statuses_cannot_succeed(self):
        for status in ('ERROR','CANCELED','INTERRUPTED','INVALID','WAITING','RUNNING','success','NEW_STATUS'):
            with self.subTest(status=status):
                self.assertNotEqual(self.parse(stream(*self.events(status)))['status'],'succeeded')

    def test_missing_conflicting_identity_multiple_turns_and_trailing_events_are_unknown(self):
        malformed=[]
        events=self.events();malformed.append(events[1:])
        events=self.events();events[1]['step_update']['conversation_id']='other';malformed.append(events)
        events=self.events();events[-1]['result']['conversation_id']='other';malformed.append(events)
        events=self.events();events[1]['step_update']={};malformed.append(events)
        for turns in (0,2,True,'1'):
            malformed.append(self.events(num_turns=turns))
        events=self.events();malformed.append([events[0],events[0],*events[1:]])
        events=self.events();malformed.append([*events,events[-1]])
        events=self.events();malformed.append([*events,{'event':'step_update','step_update':{'conversation_id':'conversation-actual'}}])
        events=self.events();events[-1]['result']['response']='';malformed.append(events)
        for events in malformed:
            with self.subTest(events=events):
                self.assertEqual(self.parse(stream(*events))['status'],'unknown')

    def test_duplicate_keys_nonfinite_mixed_streams_and_bad_usage_are_unknown(self):
        for usage in ({'input_tokens':True},{'input_tokens':-1},{'input_tokens':1.5},'unknown'):
            self.assertEqual(self.parse(stream(*self.events(usage=usage)))['status'],'unknown')
        valid=stream(*self.events())
        for text in (valid+'not-json',valid+'{"type":"result","type":"result"}',
                     valid.replace('"num_turns": 1','"num_turns": NaN'),
                     valid.replace('"num_turns": 1','"num_turns": 1,"duration_seconds": 1e400'),
                     valid.replace('"num_turns": 1','"num_turns": 1,"num_turns": 1'),
                     stream({'type':'message','role':'assistant','content':'mixed'},*self.events())):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)['status'],'unknown')

    def test_terminal_error_overrides_success_and_step_usage_cannot_be_malformed(self):
        observed=self.parse(stream(*self.events(error='provider rejected request')))
        self.assertEqual(observed['status'],'failed')
        self.assertEqual(observed['error'],'provider rejected request')
        events=self.events();events[1]['step_update']['usage']={'input_tokens':False}
        self.assertEqual(self.parse(stream(*events))['status'],'unknown')
        events=self.events();events[-1]['result'].pop('num_turns')
        self.assertEqual(self.parse(stream(*events))['status'],'succeeded')


if __name__ == '__main__':
    unittest.main()
