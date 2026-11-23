#!/usr/bin/env python3
"""One-time per-node filing of carried items, preserving every source handoff."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
import sweep

checklist = sweep.checklist
record_write = checklist.record_write
handoff = sweep.handoff


def settlement_receipts(store):
    """The settled-identity store the carry step reads for this handoff store, read as it reads it.

    A row settles exactly what it settles for the carry step (``handoff.settlement_key``).
    Every line the carry step skips (blank, undecodable, unparseable, not an object, or with
    no valid identity) settles nothing and is only counted in ``skipped``. Only an
    unreadable store is an error; a missing store has no receipts.
    """
    path = Path(handoff.settled_store_path(str(store)))
    read = dict(path=str(path), receipts={}, errors=[], skipped=[], strict={})
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return read
    except OSError as error:
        read['errors'].append('settled store ' + str(path) + ' is unreadable: ' + str(error))
        return read
    # Split on newlines only: receipts keep raw U+2028 or U+0085 inside their text.
    lines = data.split(b'\n')
    if not lines[-1]:
        lines.pop()
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            row = None
        key = handoff.settlement_key(row)
        if not key:
            read['skipped'].append(number)
            continue
        problem = handoff.invalid_receipt(row)
        if problem:
            read['strict'].setdefault(key, (number, problem))
        read['receipts'].setdefault(key, row)
    return read


def carry_key(entry):
    """The carry identity of an ``already_settled`` entry."""
    identity = entry['identity']
    return (identity['session_id'], identity['produced_at'], entry['type'], identity['text'])


def store_warnings(read, settled):
    """Skipped lines as one count, and strict-check failures only for receipts that settled a carried item."""
    where = 'settled store ' + read['path']
    warnings = []
    if read['skipped']:
        warnings.append(where + ': ' + str(len(read['skipped'])) + ' lines skipped as the carry step skips '
                        'them (not a receipt); first lines: ' + ', '.join(map(str, read['skipped'][:20])))
    for entry in settled:
        if carry_key(entry) in read['strict']:
            number, problem = read['strict'][carry_key(entry)]
            warnings.append(where + ' line ' + str(number) + ': ' + problem
                            + '; it still settles its identity, as for the carry step')
    return warnings


def settled_row(row, receipts):
    """One entry per carry identity among the copies, when every one has a receipt, else none."""
    keys = sorted({tuple(copy['item'].get(field) for field in handoff.SESSION_ITEM_IDENTITY)
                   for copy in row['copies']}, key=repr)
    if not all(key in receipts for key in keys):
        return []
    return [dict(identity=row['identity'], type=key[2], disposition=receipts[key].get('disposition'),
                 settled_at=receipts[key].get('settled_at')) for key in keys]


def merge_copies(first, second):
    """Only settlement hints and nonconflicting anchors may enrich a copy.

    Record stores key on session, time and text. The ledger deliberately retains
    distinct proposals/choices under one identity; those cannot share a receipt.
    A recorded flag in a handoff is never a substitute for writer lookup.
    """
    ignored = {'status', 'recorded', 'anchor'}
    left = {key: value for key, value in first.items() if key not in ignored}
    right = {key: value for key, value in second.items() if key not in ignored}
    if left != right:
        raise ValueError('proposal or item content differs')
    anchors = {}
    for item in (first, second):
        anchor = item.get('anchor', {})
        if not isinstance(anchor, dict):
            raise ValueError('anchor must be an object')
        for key, value in anchor.items():
            if key in anchors and anchors[key] != value:
                raise ValueError('anchor destinations differ')
            anchors[key] = value
    if anchors:
        left['anchor'] = anchors
    return left


def inventory(store, cutoff, receipts, paths=None):
    """Read both providers' handoffs without consulting sessions or knowledge.

    Returns the open items, the identities ``receipts`` already settle, source snapshots
    and errors.
    """
    items, sources, errors = {}, {}, []
    if store.is_symlink() or not store.is_dir():
        return items, [], sources, ['handoff store must be an existing regular directory']
    for path in sorted(store.glob('*.json') if paths is None else map(Path, paths)):
        try:
            raw, snapshot = sweep.read_handoff_source(path)
            data = json.loads(raw)
            loops = data.get('resume', {}).get('open_loops')
            if not isinstance(loops, list):
                raise ValueError('resume.open_loops must be an array')
            sources[str(path)] = snapshot
            for original in loops:
                if not isinstance(original, dict):
                    raise ValueError('carried item must be an object')
                subject = data.get('subject') or {}
                if (not (original.get('session_id') or subject.get('session_id') or data.get('session_id'))
                        or not (original.get('produced_at') or data.get('written_at'))):
                    raise ValueError('carried item lacks producing session or time')
                identity = sweep.item_identity(original, data, path)
                item = {**original, 'session_id': identity['session_id'],
                        'produced_at': identity['produced_at']}
                record_write.identity(item)
                if sweep.timestamp(identity['produced_at']) >= sweep.timestamp(cutoff):
                    continue
                key = sweep.identity_key(identity)
                row = items.setdefault(key, dict(identity=identity, item=item,
                    sources=[], copies=[], subject=data.get('subject', {})))
                row['sources'].append(str(path))
                row['copies'].append(dict(source=str(path), item=item))
                try:
                    row['item'] = merge_copies(row['item'], item)
                except ValueError as error:
                    row.setdefault('conflicts', []).append(str(error))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            errors.append(str(path) + ': ' + str(error))
    settled = []
    for key, row in list(items.items()):
        entries = settled_row(row, receipts)
        if entries:
            # A settlement receipt wins: a settled identity's conflicting copies need no write.
            settled += entries
            del items[key]
        else:
            errors += ['conflicting carried copies of identity ' + key + ': ' + conflict
                       for conflict in row.get('conflicts', [])]
    return items, settled, sources, errors


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_item(source, decision, plan, ask):
    """Use wrap's filing safeguards, but never read or settle a session ledger."""
    item = source['item']
    row = {**decision, 'index': 0}
    # A run judgment without status requests catch-up filing. Explicit deferred
    # outcomes retain their meaning, including when consumed by durable checkpoint.
    status = row.get('status', 'filed')
    requested = status == 'pending' and row.get('ask_delivery') == 'requested'
    validation = ({**row, 'status': 'filed', 'destination': row.get('destination') or 'planned'}
                  if status == 'filed' or requested else row)
    if row.get('rule') in ('R1', 'R6'):
        # Catch-up requires an actual home; a judgment to drop is not proof of filing.
        raise ValueError('catch-up requires a destination receipt, not a drop')
    single = {'subject': source['subject'], 'resume': {'open_loops': [item]}}
    checked = checklist.file_items(plan, single, [validation], ask, execute_writes=False)['filing']['items'][0]
    kind = checked.get('binding')
    if status != 'filed' and not (requested and kind == 'ask'):
        return {**checked, 'status': status}
    approval_pending = kind == 'ask' and checked.get('ask_status') == 'filed'
    if checked['status'] != 'filed' and not approval_pending:
        return {**checked, 'status': 'pending'}
    if kind == 'ask':
        payload = checked['ask']
        if not payload.get('owner_agent'):
            raise ValueError('catch-up asks require a configured or carried durable agent owner')
        # The ask writer uses the same lookup/write identity and receipt protocol.
        result = record_write.execute(ask, 'asks', payload, checked)
        if result['status'] == 'filed':
            checklist.require_ask_receipt(ask, result.get('receipt'), payload)
            if approval_pending:
                result.update(status='pending', ask_status='filed',
                              reason=checked['reason'])
        else:
            result.pop('ask_status', None)
        return result
    if kind not in record_write.KINDS:
        raise ValueError('native item needs its capture receipt or an approval ask')
    writes = next(step for step in plan if step['id'] == 'record')['record_writes']
    if checked.get('rule') == 'R5' and not all(checked.get(k) for k in ('priority', 'priority_reason')):
        raise ValueError('new ticket requires priority and priority_reason')
    context = None
    if kind == 'projects':
        summary = decision.get('session_summary')
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError('project filing requires session_summary')
        context = {key: decision.get(key, []) for key in ('close_outcomes', 'touched_projects')}
        context['session_summary'] = summary
    return record_write.execute(writes[kind], kind, item, checked, context=context)


UNREADABLE = 'settled store unreadable; no write attempted'


def add_unique(report, name, entries):
    report[name] += [entry for entry in entries if entry not in report[name]]


def add_settled(report, entries):
    known = {(sweep.identity_key(row['identity']), row['type']) for row in report['already_settled']}
    report['already_settled'] += [row for row in entries
                                  if (sweep.identity_key(row['identity']), row['type']) not in known]


def run(args):
    store = args.store.absolute()
    report_path = args.report.absolute()
    if report_path.resolve() == store.resolve() or store.resolve() in report_path.resolve().parents:
        raise ValueError('report must be outside the handoff store')
    sweep.timestamp(args.cutoff)
    profile = checklist.load_profile(args.user_profile)
    plan, ask = checklist.compose([profile]), checklist.ask_binding(profile)
    decisions = json.loads(args.decisions.read_text()) if args.decisions else []
    if not isinstance(decisions, list):
        raise ValueError('decisions must be an array')
    by_identity = {}
    for row in decisions:
        key = sweep.identity_key(row['identity'])
        if key in by_identity:
            raise ValueError('duplicate filing judgment')
        by_identity[key] = {k: v for k, v in row.items() if k != 'identity'}
    report = dict(node=args.node, cutoff=args.cutoff, started_at=datetime.now(timezone.utc).isoformat(),
                  mode=args.command, items=[], errors=[], warnings=[], ready_for_durable_filing=False)
    read = settlement_receipts(store)
    items, settled, sources, problems = inventory(store, args.cutoff, read['receipts'])
    settled_ids = {sweep.identity_key(row['identity']): row['identity'] for row in settled}
    report.update(errors=read['errors'] + problems, warnings=store_warnings(read, settled), sources=sources,
                  unique_items=len(items) + len(settled_ids), unfiled_before_cutoff=len(items),
                  already_settled=[], ignored_decisions=[
                      dict(identity=identity, reason='identity already settled; judgment not used')
                      for key, identity in settled_ids.items() if key in by_identity])
    add_settled(report, settled)
    save(report_path, report)
    store_failed, attempted = bool(read['errors']), set()
    for key, source in items.items():
        outcome = dict(source, status='pending', error='no filing judgment supplied')
        report['items'].append(outcome)
        if source.get('conflicts'):
            outcome['error'] = 'conflicting carried copies; no write attempted'
        elif args.command == 'run' and key in by_identity and not store_failed:
            try:
                # Re-read the store: the carry step may have settled this identity since.
                fresh = settlement_receipts(store)
                add_unique(report, 'errors', fresh['errors'])
                store_failed = bool(fresh['errors'])
                if store_failed:
                    raise ValueError(UNREADABLE)
                # Check the eligible content, not checkpoint timestamps/newer work.
                refreshed, now_settled, _, problems = inventory(store, args.cutoff, fresh['receipts'],
                                                                source['sources'])
                mine = [row for row in now_settled if sweep.identity_key(row['identity']) == key]
                if mine:
                    add_settled(report, mine)
                    add_unique(report, 'warnings', store_warnings(dict(fresh, skipped=[]), mine))
                    outcome.pop('error')
                    outcome['status'] = 'already_settled'
                else:
                    actual = refreshed.get(key)
                    if (problems or actual is None or actual.get('conflicts')
                            or actual['item'] != source['item']):
                        raise ValueError('eligible source item changed before filing; retry')
                    outcome.update(status='uncertain', error='write pending')
                    save(report_path, report)
                    attempted.add(key)
                    result = file_item(source, by_identity[key], plan, ask)
                    outcome.pop('error', None)
                    outcome.update(result)
            except (ValueError, OSError, TypeError, KeyError) as error:
                if store_failed:
                    outcome['error'] = UNREADABLE
                else:
                    outcome.update(status='failed', error=str(error))
        elif args.command == 'run' and store_failed:
            # Without the whole store, a settled identity could be filed again.
            outcome['error'] = UNREADABLE
        save(report_path, report)
    read = settlement_receipts(store)
    current, settled, snapshots, problems = inventory(store, args.cutoff, read['receipts'])
    add_unique(report, 'errors', read['errors'] + problems)
    add_unique(report, 'warnings', store_warnings(read, settled))
    report['recount_sources'] = snapshots
    # A receipt the carry step wrote during the run settles the identity for both.
    confirmed = {sweep.identity_key(row['identity']) for row in settled}
    add_settled(report, settled)
    for row in report['items']:
        key = sweep.identity_key(row['identity'])
        actual = current.get(key)
        if key in confirmed and row['status'] != 'filed':
            if key in attempted:
                # The receipt may not come from this write; keep what the write reported.
                row['recount_note'] = 'identity now settled by a receipt; this run attempted a write'
            else:
                row.pop('error', None)
                row['status'] = 'already_settled'
        elif row['status'] == 'filed':
            if actual is None or (not actual.get('conflicts') and actual['item'] == items[key]['item']):
                confirmed.add(key)
            else:
                row['recount_error'] = 'eligible content changed; receipt does not settle current copies'
    for key in set(current) - set(items):
        report['items'].append(dict(current[key], status='pending',
                                    error='old eligible item discovered at recount; retry'))
    # Keep failed initial work counted even if a concurrent checkpoint omits it.
    report['unfiled_before_cutoff'] = len((set(items) | set(current)) - confirmed)
    report['ready_for_durable_filing'] = (args.command == 'run' and not report['errors']
        and report['unfiled_before_cutoff'] == 0)
    report['ended_at'] = datetime.now(timezone.utc).isoformat()
    save(report_path, report)
    return 0 if report['ready_for_durable_filing'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'run'))
    parser.add_argument('--node', required=True)
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--cutoff', required=True, help='fixed timezone-bearing pass cutoff')
    parser.add_argument('--user-profile', required=True, type=Path)
    parser.add_argument('--decisions', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.store.is_dir() and not args.store.is_symlink():
            lock = os.open(args.store, os.O_RDONLY)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return run(args)
            finally:
                os.close(lock)
        return run(args)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
