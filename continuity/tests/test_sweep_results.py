"""Agent results drive the sweep; sources use the captured redacted handoff."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from test_sweep import (sandbox, source, command, decisions, bound_profile,
                        outside_report_snapshot, FIXTURE, archive_test_repository, assert_readable_report)


def read_run(path):
    return json.loads(Path(path).read_text().split('```json\n', 1)[1].rsplit('\n```', 1)[0])


def act(sandbox, entries=None):
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['mode'] = 'act'
    sandbox[2].write_text(json.dumps(cfg))
    profile = bound_profile(sandbox)
    args = decisions(sandbox, entries or [new_work()])
    result = command(sandbox, 'run', '--scope', 'all', *args, '--user-profile', str(profile))
    payload = json.loads(result.stdout)
    journal = read_run(payload['report'])
    assert payload['work'] == journal['work']
    assert payload['run_id'] == journal['run_id']
    return journal


def new_work():
    return dict(rule='R5', destination='new ticket', read_status='ok', priority='p2', priority_reason='Stated outcome')


def complete(sandbox, run, statuses=None, verb='complete'):
    statuses = statuses if statuses is not None else ['written'] * len(run['work'])
    rows = []
    for work, status in zip(run['work'], statuses):
        if status is None:
            continue
        rows.append(dict(write_id=work['write_id'], status=status, receipt='receipt-' + work['write_id'],
                         destination=work.get('destination') or 'record:created', error='rejected'))
    path = sandbox[0] / 'results.json'
    path.write_text(json.dumps(rows))
    done = command(sandbox, verb, '--run-id', run['run_id'], '--results', str(path))
    payload = json.loads(done.stdout)
    return read_run(payload['report'])


@pytest.mark.parametrize('status', ['written', 'already_written', 'failed', 'uncertain', None])
def test_plan_journals_before_return_and_completion_keeps_unknowns(sandbox, status):
    path = source(sandbox)
    original = path.read_bytes()
    run = act(sandbox)
    assert path.read_bytes() == original
    assert run['phase'] == 'planned' and not (sandbox[1] / 'archive').exists()
    work, = run['work']
    assert work['operation'] == 'create_ticket'
    assert work['identity'] == run['directories'][str(sandbox[0])]['filing_outcomes'][0]['identity']
    assert work['session_id'] == work['identity']['session_id']
    assert work['text'] == work['identity']['text']
    assert work['directory'] == str(sandbox[0]) and work['source_handoff'] == str(path)
    assert work['priority'] == 'p2' and work['priority_reason']
    command(sandbox, 'run', '--scope', 'all', code=2)
    done = complete(sandbox, run, [status])
    row = done['directories'][str(sandbox[0])]['filing_outcomes'][0]
    assert row['outcome'] == (status or 'uncertain')
    assert path.exists() == (status not in ('written', 'already_written'))
    assert not list(sandbox[0].glob('binding.sh.called'))
    assert done['phase'] == 'completed'
    assert len(done['undo_items']) == (2 if status == 'written' else 1 if status == 'already_written' else 0)
    if path.exists():
        retry = act(sandbox)
        assert retry['work'][0]['identity'] == work['identity']
        complete(sandbox, retry, ['already_written'])
        assert not path.exists()


def test_watch_and_direct_act_inventory_change_only_report(sandbox):
    source(sandbox, loops=[])
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['mode'] = 'act'
    sandbox[2].write_text(json.dumps(cfg))
    profile = bound_profile(sandbox)
    before = outside_report_snapshot(sandbox)
    result = command(sandbox, 'run', '--scope', 'all', '--user-profile', str(profile))
    run = read_run(result.stdout.strip())
    assert run['mode'] == 'watch-only'
    assert outside_report_snapshot(sandbox) == before


def test_tripwire_is_global_and_retains_excess_sources(sandbox):
    source(sandbox, 'one')
    source(sandbox, 'two', directory=sandbox[0] / 'two')
    source(sandbox, 'three', directory=sandbox[0] / 'three')
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['new_ticket_limit'] = 1
    sandbox[2].write_text(json.dumps(cfg))
    run = act(sandbox)
    assert [w['operation'] for w in run['work']].count('create_ticket') == 1
    asks = [w for w in run['work'] if w['operation'] == 'ask']
    assert len(asks) == 1 and 'limit reached' in asks[0]['text']
    done = complete(sandbox, run)
    assert sum(len(s['unfiled_items']) for s in done['directories'].values()) == 2
    assert len(list(sandbox[1].glob('*.json'))) == 2


@pytest.mark.parametrize('rule', ['R1', 'R2', 'R5'])
@pytest.mark.parametrize('read_status', [None, 'failed', 'unsupported'])
def test_reads_are_agent_evidence_and_failures_never_file(sandbox, rule, read_status):
    source(sandbox)
    entry = dict(rule=rule, destination='record:existing', reason='Already saved')
    if read_status:
        entry.update(read_status=read_status, error='read unavailable')
    run = act(sandbox, [entry])
    assert not run['work']
    done = complete(sandbox, run)
    assert done['directories'][str(sandbox[0])]['filing_outcomes'][0]['outcome'] == 'read failed'
    assert (sandbox[1] / 'source.json').exists()


@pytest.mark.parametrize('rule,operation', [('R2', 'comment'), ('R7', 'edit_document'), ('R3', 'ask'), ('R4', 'file_slot')])
def test_all_operations_are_planned_and_no_binding_executes(sandbox, rule, operation):
    source(sandbox)
    entry = dict(rule=rule, destination='knowledge' if rule == 'R4' else 'record:existing',
                 read_status='ok', choices=['save', 'leave it'])
    run = act(sandbox, [entry])
    assert run['work'][0]['operation'] == operation
    if rule == 'R4':
        assert run['work'][0]['slot'] == 'knowledge'
    done = complete(sandbox, run)
    assert not done['directories'][str(sandbox[0])]['unfiled_items']
    undo = json.loads(command(sandbox, 'undo', '--run-id', done['run_id'], '--user-started').stdout)
    reversal = read_run(undo['report'])
    if rule != 'R3':
        assert reversal['work'][0]['write_operation'] == operation
    complete(sandbox, reversal, ['reversed'] * len(reversal['work']), 'complete-undo')
    assert not (sandbox[0] / 'binding.sh.called').exists()


@pytest.mark.parametrize('status', ['reversed', 'conflict', 'failed'])
def test_undo_plan_completion_and_retry_only_failed(sandbox, status):
    path = source(sandbox)
    original = path.read_bytes()
    done = complete(sandbox, act(sandbox))
    planned = json.loads(command(sandbox, 'undo', '--run-id', done['run_id'], '--user-started').stdout)
    undo = read_run(planned['report'])
    assert_readable_report(Path(planned['report']).read_text(), undo)
    assert not path.exists()
    assert len(undo['work']) == 1 and undo['archive_restorations']
    restored = complete(sandbox, undo, [status], 'complete-undo')
    assert path.read_bytes() == original
    assert_readable_report(Path(planned['report']).read_text(), restored)
    assert restored['items'][0]['outcome'] == status
    retry = json.loads(command(sandbox, 'undo', '--run-id', done['run_id'], '--user-started').stdout)
    assert len(retry['work']) == (1 if status == 'failed' else 0)


@pytest.mark.parametrize('rewrite', ['same-bytes', 'formatting', 'replacement', 'changed'])
def test_completion_rechecks_source_snapshot(sandbox, rewrite):
    path = source(sandbox)
    run = act(sandbox)
    original = path.read_bytes()
    if rewrite == 'replacement':
        path.unlink()
    if rewrite == 'formatting':
        path.write_text(json.dumps(json.loads(original), indent=2))
    elif rewrite == 'changed':
        data = json.loads(original)
        data['context'] = 'Changed after planning'
        path.write_text(json.dumps(data))
    else:
        path.write_bytes(original)
    done = complete(sandbox, run)
    assert path.exists()
    assert not done['directories'][str(sandbox[0])]['handoffs_archived']


@pytest.mark.parametrize('kind', ['clean', 'dirty', 'unmerged', 'locked', 'main', 'open', 'failed-check'])
@pytest.mark.parametrize('subdirectory', [False, True])
def test_removal_rechecks_and_protects_shared_worktrees(sandbox, kind, subdirectory):
    root, directory = archive_test_repository(sandbox, ('main' if kind == 'main' else 'linked') +
                                               ('-subdirectory' if subdirectory else ''))
    path = source(sandbox, directory=directory, loops=[])
    run = act(sandbox)
    assert root.exists() and path.exists()
    if kind == 'dirty':
        (root / 'untracked').write_bytes(FIXTURE.read_bytes())
    if kind == 'unmerged':
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.test',
                        'commit', '--allow-empty', '-qm', 'work'], check=True)
    if kind == 'locked':
        subprocess.run(['git', '-C', str(root), 'worktree', 'lock', str(root)], check=True)
    if kind in ('open', 'failed-check'):
        check = sandbox[0] / 'check.sh'
        check.write_text('exit 1\n' if kind == 'failed-check' else 'echo live\n')
        source(sandbox, 'live', directory=root / 'docs', loops=[])
        cfg = json.loads(sandbox[2].read_text())
        cfg['sweep']['open_session_checks'] = ['sh ' + str(check)]
        sandbox[2].write_text(json.dumps(cfg))
    done = complete(sandbox, run)
    # A newly discovered protection is honored even after the plan was returned.
    assert root.exists() == (kind != 'clean')
    if kind in ('dirty', 'unmerged', 'locked'):
        assert done['phase'] == 'planned'
        assert any(w['operation'] == 'ask' for w in done['work'])
        done = complete(sandbox, done)
        assert done['phase'] == 'completed'
    if kind == 'clean':
        assert not path.exists()


def test_undo_archive_conflict_preserves_newer_handoff(sandbox):
    path = source(sandbox)
    done = complete(sandbox, act(sandbox))
    source(sandbox, loops=[])
    newer = path.read_bytes()
    payload = json.loads(command(sandbox, 'undo', '--run-id', done['run_id'], '--user-started').stdout)
    undo = read_run(payload['report'])
    result = complete(sandbox, undo, ['conflict'], 'complete-undo')
    assert path.read_bytes() == newer
    assert all(row['outcome'] == 'conflict' for row in result['items'])


def test_pending_slot_returns_an_ask_in_same_run_before_archive(sandbox):
    path = source(sandbox)
    run = act(sandbox, [dict(rule='R4', destination='knowledge')])
    results = sandbox[0] / 'pending.json'
    results.write_text(json.dumps([dict(write_id=run['work'][0]['write_id'], status='failed',
                                        pending=True, error='slot left item pending')]))
    payload = json.loads(command(sandbox, 'complete', '--run-id', run['run_id'], '--results', str(results)).stdout)
    pending = read_run(payload['report'])
    assert pending['phase'] == 'planned'
    assert pending['work'][-1]['operation'] == 'ask'
    assert pending['work'][-1]['identity'] == run['work'][0]['identity']
    assert path.exists()
    done = complete(sandbox, pending, ['failed', 'written'])
    assert not path.exists()
    assert not any(r['kind'] == 'record' for r in done['undo_items'])


def test_interactive_open_session_is_presented_even_with_unbound_ask(sandbox):
    source(sandbox, loops=[])
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['mode'] = 'act'
    sandbox[2].write_text(json.dumps(cfg))
    choices = sandbox[0] / 'choices.json'
    choices.write_text('[]')
    evidence = sandbox[0] / 'open.json'
    evidence.write_text(json.dumps(dict(session_ids=['source'], method='read-only fixture')))
    payload = json.loads(command(sandbox, 'run', '--scope', 'all', '--decisions', str(choices),
                                 '--interactive', '--open-sessions', str(evidence)).stdout)
    run = read_run(payload['report'])
    assert not run['work']
    checked = complete(sandbox, run)
    assert checked['work'][0]['delivery'] == 'direct'
    complete(sandbox, checked)
    payload = json.loads(command(sandbox, 'run', '--scope', 'all', '--decisions', str(choices),
                                 '--interactive', '--open-sessions', str(evidence)).stdout)
    assert not payload['work']
    complete(sandbox, read_run(payload['report']))


def test_store_reservation_survives_report_location_change(sandbox):
    path = source(sandbox)
    run = act(sandbox)
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['report_location'] = str(sandbox[0] / 'other-reports')
    sandbox[2].write_text(json.dumps(cfg))
    command(sandbox, 'run', '--scope', 'all', code=2)
    assert not (sandbox[0] / 'other-reports').exists()
    complete(sandbox, run, [None])
    assert path.exists()
    retry = act(sandbox)
    complete(sandbox, retry, ['already_written'])
    assert not path.exists()


def test_carried_successor_identity_and_existing_archive_are_preserved(sandbox):
    item = json.loads(FIXTURE.read_text())['resume']['open_loops'][0]
    paths = [source(sandbox, 'original', loops=[item]), source(sandbox, 'successor', loops=[item])]
    archive = sandbox[1] / 'archive'
    archive.mkdir()
    existing = archive / paths[0].name
    existing.write_bytes(FIXTURE.read_bytes())
    run = act(sandbox)
    assert run['work'][0]['identity'] == run['work'][1]['identity']
    assert run['work'][0]['write_id'] != run['work'][1]['write_id']
    done = complete(sandbox, run, ['written', 'already_written'])
    assert not any(p.exists() for p in paths)
    assert existing.read_bytes() == FIXTURE.read_bytes()
    assert len(done['directories'][str(sandbox[0])]['new_tickets']) == 1
    assert len([r for r in done['undo_items'] if r['kind'] == 'record']) == 1


@pytest.mark.parametrize('bad', ['duplicate', 'unknown', 'malformed-receipt', 'bad-status'])
def test_invalid_results_leave_the_intent_and_source_reserved(sandbox, bad):
    source(sandbox)
    run = act(sandbox)
    row = dict(write_id=run['work'][0]['write_id'], status='written', receipt='ack', destination='record:created')
    if bad == 'unknown':
        row['write_id'] = 'unknown'
    elif bad == 'malformed-receipt':
        row['receipt'] = ''
    elif bad == 'bad-status':
        row['status'] = 'success'
    path = sandbox[0] / 'invalid-results.json'
    path.write_text(json.dumps([row, row] if bad == 'duplicate' else [row]))
    command(sandbox, 'complete', '--run-id', run['run_id'], '--results', str(path), code=1)
    command(sandbox, 'run', '--scope', 'all', code=2)
    assert read_run(sandbox[0] / 'reports' / (run['run_id'] + '.md'))['work'][0]['outcome'] == 'intent'
    complete(sandbox, run, [None])


def test_undo_reserves_the_store_until_its_results_arrive(sandbox):
    source(sandbox)
    run = complete(sandbox, act(sandbox))
    command(sandbox, 'undo', '--run-id', run['run_id'], code=1)
    payload = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    command(sandbox, 'run', '--scope', 'all', code=2)
    # Reopening a pending undo returns its original work, without performing it.
    repeated = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    assert payload['work'] == repeated['work']
    complete(sandbox, read_run(payload['report']), ['reversed'], 'complete-undo')
    command(sandbox, 'run', '--scope', 'all')


@pytest.mark.parametrize('status', ['failed', 'uncertain', None, 'already_written'])
def test_undo_excludes_unconfirmed_and_preexisting_writes(sandbox, status):
    source(sandbox)
    run = complete(sandbox, act(sandbox), [status])
    payload = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    assert not payload['work']
    complete(sandbox, read_run(payload['report']), [], 'complete-undo')


@pytest.mark.parametrize('change', ['missing', 'modified', 'replacement'])
def test_undo_preserves_missing_or_changed_archives(sandbox, change):
    source(sandbox)
    run = complete(sandbox, act(sandbox))
    target = next(Path(r['archive']) for r in run['undo_items'] if r['kind'] == 'handoff')
    raw = target.read_bytes()
    if change in ('missing', 'replacement'):
        target.unlink()
    if change == 'replacement':
        target.write_bytes(raw)
    elif change == 'modified':
        target.write_bytes(raw + b'\n')
    payload = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    result = complete(sandbox, read_run(payload['report']), ['reversed'], 'complete-undo')
    archived = next(r for r in result['items'] if r['kind'] == 'handoff')
    assert archived['outcome'] == ('failed' if change == 'missing' else 'conflict')


@pytest.mark.parametrize('status', ['failed', 'uncertain', None])
def test_unconfirmed_asks_keep_sources(sandbox, status):
    path = source(sandbox)
    run = act(sandbox, [dict(rule='R3', destination='ask', choices=['save', 'leave it'])])
    done = complete(sandbox, run, [status])
    assert path.exists()
    assert not done['directories'][str(sandbox[0])]['handoffs_archived']


def test_recorded_dirty_files_are_named_and_keep_source_after_delivered_ask(sandbox):
    path = source(sandbox, loops=[])
    data = json.loads(path.read_text())
    data['uncommitted_files'] = [str(sandbox[0] / 'changed.txt')]
    path.write_text(json.dumps(data))
    import time
    os.utime(path, (time.time() - 5 * 86400,) * 2)
    run = act(sandbox)
    work, = run['work']
    assert work['operation'] == 'ask'
    assert all(value in work['text'] for value in ('source', str(sandbox[0]), 'changed.txt'))
    done = complete(sandbox, run)
    assert path.exists() and done['directories'][str(sandbox[0])]['handoffs_kept']


def test_act_and_undo_change_only_declared_surfaces(sandbox):
    path = source(sandbox)
    raw = path.read_bytes()
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['mode'] = 'act'
    sandbox[2].write_text(json.dumps(cfg))
    profile = bound_profile(sandbox)
    args = decisions(sandbox, [new_work()])
    results = sandbox[0] / 'surface-results.json'
    results.write_text('[]')
    before = outside_report_snapshot(sandbox)
    payload = json.loads(command(sandbox, 'run', '--scope', 'all', *args, '--user-profile', str(profile)).stdout)
    run = read_run(payload['report'])
    after = outside_report_snapshot(sandbox)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    assert changed == {'.handoffs.sweep-pending.json'}
    work = run['work'][0]
    results.write_text(json.dumps([dict(write_id=work['write_id'], status='written', receipt='ack', destination='record:new')]))
    before = outside_report_snapshot(sandbox)
    command(sandbox, 'complete', '--run-id', run['run_id'], '--results', str(results))
    after = outside_report_snapshot(sandbox)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    # Directory metadata is excluded by the snapshot helper; contents and file times are checked.
    assert changed == {'.handoffs.sweep-pending.json', 'handoffs/source.json',
                       'handoffs/archive/source.json'}
    payload = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    undo = read_run(payload['report'])
    results.write_text(json.dumps([dict(write_id=undo['work'][0]['write_id'], status='reversed')]))
    before = outside_report_snapshot(sandbox)
    command(sandbox, 'complete-undo', '--run-id', run['run_id'], '--results', str(results))
    after = outside_report_snapshot(sandbox)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    assert changed == {'.handoffs.sweep-pending.json', 'handoffs/source.json', 'handoffs/archive/source.json'}
    assert path.read_bytes() == raw
    assert not (sandbox[0] / 'binding.sh.called').exists()


def test_completion_stops_cleanup_when_transcript_discovery_becomes_unsafe(sandbox):
    root, directory = archive_test_repository(sandbox, 'linked')
    path = source(sandbox, directory=directory, loops=[])
    run = act(sandbox)
    sessions = Path(sandbox[3]['CODEX_HOME']) / 'sessions'
    sessions.parent.mkdir(parents=True)
    relocated = sandbox[0] / 'relocated'
    relocated.mkdir()
    sessions.symlink_to(relocated, target_is_directory=True)
    result = complete(sandbox, run)
    assert root.exists() and path.exists()
    assert any(error.get('blocks_sweep') for error in result['errors'])


def test_newly_discovered_old_sibling_with_unfiled_work_protects_worktree(sandbox):
    root, directory = archive_test_repository(sandbox, 'linked')
    source(sandbox, directory=directory, loops=[])
    run = act(sandbox)
    sibling = root / 'docs'
    sibling.mkdir()
    path = source(sandbox, 'newly-discovered', directory=sibling)
    result = complete(sandbox, run)
    assert root.exists() and path.exists()
    assert not any(section['worktrees_removed'] for section in result['directories'].values())


def test_undo_recovers_restoration_after_lost_report_save(sandbox):
    path = source(sandbox)
    run = complete(sandbox, act(sandbox))
    payload = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    result = complete(sandbox, read_run(payload['report']), ['reversed'], 'complete-undo')
    for row in result['items']:
        if row['kind'] == 'handoff':
            row['outcome'] = 'failed'
    Path(payload['report']).write_text('```json\n' + json.dumps(result) + '\n```\n')
    payload = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    result = complete(sandbox, read_run(payload['report']), [], 'complete-undo')
    assert path.exists()
    assert all(row['outcome'] == 'reversed' for row in result['items'])


@pytest.mark.parametrize('matches', [['record:one'], ['record:one', 'record:two']])
def test_agent_search_evidence_names_matches_in_the_report(sandbox, matches):
    source(sandbox)
    entry = (dict(rule='R2', destination=matches[0], read_status='ok', matches=matches)
             if len(matches) == 1 else dict(rule='R3', destination='ask', matches=matches,
                                            choices=['use ' + match for match in matches]))
    run = act(sandbox, [entry])
    work, = run['work']
    assert work['operation'] == ('comment' if len(matches) == 1 else 'ask')
    done = complete(sandbox, run)
    row = done['directories'][str(sandbox[0])]['filing_outcomes'][0]
    assert row['matches'] == matches
    if len(matches) == 1:
        assert row['destination'] == matches[0]
    else:
        assert all(match in ' '.join(row['choices']) for match in matches)


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('merged_after_filing', [False, True])
def test_retention_asks_wait_for_post_write_eligibility(sandbox, bound, merged_after_filing):
    from test_sweep import act_profile
    root, directory = archive_test_repository(sandbox, 'linked')
    source(sandbox, directory=directory)
    git = lambda *args: subprocess.run(['git', '-C', str(root), *args],
                                      check=True, text=True, capture_output=True)
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.test',
        'commit', '--allow-empty', '-qm', 'work')
    profile = act_profile(sandbox)
    if not bound:
        data = json.loads(profile.read_text())
        data.pop('ask')
        profile.write_text(json.dumps(data))
    args = decisions(sandbox, [new_work()])
    payload = json.loads(command(sandbox, 'run', '--scope', 'all', *args,
                                 '--user-profile', str(profile)).stdout)
    run = read_run(payload['report'])
    assert [row['operation'] for row in run['work']] == ['create_ticket']
    assert not run['directories'][str(directory)]['asks_raised']
    if merged_after_filing:
        git('push', 'origin', 'HEAD:main')
    checked = complete(sandbox, run)
    section = checked['directories'][str(directory)]
    if merged_after_filing:
        assert not root.exists()
        assert not section['asks_raised']
        assert checked['phase'] == 'completed'
    else:
        assert root.exists()
        ask, = section['asks_raised']
        assert 'not contained' in ask['ask']['text']
        assert ask['outcome'] == ('intent' if bound else 'unbound')
        assert checked['phase'] == ('planned' if bound else 'completed')
        if bound:
            finished = complete(sandbox, checked)
            assert len(finished['directories'][str(directory)]['asks_raised']) == 1


@pytest.mark.parametrize('change', ['closed', 'active', 'unchanged', 'new-idle-activity'])
@pytest.mark.parametrize('legacy_plan', [False, True])
def test_open_session_ask_uses_post_write_checks_and_activity(sandbox, change, legacy_plan):
    from test_sweep import configure_checks
    path = source(sandbox, loops=[])
    open_ids = sandbox[0] / 'open-ids.txt'
    open_ids.write_text('source\n')
    configure_checks(sandbox, ['cat ' + str(open_ids)])
    run = act(sandbox)
    assert not run['work']
    assert not run['directories'][str(sandbox[0])]['asks_raised']
    if legacy_plan:
        run['discovery'].pop('open_session_evidence')
        journal = sandbox[0] / 'reports' / (run['run_id'] + '.md')
        journal.write_text('```json\n' + json.dumps(run) + '\n```\n')
    if change == 'closed':
        open_ids.write_text('')
    elif change == 'active':
        os.utime(path, None)
    elif change == 'new-idle-activity':
        activity = path.stat().st_mtime + 60
        os.utime(path, (activity, activity))
    checked = complete(sandbox, run)
    section = checked['directories'][str(sandbox[0])]
    if change in ('closed', 'active'):
        assert not section['asks_raised']
        assert checked['phase'] == 'completed'
        if change == 'closed':
            assert not section['open_sessions']
    else:
        ask, = section['asks_raised']
        assert checked['phase'] == 'planned'
        assert ask['activity_at'] == path.stat().st_mtime
        finished = complete(sandbox, checked)
        assert finished['phase'] == 'completed'
        history = json.loads((sandbox[0] / 'reports/open-session-asks.json').read_text())
        assert history['source'] == path.stat().st_mtime


def test_completion_accepts_refreshed_agent_session_evidence(sandbox):
    source(sandbox, loops=[])
    cfg = json.loads(sandbox[2].read_text())
    cfg['sweep']['mode'] = 'act'
    sandbox[2].write_text(json.dumps(cfg))
    choices = sandbox[0] / 'choices.json'
    choices.write_text('[]')
    evidence = sandbox[0] / 'open.json'
    evidence.write_text(json.dumps(dict(session_ids=['source'], method='initial inspection')))
    payload = json.loads(command(sandbox, 'run', '--scope', 'all', '--decisions', str(choices),
                                 '--interactive', '--open-sessions', str(evidence)).stdout)
    assert not payload['work']
    evidence.write_text(json.dumps(dict(session_ids=[], method='post-write inspection')))
    results = sandbox[0] / 'results.json'
    results.write_text('[]')
    payload = json.loads(command(sandbox, 'complete', '--run-id', payload['run_id'], '--results', str(results),
                                 '--open-sessions', str(evidence)).stdout)
    checked = read_run(payload['report'])
    assert checked['phase'] == 'completed' and not checked['work']
    assert not checked['directories'][str(sandbox[0])]['open_sessions']
    assert checked['open_session_checks'][0]['method'] == 'post-write inspection'
