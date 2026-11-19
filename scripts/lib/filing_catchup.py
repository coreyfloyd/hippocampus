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


def inventory(store, cutoff):
    """Read both providers' handoffs without consulting sessions or knowledge."""
    items, sources, errors = {}, {}, []
    if store.is_symlink() or not store.is_dir():
        return items, sources, ['handoff store must be an existing regular directory']
    for path in sorted(store.glob('*.json')):
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
                if key in items and items[key]['item'] != item:
                    raise ValueError('conflicting carried copies of identity ' + key)
                row = items.setdefault(key, dict(identity=identity, item=item, sources=[],
                                                subject=data.get('subject', {})))
                row['sources'].append(str(path))
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
    row = {**decision, 'index': 0, 'status': 'filed', 'destination': 'planned'}
    if row.get('rule') in ('R1', 'R6'):
        # Catch-up requires an actual home; a judgment to drop is not proof of filing.
        raise ValueError('catch-up requires a destination receipt, not a drop')
    single = {'subject': source['subject'], 'resume': {'open_loops': [item]}}
    checked = checklist.file_items(plan, single, [row], ask, execute_writes=False)['filing']['items'][0]
    kind = checked.get('binding')
    approval_pending = kind == 'ask' and checked.get('ask_status') == 'filed'
    if checked['status'] != 'filed' and not approval_pending:
        return {**checked, 'status': 'pending'}
    if kind == 'ask':
        if not ask or not ask.get('owner_agent'):
            raise ValueError('catch-up asks require a configured durable agent owner')
        payload = checked['ask']
        # The ask writer uses the same lookup/write identity and receipt protocol.
        result = record_write.execute(ask, 'asks', payload, checked)
        if result['status'] == 'filed':
            checklist.require_ask_receipt(ask, result.get('receipt'), payload)
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
        if args.command == 'run' and key in by_identity:
            try:
                # A concurrent handoff write blocks this item before any effect.
                for path in source['sources']:
                    _, snapshot = sweep.read_handoff_source(Path(path))
                    if snapshot != sources[path]:
                        raise ValueError('source handoff changed before filing')
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
    if snapshots != sources:
        report['errors'].append('handoff inventory changed during pass; retry before cutover')
    filed = {sweep.identity_key(row['identity']) for row in report['items'] if row['status'] == 'filed'}
    report['unfiled_before_cutoff'] = len(set(current) - filed)
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
