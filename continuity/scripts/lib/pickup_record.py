#!/usr/bin/env python3
"""Prepare agent-owned record reads and append only validated skill responses.

Reads a selected pickup report on stdin; never executes a binding or writes files.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from checklist import compose, load_profile, record_read_binding
from record_read import verdict


UNBOUND = 'No record read is bound.'


def line(report, text, provenance="validated: user profile and request preparation"):
    report['briefing'].append({'line': text, 'provenance': provenance,
                               'source': 'record_read'})


def prepare(report, no_commitments=False):
    """Resolve only the user profile; a read never starts a checklist plan."""
    if report.get('source') != 'handoff' or 'error' in report:
        return report
    previous = report.pop('record_read', {})
    no_commitments = no_commitments or previous.get('commitments_skipped', False)
    report['briefing'] = [row for row in report['briefing']
                          if row.get('source') != 'record_read' and row['line'] != UNBOUND]
    if no_commitments:
        line(report, 'Commitments from record: skipped (--no-commitments)')
    configured = os.environ.get('CHECKLIST_USER_PROFILE')
    path = Path(configured) if configured else Path(
        os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'checklist/profile.md'
    try:
        # Only an absent default is configured-nothing. An explicit path that
        # cannot be read, including an unavailable link, is still configured.
        binding = None
        if configured or path.exists() or path.is_symlink():
            try:
                profile = load_profile(path)
                # Reuse checklist validation without executing any plan steps.
                compose([profile])
                binding = record_read_binding(profile)
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f'{path}: invalid profile: {error}') from error
    except (OSError, ValueError, TypeError, AttributeError) as error:
        line(report, 'record read unavailable: user profile: ' + ' '.join(str(error).split()))
        return report
    if binding is None:
        line(report, UNBOUND)
        return report
    handoff = report['handoff']
    references = []
    # Ticket pointers are typed anchors, not text mined from a transcript.
    for loop in handoff['resume'].get('open_loops', []):
        anchor = loop.get('anchor') if isinstance(loop, dict) else None
        reference = anchor.get('ticket') if isinstance(anchor, dict) else None
        if isinstance(reference, str) and reference.strip() and reference not in references:
            references.append(reference)
    requests = {'ticket_status': {'kind': 'ticket_status', 'references': references}}
    if not no_commitments:
        requests['commitments'] = {
            'kind': 'commitments', 'session_id': handoff['subject'].get('session_id'),
            'repository': handoff['git'].get('repository_root') or handoff['subject']['working_directory'],
            'handoff': handoff}
    report['record_read'] = dict(command=binding['command'], requests=requests,
                                 commitments_skipped=no_commitments)
    for kind in requests:
        line(report, 'record read pending: ' + kind)
    return report


def complete(report, responses):
    """Each request succeeds independently; failed reads have no rows to render."""
    read = report.get('record_read')
    if not read:
        return report
    report['briefing'] = [row for row in report['briefing']
                          if not (row.get('source') == 'record_read'
                                  and row['line'].startswith('record read pending:'))]
    read['results'] = {}
    for kind, request in read['requests'].items():
        path = responses.get(kind)
        if path is None:
            line(report, 'record read unavailable: ' + kind + ': binding returned no response',
                 'validated: binding returned no response')
            continue
        try:
            text = path.read_text(encoding='utf-8')
            status, message = verdict(text, kind)
            if status:
                raise ValueError(message)
            response = json.loads(text)
            if kind == 'ticket_status' and set(request['references']) != {
                    row['reference'] for row in response['rows']}:
                raise ValueError('response does not cover exactly the requested references')
        except (OSError, UnicodeError, ValueError) as error:
            line(report, 'record read unavailable: ' + kind + ': ' + ' '.join(str(error).split()),
                 'validated: record-read response check')
            continue
        read['results'][kind] = response
        label = 'Tickets from record' if kind == 'ticket_status' else 'Commitments from record'
        if not response['rows']:
            line(report, label + ': none (validated empty response)',
                 'validated: record-read validator; binding reported no rows')
        for row in response['rows']:
            fields = ['reference', 'title', 'state', 'link']
            if kind == 'ticket_status':
                fields.append('latest_progress')
            line(report, label + ': ' + '; '.join(field + ': ' + row[field] for field in fields),
                 'validated: record-read validator and reference coverage; state reported by binding')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-commitments', action='store_true')
    parser.add_argument('--ticket-status', type=Path, help='raw skill response file')
    parser.add_argument('--commitments', type=Path, help='raw skill response file')
    parser.add_argument('--complete', action='store_true', help='finish even if neither skill returned output')
    args = parser.parse_args()
    report = prepare(json.load(sys.stdin), args.no_commitments)
    if args.complete or args.ticket_status is not None or args.commitments is not None:
        complete(report, {'ticket_status': args.ticket_status, 'commitments': args.commitments})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
