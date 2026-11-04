#!/usr/bin/env python3
"""Run one provider and exact checks within the existing native process custody.

This wrapper does not schedule, retry, parse model output or grant acceptance.
The original LocalCommandBackend owns timeout, cancellation and descendants.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _argv(value):
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item or '\0' in item for item in value)):
        raise ValueError('each command must be a nonempty array of nonempty arguments')
    return value


def _fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_receipt(directory, receipt):
    descriptor, temporary = tempfile.mkstemp(prefix='.checks-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'checks.json')
        _fsync_directory(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _exit_code(raw_code):
    return 128 - raw_code if raw_code < 0 else raw_code


def _exclusive_log(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, 'wb')


def execute(directory, checks, provider):
    """Consume one local wrapper start, preserving raw child returns in evidence."""
    _argv(provider)
    if not isinstance(checks, list):
        raise ValueError('tests must be an array of argument arrays')
    for check in checks:
        _argv(check)
    directory = Path(directory)
    if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
        raise ValueError('evidence directory must be an existing absolute native journal directory')
    if (directory / 'checks.json').exists() or (directory / 'checks.json').is_symlink():
        raise ValueError('existing check evidence cannot be replayed')
    # The marker is never removed: a lost provider reply is not a fresh start.
    descriptor = os.open(directory / 'tests.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='ascii') as lock:
        lock.write(str(os.getpid()) + '\n')
        lock.flush()
        os.fsync(lock.fileno())
    _fsync_directory(directory)
    if (directory / 'checks.json').exists() or (directory / 'checks.json').is_symlink():
        raise ValueError('check evidence appeared before provider start')
    receipt = {'schema': 'cdc-agent-checks/v1', 'provider_exit_code': None,
               'checks': [], 'status': 'not_run'}
    try:
        provider_code = subprocess.run(provider, stdin=subprocess.DEVNULL, check=False).returncode
    except OSError as exc:
        receipt['error'] = 'provider could not start: ' + str(exc)
        _write_receipt(directory, receipt)
        return 2
    receipt['provider_exit_code'] = provider_code
    if provider_code != 0 or not checks:
        _write_receipt(directory, receipt)
        return _exit_code(provider_code)
    for index, argv in enumerate(checks):
        stdout = directory / ('check-' + str(index) + '.stdout.log')
        stderr = directory / ('check-' + str(index) + '.stderr.log')
        observed = {'argv': list(argv), 'exit_code': None, 'started_at': _utc(),
                    'completed_at': None, 'stdout': str(stdout), 'stderr': str(stderr)}
        try:
            with _exclusive_log(stdout) as output, _exclusive_log(stderr) as errors:
                try:
                    observed['exit_code'] = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                                           stdout=output, stderr=errors,
                                                           check=False).returncode
                finally:
                    output.flush(); os.fsync(output.fileno())
                    errors.flush(); os.fsync(errors.fileno())
        except OSError as exc:
            observed['error'] = 'check could not complete: ' + str(exc)
        observed['completed_at'] = _utc()
        receipt['checks'].append(observed)
        if observed['exit_code'] != 0 or observed.get('error'):
            receipt['status'] = 'failed'
            _write_receipt(directory, receipt)
            code = observed['exit_code']
            return _exit_code(code) if code is not None and code != 0 else 2
    receipt['status'] = 'passed'
    _write_receipt(directory, receipt)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', required=True)
    parser.add_argument('--tests-json', required=True)
    parser.add_argument('provider_argv', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if not args.provider_argv or args.provider_argv[0] != '--':
            raise ValueError('provider argument array must follow --')
        checks = json.loads(args.tests_json)
        return execute(args.evidence_dir, checks, args.provider_argv[1:])
    except (ValueError, OSError) as exc:
        print('agent check runner: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
