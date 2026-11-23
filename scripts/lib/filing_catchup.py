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
    """One entry per carry identity among the copies, when every one has a receipt, else none.

    Superseded copies count too: each copy's own carry identity needs its own receipt.
    """
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


# The fields a newer copy may change: its anchor and its proposal text. Every other field,
# the type included, decides how the item is filed, so copies differing there conflict.
SUPERSEDABLE = ('status', 'recorded', 'anchor', 'choices', 'ask_text')


def filing_difference(newer, older):
    """Why ``older`` cannot be superseded by ``newer``, else None."""
    if newer.get('type') == older.get('type') == 'artifact' and newer.get('location') != older.get('location'):
        return ('artifacts of one session and produced_at have different locations; catch-up cannot '
                'drop or settle either by their shared identity')
    if newer.get('type') != older.get('type'):
        return 'copies differ in type (' + str(older.get('type')) + ', then ' + str(newer.get('type')) + ')'
    fields = sorted(key for key in set(newer) | set(older)
                    if key not in SUPERSEDABLE and newer.get(key, older) != older.get(key, newer))
    return 'copies differ in filing content: ' + ', '.join(fields) if fields else None


def resolve_copies(row):
    """Merge an identity's copies; where they conflict, the copy from the newest handoff wins.

    Copies are ordered by their handoff's ``written_at`` (content, never file metadata). An
    older copy that does not merge into the newest one is kept under ``superseded_copies``
    with its source and the difference, but only when it agrees with the newest copy on type
    and on every field that decides filing (``filing_difference``); it may differ only in its
    anchor and proposal text. Any other difference stays a conflict, as does a conflict that
    cannot be ordered (a handoff without a valid ``written_at``, or conflicting copies written
    at the same time). So a filed type is never superseded by a droppable one.
    """
    item = row['copies'][0]['item']
    try:
        for copy in row['copies'][1:]:
            item = merge_copies(item, copy['item'])
        row['item'] = item
        return
    except ValueError:
        pass
    if any(copy['written_at'] is None for copy in row['copies']):
        row['conflicts'] = ['copies differ and a handoff has no valid written_at to order them']
        return
    ordered = sorted(row['copies'], key=lambda copy: (-copy['written_at'], copy['source']))
    newest = [copy for copy in ordered if copy['written_at'] == ordered[0]['written_at']]
    item = newest[0]['item']
    for copy in newest[1:]:
        try:
            item = merge_copies(item, copy['item'])
        except ValueError as error:
            row['conflicts'] = ['copies written at the same time differ: '
                                + (filing_difference(item, copy['item']) or str(error))]
            return
    superseded = []
    for copy in ordered[len(newest):]:
        try:
            item = merge_copies(item, copy['item'])
        except ValueError as error:
            problem = filing_difference(item, copy['item'])
            if problem:
                row['conflicts'] = [problem]
                return
            superseded.append(dict(source=copy['source'], written_at=copy['written_at_text'],
                                   item=copy['item'], difference=str(error)))
    row.update(item=item, superseded_copies=superseded)


def handoff_time(data):
    """A handoff's own ``written_at`` as a number, or None when it has no valid one."""
    try:
        return sweep.timestamp(data['written_at'])
    except (KeyError, TypeError, ValueError):
        return None


def unstable_identity(item, data):
    """Why catch-up cannot give this loop a stable, fileable identity, else None.

    Identity is content only: the item's own fields, else its handoff's ``subject.session_id``
    and ``written_at``, never the file's name or modification time. A typed item is identified
    by its own fields alone, as the carry step settles it (``handoff.session_item_identity``).
    """
    if not isinstance(item.get('context'), str) or not item['context'].strip():
        return 'has no context; it cannot be filed (see #285 for writers, #271 for existing loops)'
    if item.get('type') in handoff.ITEM_TYPES:
        if not (item.get('session_id') and item.get('produced_at')):
            return 'is a typed item without its own session_id and produced_at; the carry step cannot settle it'
        return None
    subject = data.get('subject')
    subject = subject if isinstance(subject, dict) else {}
    if not (item.get('session_id') or subject.get('session_id') or data.get('session_id')):
        return 'has no producing session in the item or its handoff; a file name is not an identity'
    if not (item.get('produced_at') or data.get('written_at')):
        return 'has no producing time in the item or its handoff; a file time is not an identity'
    return None


def written_before(data, cutoff):
    """Whether a handoff's own ``written_at`` is before the cutoff; unknown counts as before."""
    written = handoff_time(data)
    return written is None or written < sweep.timestamp(cutoff)


def inventory(store, cutoff, receipts, paths=None):
    """Read both providers' handoffs without consulting sessions or knowledge.

    Returns the open items, the identities ``receipts`` already settle, source snapshots,
    errors, loop errors and warnings. Items come from ``sweep.carried_items``, as for the
    sweep. A loop without a stable, fileable identity (``unstable_identity``) is a loop
    error, never an item; it blocks readiness but not the other items of its handoff. A null
    ``open_loops`` in a handoff not written after the cutoff is a warning naming it. Copies of
    one identity resolve through ``resolve_copies``.
    """
    items, sources, errors, loop_errors, warnings = {}, {}, [], [], []
    if store.is_symlink() or not store.is_dir():
        return items, [], sources, ['handoff store must be an existing regular directory'], [], warnings
    for path in sorted(store.glob('*.json') if paths is None else map(Path, paths)):
        try:
            raw, snapshot = sweep.read_handoff_source(path)
            data, null_loops = sweep.null_loops_as_empty(json.loads(raw))
            carried_items = sweep.carried_items(data, path)
            sources[str(path)] = snapshot
            if null_loops and written_before(data, cutoff):
                warnings.append(str(path) + ': ' + sweep.NULL_LOOPS)
            subject = data.get('subject')
            for index, carried in enumerate(carried_items):
                problem = unstable_identity(carried['item'], data)
                if problem:
                    loop_errors.append(str(path) + ': open_loops[' + str(index) + '] ' + problem)
                    continue
                identity = carried['identity']
                item = {**carried['item'], 'session_id': identity['session_id'],
                        'produced_at': identity['produced_at']}
                if sweep.timestamp(identity['produced_at']) >= sweep.timestamp(cutoff):
                    continue
                key = sweep.identity_key(identity)
                row = items.setdefault(key, dict(identity=identity, item=item,
                    sources=[], copies=[], subject=subject if isinstance(subject, dict) else {}))
                row['sources'].append(str(path))
                row['copies'].append(dict(source=str(path), item=item, written_at=handoff_time(data),
                                          written_at_text=data.get('written_at')))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            errors.append(str(path) + ': ' + str(error))
    settled = []
    for key, row in list(items.items()):
        resolve_copies(row)
        row['copies'] = [dict(source=copy['source'], item=copy['item']) for copy in row['copies']]
        entries = settled_row(row, receipts)
        if entries:
            # A settlement receipt wins: a settled identity's conflicting copies need no write.
            settled += entries
            del items[key]
        else:
            errors += ['conflicting carried copies of identity ' + key + ': ' + conflict
                       for conflict in row.get('conflicts', [])]
    return items, settled, sources, errors, loop_errors, warnings


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


DROPPABLE = ('progress', 'open_loop', 'artifact')
UNANCHORED_COMMITMENT = ('a commitment without a ticket anchor stays unfiled: catch-up never creates '
                         'a ticket for it until the maintainer sets a rule')


def drop_item(source, decision, plan, ask, store, node):
    """Settle a droppable item with a ``dropped`` receipt, so the carry step stops carrying it.

    Knowledge, lessons, decisions and commitments are filed, never dropped; every drop needs
    a reason and passes the wrap's checks for its rule. The receipt goes through the carry
    step's own writer into the store catch-up reads, and the drop counts only when the store
    then settles the identity with this drop.
    """
    item = source['item']
    if decision.get('status', 'filed') not in ('filed', 'dropped'):
        raise ValueError('a drop judgment (R1 or R6) takes status dropped or none')
    if item.get('type') not in DROPPABLE:
        raise ValueError('a ' + str(item.get('type') or 'untyped') + ' item is filed, never dropped; '
                         'catch-up drops only ' + ', '.join(DROPPABLE) + ' items')
    reason = decision.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('a drop requires a non-empty reason')
    single = {'subject': source['subject'], 'resume': {'open_loops': [item]}}
    checked = checklist.file_items(plan, single, [{**decision, 'status': 'dropped', 'index': 0}], ask,
                                   execute_writes=False)['filing']['items'][0]
    if checked['status'] != 'dropped':
        return {**checked, 'status': checked['status']}
    receipt = handoff.settlement_receipt(item, 'filing-catchup:' + node, 'dropped', reason)
    if not receipt:
        raise ValueError('item has no carry identity to settle')
    path = handoff.settled_store_path(str(store))
    if not handoff.write_settlement_receipts([receipt], path)['written']:
        key = handoff.receipt_key(receipt['identity'])
        found = settlement_receipts(store)['receipts'].get(key, {})
        if (found.get('disposition'), found.get('reason')) != ('dropped', receipt['reason']):
            raise ValueError('another receipt (disposition ' + str(found.get('disposition'))
                             + ') settled this identity first; the drop was not recorded')
        receipt = found
    return dict(status='dropped', rule=decision['rule'], reason=receipt['reason'], destination=None,
                receipt=receipt)


def ticket_anchor(item):
    """The item's ticket anchor when it is a non-empty string, else None."""
    anchor = item.get('anchor')
    ticket = anchor.get('ticket') if isinstance(anchor, dict) else None
    return ticket if isinstance(ticket, str) and ticket.strip() else None


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
        # A drop is settled by ``drop_item``'s receipt, never by a record write.
        raise ValueError('catch-up requires a destination receipt, not a drop')
    single = {'subject': source['subject'], 'resume': {'open_loops': [item]}}
    checked = checklist.file_items(plan, single, [validation], ask, execute_writes=False)['filing']['items'][0]
    kind = checked.get('binding')
    if item.get('type') == 'commitment' and kind == 'tickets':
        if not ticket_anchor(item):
            return {**checked, 'status': 'pending', 'reason': UNANCHORED_COMMITMENT}
        if checked.get('rule') == 'R5':
            raise ValueError('an anchored commitment files as an R2 comment on its ticket, never a new ticket (R5)')
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
    items, settled, sources, problems, unfileable, notes = inventory(store, args.cutoff, read['receipts'])
    settled_ids = {sweep.identity_key(row['identity']): row['identity'] for row in settled}
    report.update(errors=read['errors'] + problems + unfileable, warnings=store_warnings(read, settled) + notes,
                  sources=sources,
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
                refreshed, now_settled, _, problems, _, _ = inventory(store, args.cutoff, fresh['receipts'],
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
                    judgment = by_identity[key]
                    result = (drop_item(source, judgment, plan, ask, store, args.node)
                              if judgment.get('rule') in ('R1', 'R6')
                              else file_item(source, judgment, plan, ask))
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
    current, settled, snapshots, problems, unfileable, notes = inventory(store, args.cutoff, read['receipts'])
    add_unique(report, 'errors', read['errors'] + problems + unfileable)
    add_unique(report, 'warnings', store_warnings(read, settled) + notes)
    report['recount_sources'] = snapshots
    # A receipt the carry step wrote during the run settles the identity for both.
    confirmed = {sweep.identity_key(row['identity']) for row in settled}
    add_settled(report, settled)
    # A drop's receipt settles its identity, so compare dropped rows with the copies as read without receipts.
    unsettled = (inventory(store, args.cutoff, {})[0]
                 if any(row['status'] == 'dropped' for row in report['items']) else {})
    for row in report['items']:
        key = sweep.identity_key(row['identity'])
        actual = current.get(key)
        if key in confirmed and row['status'] not in ('filed', 'dropped'):
            if key in attempted:
                # The receipt may not come from this write; keep what the write reported.
                row['recount_note'] = 'identity now settled by a receipt; this run attempted a write'
            else:
                row.pop('error', None)
                row['status'] = 'already_settled'
        elif row['status'] == 'filed' or (row['status'] == 'dropped' and key in confirmed):
            if row['status'] == 'dropped':
                actual = unsettled.get(key)
            if actual is None or (not actual.get('conflicts') and actual['item'] == items[key]['item']):
                confirmed.add(key)
            else:
                if row['status'] == 'dropped':
                    confirmed.discard(key)  # The drop never saw the current copies.
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
