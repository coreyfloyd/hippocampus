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


def decision_routes(profile: Mapping[str, Any]) -> dict[str, Any] | None:
    value = profile.get('decision_records')
    if value is None:
        return None
    if (not isinstance(value, Mapping) or set(value) - {'default_folder', 'scope_folders'}
            or not isinstance(value.get('default_folder'), str) or not value['default_folder'].strip()):
        raise ValueError('decision_records requires default_folder and optional scope_folders')
    scopes = value.get('scope_folders', {})
    if not isinstance(scopes, Mapping) or not all(
            isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
            for k, v in scopes.items()):
        raise ValueError('decision_records.scope_folders must map scopes to folders')
    return copy.deepcopy(dict(value))


def decision_document(item: Mapping[str, Any], row: Mapping[str, Any], kind: str | None) -> bool:
    """Document safeguards follow the filing route, not every decision item."""
    return item.get('type') == 'decision' and (row.get('rule') == 'R7' or kind == 'documents')


def decision_filing(item: Mapping[str, Any], row: Mapping[str, Any],
                    routes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Only a user's approved proposal may reach the documents writer."""
    proposal = item.get('decision_record')
    if item.get('author_role') != 'user' or not all(
            isinstance(item.get(k), str) and item[k].strip() for k in ('author', 'location')):
        raise ValueError('decision record requires a user author and source location')
    if not isinstance(proposal, Mapping) or not all(
            isinstance(proposal.get(k), str) and proposal[k].strip() for k in ('title', 'scope', 'text')):
        raise ValueError('decision record requires title, scope, and text')
    if (row.get('rule') != 'R7' or row.get('answer') != 'approve'
            or not isinstance(row.get('approval_source'), str) or not row['approval_source'].strip()):
        raise ValueError('decision record requires explicit user approval and its source')
    if row.get('record_kind', 'documents') != 'documents' or item.get('record_kind', 'documents') != 'documents':
        raise ValueError('decision records must use documents')
    if not routes:
        raise ValueError('decision record has no configured default folder')
    folder = routes.get('scope_folders', {}).get(proposal['scope'], routes['default_folder'])
    return {**copy.deepcopy(dict(row)), 'record_kind': 'documents', 'folder': folder}


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


def receipt(response: Mapping[str, Any], expected: Mapping[str, Any],
            *, folder: str | None = None) -> dict[str, Any]:
    value = response.get('receipt')
    if (not isinstance(value, dict) or value.get('identity') != expected or
            not isinstance(value.get('destination'), str) or not value['destination'].strip()):
        raise ValueError('missing or malformed receipt for item identity')
    if folder is not None and value.get('folder') != folder:
        raise ValueError('decision receipt does not confirm the configured folder')
    return value


def execute(binding: Mapping[str, Any], kind: str, item: Mapping[str, Any], row: Mapping[str, Any],
            *, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A failed lookup blocks writes. Missing write acknowledgement is uncertain."""
    output = copy.deepcopy(dict(row))
    phase = 'lookup'
    try:
        key = identity(item)
        request = {'operation': 'lookup', 'kind': kind, 'identity': key, 'item': item, 'filing': row}
        if context is not None:
            request.update(context)
        folder = row.get('folder') if decision_document(item, row, kind) else None
        found = invoke(binding, request)
        if kind == 'tickets' and 'tickets' in found:
            output['tickets'] = found['tickets']
        if found.get('status') == 'found':
            saved = receipt(found, key, folder=folder)
        elif found == {'status': 'not_found'}:
            phase = 'write'
            response = invoke(binding, {**request, 'operation': 'write'})
            if kind == 'tickets' and 'tickets' in response:
                output['tickets'] = response['tickets']
            if response.get('status') != 'saved':
                raise ValueError('write ended without a usable receipt')
            saved = receipt(response, key, folder=folder)
        else:
            raise ValueError('malformed lookup: expected found receipt or not_found')
        output.update(status='filed', receipt=saved, destination=saved['destination'])
        output.pop('error', None)
    except ValueError as error:
        output.update(status='failed' if phase == 'lookup' or isinstance(error, Rejected) else 'uncertain',
                      error=f'{phase}: {error}')
    return output


def reverse(binding: Mapping[str, Any], kind: str, identity: Mapping[str, Any], receipt: Mapping[str, Any],
            *, run_id: str, write_operation: str) -> dict[str, Any]:
    """Ask a record write to reverse this run's confirmed write."""
    if kind not in KINDS:
        raise ValueError(f'unknown record write kind {kind!r}')
    expected = ('session_id', 'produced_at', 'text')
    if set(identity) != set(expected) or not all(isinstance(identity[key], str) and identity[key].strip()
                                                 for key in expected):
        raise ValueError('reverse requires a complete item identity')
    if (not isinstance(receipt, Mapping) or receipt.get('identity') != identity or
            not isinstance(receipt.get('destination'), str) or not receipt['destination'].strip()):
        raise ValueError('reverse requires the original receipt')
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(write_operation, str) or not write_operation.strip():
        raise ValueError('reverse requires the original run and write operation')
    try:
        response = invoke(binding, {'operation': 'reverse', 'kind': kind, 'identity': dict(identity),
                                    'receipt': dict(receipt), 'run_id': run_id,
                                    'write_operation': write_operation})
    except Rejected as error:
        return {'status': 'failed', 'error': str(error).strip() or 'record write failed'}
    if response == {'status': 'reversed'}:
        return response
    if (set(response) == {'status', 'reason'} and response.get('status') == 'conflict' and
            isinstance(response['reason'], str) and response['reason'].strip()):
        return response
    raise ValueError('malformed reverse response')
