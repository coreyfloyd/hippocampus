"""Per-kind record writes: look up an immutable item identity before every write."""
from __future__ import annotations

import copy
import json
import shlex
import subprocess
from typing import Any, Mapping


class Rejected(ValueError):
    """The store explicitly rejected the operation."""


KINDS = ('tickets', 'projects', 'documents', 'scheduled_jobs')


def bindings(profile: Mapping[str, Any]) -> dict[str, Any]:
    value = profile.get('record_writes', {})
    if not isinstance(value, Mapping) or set(value) - set(KINDS):
        raise ValueError('record_writes must map tickets, projects, documents, or scheduled_jobs to commands')
    for kind, binding in value.items():
        if binding is None:
            continue
        if not isinstance(binding, Mapping) or set(binding) != {'command'}:
            raise ValueError(f'record_writes.{kind} requires only command')
        command = binding['command']
        if not ((isinstance(command, str) and command.strip()) or
                (isinstance(command, list) and command and
                 all(isinstance(s, str) and s.strip() for s in command))):
            raise ValueError(f'record_writes.{kind} requires a non-empty command or argv array')
    return copy.deepcopy(dict(value))


def identity(item: Mapping[str, Any]) -> dict[str, str]:
    result = {key: item.get(source) for key, source in
              [('session_id', 'session_id'), ('produced_at', 'produced_at'), ('text', 'context')]}
    if not all(isinstance(v, str) and v.strip() for v in result.values()):
        raise ValueError('record write identity requires producing session_id, produced_at, and context')
    return result


def kind_for(rule: str, item: Mapping[str, Any], row: Mapping[str, Any], writes: Mapping[str, Any]) -> str:
    if item.get('type') == 'commitment':
        if any(item.get(k) for k in ('time', 'recurrence', 'scheduled_at', 'due_at')) and writes.get('scheduled_jobs'):
            return 'scheduled_jobs'
        return 'tickets'
    kind = row.get('record_kind', item.get('record_kind', 'documents' if rule == 'R7' else 'tickets'))
    if kind not in KINDS:
        raise ValueError(f'unknown record write kind {kind!r}')
    return kind


def invoke(binding: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    command = binding['command']
    argv = shlex.split(command) if isinstance(command, str) else command
    try:
        result = subprocess.run(argv, input=json.dumps(request), text=True, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(str(error)) from error
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError(result.stderr.strip() or 'command ended without a usable response') from error
    if not isinstance(response, dict):
        raise ValueError('response must be an object')
    if response.get('status') == 'failed':
        raise Rejected(response.get('error') or result.stderr.strip() or 'record write failed')
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'command exited {result.returncode}')
    return response


def receipt(response: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    value = response.get('receipt')
    if (not isinstance(value, dict) or value.get('identity') != expected or
            not isinstance(value.get('destination'), str) or not value['destination'].strip()):
        raise ValueError('missing or malformed receipt for item identity')
    return value


def execute(binding: Mapping[str, Any], kind: str, item: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """A failed lookup blocks writes. Missing write acknowledgement is uncertain."""
    output = copy.deepcopy(dict(row))
    phase = 'lookup'
    try:
        key = identity(item)
        request = {'operation': 'lookup', 'kind': kind, 'identity': key, 'item': item, 'filing': row}
        found = invoke(binding, request)
        if found.get('status') == 'found':
            saved = receipt(found, key)
        elif found == {'status': 'not_found'}:
            phase = 'write'
            response = invoke(binding, {**request, 'operation': 'write'})
            if response.get('status') != 'saved':
                raise ValueError('write ended without a usable receipt')
            saved = receipt(response, key)
        else:
            raise ValueError('malformed lookup: expected found receipt or not_found')
        output.update(status='filed', receipt=saved, destination=saved['destination'])
        output.pop('error', None)
    except ValueError as error:
        output.update(status='failed' if phase == 'lookup' or isinstance(error, Rejected) else 'uncertain',
                      error=f'{phase}: {error}')
    return output
