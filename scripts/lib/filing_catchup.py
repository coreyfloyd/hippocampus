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


def inventory(store, cutoff, paths=None):
    """Read both providers' handoffs without consulting sessions or knowledge."""
    items, sources, errors = {}, {}, []
    if store.is_symlink() or not store.is_dir():
        return items, sources, ['handoff store must be an existing regular directory']
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
                    errors.append('conflicting carried copies of identity ' + key + ': ' + str(error))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            errors.append(str(path) + ': ' + str(error))
    return items, sources, errors


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
                  mode=args.command, items=[], errors=[], ready_for_durable_filing=False)
    items, sources, errors = inventory(store, args.cutoff)
    report.update(errors=errors, sources=sources, unique_items=len(items), unfiled_before_cutoff=len(items))
    save(report_path, report)
    for key, source in items.items():
        outcome = dict(source, status='pending', error='no filing judgment supplied')
        report['items'].append(outcome)
        if source.get('conflicts'):
            outcome['error'] = 'conflicting carried copies; no write attempted'
        elif args.command == 'run' and key in by_identity:
            try:
                # Check the eligible content, not checkpoint timestamps/newer work.
                refreshed, _, problems = inventory(store, args.cutoff, source['sources'])
                actual = refreshed.get(key)
                if (problems or actual is None or actual.get('conflicts')
                        or actual['item'] != source['item']):
                    raise ValueError('eligible source item changed before filing; retry')
                outcome.update(status='uncertain', error='write pending')
                save(report_path, report)
                result = file_item(source, by_identity[key], plan, ask)
                outcome.pop('error', None)
                outcome.update(result)
            except (ValueError, OSError, TypeError, KeyError) as error:
                outcome.update(status='failed', error=str(error))
        save(report_path, report)
    current, snapshots, errors = inventory(store, args.cutoff)
    report['errors'].extend(errors)
    report['recount_sources'] = snapshots
    confirmed = set()
    for row in report['items']:
        key = sweep.identity_key(row['identity'])
        actual = current.get(key)
        if row['status'] == 'filed':
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
