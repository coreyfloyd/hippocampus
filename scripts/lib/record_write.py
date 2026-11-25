"""Per-kind record writes: look up an immutable item identity before every write."""
from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
from typing import Any, Mapping


class Rejected(ValueError):
    """The store explicitly rejected the operation, optionally returning an ask for the user."""

    def __init__(self, message: str, ask: Any = None):
        super().__init__(message)
        self.ask = ask


KINDS = ('tickets', 'projects', 'documents', 'scheduled_jobs', 'decisions', 'logs')
SCOPES = ('area', 'repository', 'project')
DOCUMENTS_REFUSAL = ("the documents record write refuses a decision; "
                     "file it through the decisions record write (kind 'decisions')")
TICKET_DECISION = ("an agent decision tied to a ticket stays a comment on that ticket "
                   "through the tickets record write (R2)")


def bindings(profile: Mapping[str, Any]) -> dict[str, Any]:
    value = profile.get('record_writes', {})
    if not isinstance(value, Mapping) or set(value) - set(KINDS):
        raise ValueError('record_writes must map ' + ', '.join(KINDS) + ' to commands')
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


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _scope(value: Any) -> bool:
    return (isinstance(value, Mapping) and len(value) == 1 and set(value) <= set(SCOPES)
            and all(_text(v) for v in value.values()))


def ticket_anchor(item: Mapping[str, Any]) -> str | None:
    """The item's ticket, from its anchor or its top-level ``ticket``, as the filing pass reads it."""
    anchor = item.get('anchor')
    if anchor is not None and not isinstance(anchor, Mapping):
        raise ValueError('anchor must be an object')
    for ticket in ((anchor or {}).get('ticket'), item.get('ticket')):
        if _text(ticket):
            return ticket
    return None


def user_decision(item: Mapping[str, Any]) -> bool:
    """Anything not plainly an agent's decision is treated as the user's and needs approval."""
    return item.get('type') == 'decision' and not (
        item.get('entry') == 'agent_log' and item.get('author_role') == 'agent')


def require_approval(row: Mapping[str, Any]) -> None:
    if row.get('answer') != 'approve' or not _text(row.get('approval_source')):
        raise ValueError('a user decision requires explicit user approval and its source')


def decision_request(item: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    """A user's decision files only with explicit approval; an agent's only when no ticket holds it."""
    entry, proposal = item.get('entry'), item.get('decision_record')
    roles = {'record': 'user', 'agent_log': 'agent'}
    if entry not in roles or item.get('author_role') != roles[entry] or not _text(item.get('author')):
        raise ValueError("a decision requires entry 'record' with author_role 'user', or "
                         "'agent_log' with author_role 'agent', and its author")
    if not isinstance(proposal, Mapping) or not _scope(proposal.get('scope')):
        raise ValueError('decision_record.scope must name exactly one of ' + ', '.join(SCOPES))
    if not (_text(proposal.get('text')) and _text(proposal.get('why'))):
        raise ValueError('decision_record requires text and why')
    if entry == 'agent_log':
        if ticket_anchor(item):
            raise ValueError(TICKET_DECISION)
        return
    options = proposal.get('options')
    if (not _text(item.get('location')) or not _text(proposal.get('title'))
            or not isinstance(options, list) or not all(_text(o) for o in options)):
        raise ValueError('a decision record requires title, options, and the source location')
    require_approval(row)


def change_log_request(item: Mapping[str, Any]) -> None:
    entry = item.get('change_log')
    if (not _text(item.get('author')) or not isinstance(entry, Mapping) or not _scope(entry.get('scope'))
            or not _text(entry.get('subject')) or not _text(entry.get('text'))):
        raise ValueError('a change log entry requires its author and change_log scope, subject and text')


def check_request(kind: str, item: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    """Refuse a request its kind cannot file, before any lookup."""
    if kind == 'asks':
        # An ask carries a copy of the item it asks the user about; no item rule applies to it.
        return
    if kind == 'documents' and item.get('type') == 'decision':
        raise Rejected(DOCUMENTS_REFUSAL)
    if kind != 'decisions' and user_decision(item):
        # A user's decision reaches no other store, such as a ticket comment, unapproved.
        require_approval(row)
    if kind != 'logs' and 'change_log' in item:
        raise ValueError("a change log entry files only through the logs record write (kind 'logs')")
    if kind == 'decisions':
        if item.get('type') != 'decision':
            raise ValueError('the decisions record write files only decision items')
        decision_request(item, row)
    if kind == 'logs':
        change_log_request(item)


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
    default = ('tickets' if rule != 'R7' else 'decisions' if item.get('type') == 'decision'
               else 'logs' if 'change_log' in item else 'documents')
    kind = row.get('record_kind', item.get('record_kind', default))
    if kind not in KINDS:
        raise ValueError(f'unknown record write kind {kind!r}')
    return kind


def argv(command: str | list[str]) -> list[str]:
    """A binding command as argv, run without a shell: only `$VAR`, `${VAR}` and a leading `~` expand.

    An unset variable stays literal, so exec fails naming the token instead of an empty path.
    """
    tokens = shlex.split(command) if isinstance(command, str) else command
    return [os.path.expanduser(os.path.expandvars(token)) for token in tokens]


def invoke(binding: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = subprocess.run(argv(binding['command']), input=json.dumps(request), text=True,
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(str(error)) from error
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError(result.stderr.strip() or 'command ended without a usable response') from error
    if not isinstance(response, dict):
        raise ValueError('response must be an object')
    if response.get('status') == 'failed':
        raise Rejected(response.get('error') or result.stderr.strip() or 'record write failed',
                       response.get('ask'))
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'command exited {result.returncode}')
    return response


def receipt(response: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    value = response.get('receipt')
    if (not isinstance(value, dict) or value.get('identity') != expected or
            not isinstance(value.get('destination'), str) or not value['destination'].strip()):
        raise ValueError('missing or malformed receipt for item identity')
    return value


def execute(binding: Mapping[str, Any], kind: str, item: Mapping[str, Any], row: Mapping[str, Any],
            *, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A failed lookup blocks writes. Missing write acknowledgement is uncertain."""
    output = copy.deepcopy(dict(row))
    # The writer's earlier ask rides on the carried item; it is not part of the record.
    item = {k: v for k, v in item.items() if k != 'writer_ask'}
    phase = 'lookup'
    try:
        key = identity(item)
        check_request(kind, item, row)
        request = {'operation': 'lookup', 'kind': kind, 'identity': key, 'item': item, 'filing': row}
        if context is not None:
            request.update(context)
        found = invoke(binding, request)
        if kind == 'tickets' and 'tickets' in found:
            output['tickets'] = found['tickets']
        if found.get('status') == 'found':
            saved = receipt(found, key)
        elif found == {'status': 'not_found'}:
            phase = 'write'
            response = invoke(binding, {**request, 'operation': 'write'})
            if kind == 'tickets' and 'tickets' in response:
                output['tickets'] = response['tickets']
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
        if isinstance(error, Rejected) and isinstance(error.ask, Mapping):
            # The writer matched no destination: its ask goes to the user; nothing is guessed.
            output['writer_ask'] = copy.deepcopy(dict(error.ask))
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
