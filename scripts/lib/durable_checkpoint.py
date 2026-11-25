"""File a running interactive session using the shared checklist contracts."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import checklist
import filing_catchup


def settled_rows(positions, rows):
    """Rows index the loops as supplied. Follow each to its index in the written loops.

    ``positions`` is the checkpoint's own map from each supplied position to its written
    index, None for an item it dropped as settled (such as on a retry), and its loop. Returns the rows to
    file, the items already settled, and the rows skipped with their reason.
    """
    if not isinstance(rows, list):
        return rows, [], []
    result, settled, skipped = [], [], []
    for row in rows:
        index = row.get('index') if isinstance(row, dict) else None
        if type(index) is not int or index < 0:
            result.append(row)
        elif positions is None:
            skipped.append({'row': row, 'reason': 'the checkpoint could not map supplied positions to written loops'})
        elif index >= len(positions):
            result.append(row)  # Out of range: filing validation refuses it.
        elif positions[index][0] is None:
            settled.append(positions[index][1])
        else:
            result.append(dict(row, index=positions[index][0]))
    return result, settled, skipped


def run(module, supplied, args):
    if not args.report:
        raise ValueError('durable requires --report')
    path = module.resolve_path(args.cwd, args.session_id)
    if Path(args.report).resolve() == Path(path).resolve():
        raise ValueError('durable report must differ from the handoff')
    report = dict(session_id=args.session_id, started_at=module.utc_now(),
                  filed=[], unfiled=copy.deepcopy(module.supplied_session_items(supplied)), errors=[],
                  already_settled=[])
    resume = supplied.get('resume') if isinstance(supplied, dict) else None
    continuation = resume.get('next_action') if isinstance(resume, dict) else None
    report['next_action'] = continuation
    output = ''
    try:
        report['unfiled'] = module.merge_session_items(report['unfiled'], args.session_id)
        module.atomic_write(args.report, report)
        if not args.user_profile or not args.filing:
            raise ValueError('durable requires --user-profile and --filing')
        profiles = checklist.load_profiles(Path(args.user_profile), [Path(p) for p in args.repository_profile])
        plan, ask = checklist.compose(profiles), checklist.ask_binding(profiles[0])
        rows = json.loads(Path(args.filing).read_text())
        # Retain and validate before writes. Never read an earlier handoff when
        # checkpoint deliberately skipped writing this pass (e.g. keep-warm).
        initial = module.checkpoint(supplied, args.cwd, args.session_id, args.trigger, positions=True)
        output = initial.output
        if initial.exit_code:
            raise ValueError('; '.join(initial.errors) or 'checkpoint failed')
        if not initial.path or not Path(initial.path).is_file():
            raise ValueError('checkpoint wrote no handoff; filing skipped')
        data = module.read_json(initial.path)
        loops = data.get('resume', {}).get('open_loops')
        if not isinstance(loops, list):
            raise ValueError('checkpoint has no open_loops array; filing skipped')
        continuation = data['resume'].get('next_action', continuation)
        report.update(unfiled=copy.deepcopy(loops), next_action=continuation)
        rows, report['already_settled'], skipped = settled_rows(initial.positions, rows)
        if skipped:
            report['skipped_rows'] = skipped
        # Validate the entire set before dispatching asks. Their writer shares
        # the record lookup protocol; file_items validates the returned owner.
        checklist.file_items(plan, data, rows, ask, execute_writes=False)
        rows = copy.deepcopy(rows)
        for row in rows:
            item = data['resume']['open_loops'][row['index']]
            if checklist.filing_binding(row['rule'], item, row) != 'ask':
                continue
            if row.get('status') == 'filed':
                try:
                    checklist.require_ask_receipt(ask, row.get('receipt'), item, required_owner=True)
                    checklist.record_write.receipt(row, checklist.record_write.identity(item))
                except ValueError as error:
                    row.update(status='failed', error=str(error))
                    row.pop('ask_status', None)
            if row.get('status') == 'pending' and row.get('ask_delivery') == 'requested':
                try:
                    outcome = filing_catchup.file_item(dict(item=item, subject=data['subject']), row, plan, ask)
                    row.update({k: v for k, v in outcome.items() if k != 'index'})
                except (OSError, ValueError, TypeError, KeyError) as error:
                    row.update(status='failed', error=str(error))
        filed = checklist.file_items(plan, data, rows, ask,
                                     unattended=checklist.session_unattended(args.session_id))
        for entry in filed['filing']['items']:
            # The same delivery as catch-up: an ask the pass raised reaches the user through the ask writer.
            try:
                entry.update(filing_catchup.deliver_raised_ask(ask, entry))
            except (OSError, ValueError, TypeError, KeyError) as error:
                entry['error'] = f"{entry.get('ask_source')} ask: {error}"
            if entry.get('ask_source') and entry.get('ask_status') != 'filed':
                report['errors'].append(f"{entry['item'].get('context')}: {entry.get('error')}")
        filed['resume']['next_action'] = continuation
        module.atomic_write(path, filed)
        code, lint = module.lint_output(path)
        if code:
            report['errors'].append(lint)
        report['filed'] = [r for r in filed['filing']['items'] if r['status'] == 'filed']
        report['unfiled'] = filed['resume']['open_loops']
        report['items'] = filed['filing']['items']
        report['errors'].extend(filed['filing']['failures'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        report['errors'].append(str(error))
    report['ended_at'] = module.utc_now()
    module.atomic_write(args.report, report)
    if args.scheduled_report:
        try:
            response = checklist.record_write.invoke({'command': args.scheduled_report},
                {'operation': 'report', 'kind': 'durable_checkpoint', 'report': report})
            receipt = response.get('receipt')
            if response.get('status') != 'saved' or not isinstance(receipt, dict) or not receipt.get('destination'):
                raise ValueError('Scheduled report adapter requires a saved destination receipt')
            report['scheduled_receipt'] = receipt
        except (ValueError, OSError) as error:
            report['errors'].append('Scheduled report: ' + str(error))
        module.atomic_write(args.report, report)
    code = int(bool(report['unfiled'] or report['errors']))
    return module.CheckpointResult(path, code, output + f'Durable filing report: {args.report}\n', report['errors'])


def not_ready(report):
    """Name each condition that keeps one node's catch-up report from enabling filing."""
    problems = []
    if report.get('mode') != 'run':
        problems.append(f"mode {report.get('mode')!r}, not 'run'")
    if report.get('ready_for_durable_filing') is not True:
        problems.append(f"ready_for_durable_filing {report.get('ready_for_durable_filing')!r}")
    unfiled = report.get('unfiled_before_cutoff')
    if type(unfiled) is not int:
        problems.append(f'unfiled_before_cutoff {unfiled!r}')
    elif unfiled:
        problems.append(f'{unfiled} unfiled before the cutoff')
    errors = report.get('errors')
    if not isinstance(errors, list):
        problems.append(f'errors {errors!r}')
    elif errors:
        problems.append(f"{len(errors)} error{'s' if len(errors) > 1 else ''}, first: {errors[0]}")
    return problems


def schedule_request(session_id, cwd, required_nodes, reports):
    """Require successful per-node catch-up before asking a scheduler to enable."""
    if (not isinstance(session_id, str) or not session_id.strip()
            or not isinstance(required_nodes, list) or not required_nodes
            or not all(isinstance(node, str) and node.strip() for node in required_nodes)
            or len(set(required_nodes)) != len(required_nodes)):
        raise ValueError('schedule requires a session and distinct required nodes')
    if not isinstance(reports, list) or not all(isinstance(report, dict) for report in reports):
        raise ValueError('catch-up reports must be an array of objects')
    for report in reports:
        if not isinstance(report.get('node'), str) or not report['node'].strip():
            raise ValueError('catch-up report requires a node identifier')
        filing_catchup.sweep.timestamp(report.get('cutoff'))
    failures = []
    for node in required_nodes:
        found = [r for r in reports if r['node'] == node]
        problems = not_ready(found[0]) if len(found) == 1 else [
            'no catch-up report' if not found else f'{len(found)} catch-up reports']
        if problems:
            failures.append(f"{node}: {', '.join(problems)}")
    failures += [f"{node}: not a required node" for node in
                 dict.fromkeys(r['node'] for r in reports) if node not in required_nodes]
    if len({r['cutoff'] for r in reports}) > 1:
        failures.append('cutoffs differ: ' + ', '.join(f"{r['node']} {r['cutoff']}" for r in reports))
    if failures:
        raise ValueError('catch-up is not ready; periodic filing remains disabled: ' + '; '.join(failures))
    return dict(operation='ensure_job', kind='durable_checkpoint',
                job_key='FILE-4H:' + session_id, target_session=session_id,
                working_directory=cwd, interval_seconds=4 * 60 * 60,
                checkpoint_option='durable', report_surface='Scheduled',
                catchup_reports=reports)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Explicitly enable FILE-4H through a configured scheduler adapter')
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--required-node', action='append', required=True)
    parser.add_argument('--catchup-report', type=Path, action='append', required=True)
    parser.add_argument('--adapter', required=True)
    args = parser.parse_args()
    try:
        request = schedule_request(args.session_id, args.cwd, args.required_node,
                                   [json.loads(p.read_text()) for p in args.catchup_report])
        response = checklist.record_write.invoke({'command': args.adapter}, request)
        receipt = response.get('receipt')
        if (response.get('status') != 'saved' or not isinstance(receipt, dict)
                or receipt.get('job_key') != request['job_key'] or not receipt.get('destination')):
            raise ValueError('scheduler must acknowledge the job key and Scheduled destination')
        print(json.dumps(response, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        import sys
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
