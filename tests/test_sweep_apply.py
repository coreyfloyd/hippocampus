"""A sweep with the auto-apply setting on, driven through its command line with stub bindings."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from test_auto_apply_lessons import clone_pair, git, move_remote
from test_sweep import ENGINE, assert_readable_report, command, decisions, read_run, sandbox, source  # noqa: F401

PRODUCER = 'abandoned-session'


@pytest.fixture(params=['claude', 'codex'])
def tool(request, sandbox):
    """The same run under each tool; only the tool's own environment differs."""
    base = sandbox[0]
    sandbox[3].update(HIPPOCAMPUS_ROUTING=str(base / 'routing.md'), CLAUDE_CONFIG_DIR=str(base / 'claude'),
                      HIPPOCAMPUS_HARNESS=request.param, CODEX_THREAD_ID='driver' if request.param == 'codex' else '')
    (base / 'routing.md').write_text('# Routing\n')
    return request.param


def configure(sandbox, mode='act', setting=True):
    config = json.loads(sandbox[2].read_text())
    config['sweep']['mode'] = mode
    config.pop('auto_apply_lessons', None)
    if setting:
        config['auto_apply_lessons'] = True
    sandbox[2].write_text(json.dumps(config))


def profile(sandbox, persist=True, ask=True):
    data = {'name': 'test'}
    if ask:
        data['ask'] = {'command': '/ask'}
    if persist:
        data['bindings'] = {'persist': {'command': '/persist', 'consumes': []}}
    path = sandbox[0] / 'profile.json'
    path.write_text(json.dumps(data))
    return path


def lesson(text='Run the suite before reporting ready.', **changes):
    return {'type': 'lesson', 'session_id': PRODUCER, 'produced_at': '2026-11-01T12:00:00Z',
            'disposition': 'route through improve-harness', 'context': text, **changes}


def knowledge(text='Pickup reads sibling worktrees first.', **changes):
    return {'type': 'knowledge', 'session_id': PRODUCER, 'produced_at': '2026-11-01T12:00:00Z',
            'disposition': 'route through knowledge-capture', 'context': text, **changes}


def assessment(target, new='Run the suite first.\n', **changes):
    return {'recommend': 'apply', 'target': str(target), 'change': 'Add the suite rule',
            'evidence': 'A generator reported ready with failing tests.', 'edits': [{'new': new}], **changes}


def start(sandbox, destination='lessons', persist=True, ask=True):
    args = decisions(sandbox, [dict(rule='R4', destination=destination)])
    result = command(sandbox, 'run', '--scope', 'all', *args, '--user-profile', str(profile(sandbox, persist, ask)))
    return json.loads(result.stdout)


def finish(sandbox, payload, answer, *extra):
    """Stand in for the agent: answer each round's new intents until the run completes."""
    path = Path(payload['report'])
    rounds = []
    for _ in range(5):
        run = read_run(path)
        rows = [answer(work) for work in run['work'] if work['outcome'] == 'intent']
        rounds.append([row for row in run['work'] if row['outcome'] == 'intent'])
        results = sandbox[0] / 'results.json'
        results.write_text(json.dumps([row for row in rows if row]))
        command(sandbox, 'complete', '--run-id', run['run_id'], '--results', str(results), *extra)
        run = read_run(path)
        if run['phase'] == 'completed':
            assert_readable_report(path.read_text(), run)
            return run, rounds
    raise AssertionError('the run never completed')


def agent(lesson_row=None, knowledge_row=None):
    def answer(work):
        result = {'write_id': work['write_id']}
        if work['operation'] == 'apply_lesson':
            return {**result, 'status': 'assessed', 'lesson': lesson_row}
        if work['operation'] == 'apply_knowledge':
            return {**result, 'status': 'assessed', 'knowledge': knowledge_row}
        return {**result, 'status': 'written', 'receipt': 'receipt-' + work['operation'],
                'destination': work['operation']}
    return answer


def section(sandbox, run):
    return run['directories'][str(sandbox[0])]


def archived(sandbox, name='source'):
    return (sandbox[1] / 'archive' / (name + '.json')).exists() and not (sandbox[1] / (name + '.json')).exists()


def commits(checkout):
    return int(git(checkout, 'rev-list', '--count', 'HEAD'))


def test_carried_lesson_is_applied_pushed_and_its_handoff_archived(sandbox, tool):
    checkout, remote, _ = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    payload = start(sandbox)
    work, = payload['work']
    assert work['operation'] == 'apply_lesson' and work['native_step'] == 'lessons'
    assert work['command'].endswith('improve-harness')
    assert 'Run the suite first.' not in (checkout / 'rules.md').read_text()
    run, rounds = finish(sandbox, payload, agent(assessment(checkout / 'rules.md')))
    assert [[row['operation'] for row in group] for group in rounds] == [['apply_lesson'], ['persist']]
    assert rounds[1][0]['command'] == '/persist' and rounds[1][0]['checkouts'] == [str(checkout.resolve())]
    row, = section(sandbox, run)['lessons_applied']
    head = git(checkout, 'rev-parse', 'HEAD')
    assert row['outcome'] == 'written' and row['delivery'] == 'pushed'
    assert row['receipt'] == row['commit'] == head == git(remote, 'rev-parse', 'main')
    assert row['destination'] == str((checkout / 'rules.md').resolve())
    assert git(checkout, 'log', '-1', '--format=%s') == 'lesson: Add the suite rule'
    assert archived(sandbox, PRODUCER)
    assert head in Path(payload['report']).read_text().split('```json')[0]


def test_skipped_lesson_is_dropped_and_the_handoff_archived(sandbox, tool):
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    run, rounds = finish(sandbox, start(sandbox), agent({'recommend': 'skip', 'reason': 'Future impact is noise'}))
    assert len(rounds) == 1
    row, = section(sandbox, run)['items_dropped']
    assert row['outcome'] == 'dropped' and row['reason'] == 'Future impact is noise'
    assert archived(sandbox, PRODUCER)


def test_target_outside_git_has_its_path_as_receipt_and_needs_no_persist(sandbox, tool):
    target = sandbox[0] / 'notes.md'
    target.write_text('# Notes\n')
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    run, rounds = finish(sandbox, start(sandbox, persist=False), agent(assessment(target)))
    row, = section(sandbox, run)['lessons_applied']
    assert row['receipt'] == str(target.resolve()) and 'commit' not in row
    assert 'Run the suite first.' in target.read_text() and len(rounds) == 1
    assert archived(sandbox, PRODUCER)


def test_watch_only_applies_nothing_and_reports_what_it_would_apply(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox, mode='watch-only')
    before, head = (checkout / 'rules.md').read_text(), git(checkout, 'rev-parse', 'HEAD')
    args = decisions(sandbox, [dict(rule='R4', destination='lessons')])
    report = Path(command(sandbox, 'run', '--scope', 'all', *args, '--user-profile', str(profile(sandbox))).stdout.strip())
    run = read_run(report)
    row, = section(sandbox, run)['would_apply']
    assert row['outcome'] == 'would apply' and row['identity']['text'] == lesson()['context']
    assert '### Would apply' in report.read_text() and 'Watch-only' in report.read_text()
    assert (checkout / 'rules.md').read_text() == before and git(checkout, 'rev-parse', 'HEAD') == head
    assert path.exists() and not (sandbox[0] / 'handoff-ledger').exists()


@pytest.mark.parametrize('item,destination', [(lesson(), 'lessons'), (knowledge(), 'knowledge')])
def test_setting_off_carries_as_today(sandbox, tool, item, destination):
    path = source(sandbox, PRODUCER, loops=[item])
    configure(sandbox, setting=False)
    payload = start(sandbox, destination)
    work, = payload['work']
    assert work['operation'] == 'native_step' and work['unattended'] is True
    run, _ = finish(sandbox, payload, lambda work: {'write_id': work['write_id'], 'status': 'carried'})
    text = Path(payload['report']).read_text()
    assert section(sandbox, run)['filing_outcomes'][0]['outcome'] == 'carried'
    assert path.exists() and 'auto_apply' not in run and 'persist_binding' not in run
    assert 'lessons_applied' not in section(sandbox, run)
    assert '### Would apply' not in text and '### Lessons applied' not in text


def test_routing_file_that_requires_proposals_carries_lessons_and_says_why(sandbox, tool):
    (sandbox[0] / 'routing.md').write_text('lesson-policy: propose\n')
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    payload = start(sandbox)
    work, = payload['work']
    assert work['operation'] == 'native_step' and 'routing file' in work['reason']
    run, _ = finish(sandbox, payload, lambda work: {'write_id': work['write_id'], 'status': 'carried'})
    assert run['auto_apply']['lessons'] == 'propose' and path.exists()


def reject_pushes(remote):
    hook = remote / 'hooks/pre-receive'
    hook.write_text('#!/bin/sh\necho "remote: refused by test" >&2\nexit 1\n')
    hook.chmod(0o755)
    return hook


def test_a_push_that_still_fails_keeps_the_handoff_and_a_rerun_never_applies_twice(sandbox, tool):
    checkout, remote, _ = clone_pair(sandbox[0])
    hook = reject_pushes(remote)
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    count = commits(checkout)
    run, _ = finish(sandbox, start(sandbox), agent(assessment(checkout / 'rules.md')))
    row, = section(sandbox, run)['lessons_not_pushed']
    commit = git(checkout, 'rev-parse', 'HEAD')
    assert row['commit'] == commit and row['outcome'] == 'not pushed'
    assert row['delivery'] == 'committed, not pushed' and 'refused by test' in row['error']
    assert path.exists() and not section(sandbox, run)['lessons_applied']
    kept, = section(sandbox, run)['handoffs_kept']
    assert commit in kept['reason'] and 'refused by test' in kept['reason']
    hook.unlink()
    # The rerun finds the receipt in the ledger: no assessment, one push, no second commit.
    payload = start(sandbox)
    assert payload['work'] == []
    run, rounds = finish(sandbox, payload, agent())
    assert [[row['operation'] for row in group] for group in rounds] == [[], ['persist']]
    assert commits(checkout) == count + 1 and git(remote, 'rev-parse', 'main') == commit
    assert section(sandbox, run)['already_settled'][0]['delivery'] == 'pushed'
    assert not section(sandbox, run)['lessons_applied']
    assert archived(sandbox, PRODUCER)


def test_remote_that_moved_is_brought_in_and_pushed_once(sandbox, tool):
    checkout, remote, other = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    payload = start(sandbox)
    move_remote(other)
    run, _ = finish(sandbox, payload, agent(assessment(checkout / 'rules.md')))
    row, = section(sandbox, run)['lessons_applied']
    assert (row['delivery'], row['attempts']) == ('pushed', 2)
    assert git(remote, 'merge-base', '--is-ancestor', row['commit'], 'main') == ''
    assert archived(sandbox, PRODUCER)


def test_persist_unbound_reports_the_commit_and_keeps_the_handoff(sandbox, tool):
    checkout, remote, _ = clone_pair(sandbox[0])
    pushed = git(remote, 'rev-parse', 'main')
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    run, rounds = finish(sandbox, start(sandbox, persist=False), agent(assessment(checkout / 'rules.md')))
    row, = section(sandbox, run)['lessons_not_pushed']
    assert row['commit'] == git(checkout, 'rev-parse', 'HEAD') and 'persist is unbound' in row['error']
    assert len(rounds) == 1 and path.exists() and git(remote, 'rev-parse', 'main') == pushed


@pytest.mark.parametrize('status,expected', [('failed', 'persist stub failed'), ('uncertain', 'persist stub failed'),
                                             (None, 'missing result')])
def test_delivery_waits_for_a_confirmed_persist(sandbox, tool, status, expected):
    checkout, remote, _ = clone_pair(sandbox[0])
    pushed = git(remote, 'rev-parse', 'main')
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    base = agent(assessment(checkout / 'rules.md'))

    def answer(work):
        if work['operation'] != 'persist':
            return base(work)
        return {'write_id': work['write_id'], 'status': status, 'error': 'persist stub failed'} if status else None

    payload = start(sandbox)
    run, _ = finish(sandbox, payload, answer)
    row, = section(sandbox, run)['lessons_not_pushed']
    assert row['commit'] == git(checkout, 'rev-parse', 'HEAD') and expected in row['error']
    assert git(remote, 'rev-parse', 'main') == pushed and path.exists()
    assert expected in Path(payload['report']).read_text().split('```json')[0]
    # The commit is not lost: the next run confirms persist and delivers it once.
    run, _ = finish(sandbox, start(sandbox), agent())
    assert git(remote, 'rev-parse', 'main') == row['commit'] and archived(sandbox, PRODUCER)


def test_undo_lists_lesson_commits_and_reverts_none(sandbox, tool):
    checkout, remote, _ = clone_pair(sandbox[0])
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    run, _ = finish(sandbox, start(sandbox), agent(assessment(checkout / 'rules.md')))
    commit = git(checkout, 'rev-parse', 'HEAD')
    assert all(row['kind'] == 'handoff' for row in run['undo_items'])
    undo = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    assert undo['work'] == []
    listed, = undo['applied_left_in_place']
    assert listed['commit'] == commit and listed['applied_kind'] == 'lesson'
    results = sandbox[0] / 'undo-results.json'
    results.write_text('[]')
    done = json.loads(command(sandbox, 'complete-undo', '--run-id', run['run_id'], '--results', str(results)).stdout)
    assert commit in Path(done['report']).read_text().split('```json')[0]
    assert path.exists() and 'Run the suite first.' in (checkout / 'rules.md').read_text()
    assert git(checkout, 'rev-parse', 'HEAD') == commit == git(remote, 'rev-parse', 'main')
    # The restored handoff never applies its lesson again.
    payload = start(sandbox)
    assert payload['work'] == []
    finish(sandbox, payload, agent())
    assert git(checkout, 'rev-parse', 'HEAD') == commit and archived(sandbox, PRODUCER)


def always_loaded(sandbox, ask=True):
    checkout, _, _ = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[lesson(choices=['approve', 'decline'])])
    configure(sandbox)
    return finish(sandbox, start(sandbox, ask=ask), agent(assessment(checkout / 'rules.md', always_loaded=True))), checkout


def test_always_loaded_lesson_raises_a_text_ask_naming_the_pushed_commit(sandbox, tool):
    (run, rounds), checkout = always_loaded(sandbox)
    ask, = rounds[2]
    assert ask['operation'] == 'ask' and ask['choices'] == []
    assert git(checkout, 'rev-parse', 'HEAD') in ask['ask']['text'] and 'already applied' in ask['ask']['text']
    assert archived(sandbox, PRODUCER)


def test_always_loaded_lesson_without_an_ask_binding_keeps_its_handoff(sandbox, tool):
    (run, _), _ = always_loaded(sandbox, ask=False)
    assert section(sandbox, run)['asks_raised'][0]['outcome'] == 'unbound'
    assert (sandbox[1] / (PRODUCER + '.json')).exists()


def test_two_handoffs_carrying_one_lesson_apply_it_once(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[lesson()])
    source(sandbox, 'successor', loops=[lesson()])
    configure(sandbox)
    count = commits(checkout)
    payload = start(sandbox)
    assert len(payload['work']) == 2
    first = agent(assessment(checkout / 'rules.md'))
    run, _ = finish(sandbox, payload, first)
    assert commits(checkout) == count + 1
    assert (checkout / 'rules.md').read_text().count('Run the suite first.') == 1
    assert archived(sandbox, PRODUCER) and archived(sandbox, 'successor')
    # The second handoff only found the first one's outcome, so this run applied one lesson.
    assert len(section(sandbox, run)['lessons_applied']) == 1
    assert len(section(sandbox, run)['already_settled']) == 1
    undo = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    assert len(undo['applied_left_in_place']) == 1


def seed_ledger(sandbox, session, *rows):
    ledger = sandbox[0] / 'handoff-ledger'
    ledger.mkdir(exist_ok=True)
    with (ledger / f'session-touched-paths.{session}.jsonl').open('a') as handle:
        for row in rows:
            handle.write(json.dumps(row) + '\n')


def wrap_outcome(checkout):
    return {'kind': 'lesson_outcome', 'outcome': {
        'identity': [PRODUCER, lesson()['produced_at'], 'lesson', lesson()['context']], 'status': 'applied',
        'target': str(checkout / 'rules.md'), 'commit': git(checkout, 'rev-parse', 'HEAD'), 'delivery': 'pushed'}}


@pytest.mark.parametrize('ledger', ['successor', 'a-third-session'])
def test_lesson_a_wrap_applied_is_found_in_any_ledger_and_reported_as_settled(sandbox, tool, ledger):
    checkout, _, _ = clone_pair(sandbox[0])
    source(sandbox, 'successor', loops=[lesson()])
    configure(sandbox)
    row = wrap_outcome(checkout)
    seed_ledger(sandbox, ledger, row)
    seed_ledger(sandbox, 'unreadable-session', {'kind': 'lesson_outcome', 'outcome': {'status': 'applied'}})
    payload = start(sandbox)
    assert payload['work'] == []
    run, _ = finish(sandbox, payload, agent())
    settled, = section(sandbox, run)['already_settled']
    assert settled['receipt'] == row['outcome']['commit'] and settled['outcome'] == 'already_written'
    assert not section(sandbox, run)['lessons_applied']
    assert '### Already settled' in Path(payload['report']).read_text()
    assert archived(sandbox, 'successor')
    undo = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    assert 'applied_left_in_place' not in undo


def test_capture_a_wrap_recorded_is_reported_as_settled_and_undo_never_lists_it(sandbox, tool):
    source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    seed_ledger(sandbox, PRODUCER, {'kind': 'knowledge_outcome', 'outcome': {
        'identity': [PRODUCER, knowledge()['produced_at'], 'knowledge', knowledge()['context']],
        'status': 'captured', 'capture': 'wiki', 'context': knowledge()['context'],
        'created': ['wiki/topic.md'], 'updated': []}})
    payload = start(sandbox, 'knowledge')
    assert payload['work'] == []
    run, _ = finish(sandbox, payload, agent())
    assert section(sandbox, run)['already_settled'][0]['receipt'] == 'wiki/topic.md'
    assert not section(sandbox, run)['knowledge_captured'] and archived(sandbox, PRODUCER)
    assert 'applied_left_in_place' not in json.loads(
        command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)


def test_open_session_evidence_survives_the_rounds_that_deliver_lessons(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    evidence = sandbox[0] / 'evidence.json'
    evidence.write_text(json.dumps({'session_ids': [PRODUCER], 'method': 'stub inspection'}))
    payload = start(sandbox)
    work, = payload['work']
    results = sandbox[0] / 'first.json'
    results.write_text(json.dumps([agent(assessment(checkout / 'rules.md'))(work)]))
    command(sandbox, 'complete', '--run-id', payload['run_id'], '--results', str(results),
            '--open-sessions', str(evidence))
    # The next call passes no evidence, as the skill's persist round may.
    finish(sandbox, payload, agent())
    assert path.exists()


def in_process(sandbox, monkeypatch):
    """The engine in this process, so a test can make one step of it fail."""
    for key, value in sandbox[3].items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location('sweep_under_test', ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_in_process(sandbox, module, payload, rows, *extra):
    results = sandbox[0] / 'in-process.json'
    results.write_text(json.dumps(rows))
    assert module.main(['complete', '--run-id', payload['run_id'], '--results', str(results), *extra]) == 0
    return read_run(Path(payload['report']))


def fail_with(error):
    def fail(*_args, **_kwargs):
        raise error
    return fail


@pytest.mark.parametrize('step', ['touched_checkouts', 'settle_session_items'])
def test_error_after_the_commit_does_not_report_a_failure_or_stop_delivery(sandbox, tool, monkeypatch, step):
    checkout, remote, _ = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    payload = start(sandbox)
    work, = payload['work']
    module = in_process(sandbox, monkeypatch)
    monkeypatch.setattr(module.handoff, step, fail_with(OSError('ledger step failed')))
    run = complete_in_process(sandbox, module, payload, [agent(assessment(checkout / 'rules.md'))(work)])
    row = section(sandbox, run)['filing_outcomes'][0]
    assert row['outcome'] == 'applied' and row['commit'] == git(checkout, 'rev-parse', 'HEAD')
    assert 'ledger step failed' in row['warning'] and 'error' not in row
    monkeypatch.undo()
    run, _ = finish(sandbox, payload, agent())
    assert section(sandbox, run)['lessons_applied'][0]['delivery'] == 'pushed'
    assert git(remote, 'rev-parse', 'main') == row['commit'] and archived(sandbox, PRODUCER)


@pytest.mark.parametrize('error', [RuntimeError('boom'), StopIteration(), IndexError('boom')])
def test_any_assessment_error_fails_only_its_own_item(sandbox, tool, monkeypatch, error):
    _, extra = knowledge_root(sandbox)
    source(sandbox, PRODUCER, loops=[knowledge('First.'), knowledge('Second.')])
    configure(sandbox)
    payload = start(sandbox, 'knowledge')
    module = in_process(sandbox, monkeypatch)
    real = module.checklist.knowledge.apply
    calls = []

    def apply(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(module.checklist.knowledge, 'apply', apply)
    rows = [agent(knowledge_row=FACT)(work) for work in payload['work']]
    run = complete_in_process(sandbox, module, payload, rows, *extra)
    first, second = section(sandbox, run)['filing_outcomes']
    assert first['outcome'] == 'failed' and second['binding'] == 'ask' and len(calls) == 2


def test_outcome_missing_from_the_module_fails_its_item(sandbox, tool, monkeypatch):
    source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    payload = start(sandbox, 'knowledge')
    module = in_process(sandbox, monkeypatch)
    monkeypatch.setattr(module.checklist.knowledge, 'apply', lambda *a, **k: {'knowledge_outcomes': []})
    rows = [agent(knowledge_row=FACT)(work) for work in payload['work']]
    run = complete_in_process(sandbox, module, payload, rows)
    assert 'recorded no outcome' in section(sandbox, run)['filing_outcomes'][0]['error']


@pytest.mark.parametrize('error', [OSError('ledger gone'), RuntimeError('boom')])
def test_delivery_error_reports_the_commit_and_finishes_the_run(sandbox, tool, monkeypatch, error):
    checkout, _, _ = clone_pair(sandbox[0])
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    payload = start(sandbox)
    work, = payload['work']
    module = in_process(sandbox, monkeypatch)
    run = complete_in_process(sandbox, module, payload, [agent(assessment(checkout / 'rules.md'))(work)])
    persist = next(row for row in run['work'] if row['operation'] == 'persist')
    monkeypatch.setattr(module.checklist.lessons, 'deliver', fail_with(error))
    run = complete_in_process(sandbox, module, payload, [agent()(persist)])
    assert run['phase'] == 'completed' and path.exists()
    row, = section(sandbox, run)['lessons_not_pushed']
    assert str(error) in row['error'] and row['commit'] == git(checkout, 'rev-parse', 'HEAD')


def test_malformed_routing_fails_only_lessons_in_act_mode(sandbox, tool):
    (sandbox[0] / 'routing.md').write_text('lesson-policy: sometimes\n')
    root, extra = knowledge_root(sandbox)
    lesson_path = source(sandbox, PRODUCER, loops=[lesson(), knowledge()])
    configure(sandbox)
    args = decisions(sandbox, [dict(rule='R4', destination='lessons'), dict(rule='R4', destination='knowledge')])
    payload = json.loads(command(sandbox, 'run', '--scope', 'all', *args, '--user-profile', str(profile(sandbox))).stdout)
    assert sorted(work['operation'] for work in payload['work']) == ['apply_knowledge', 'native_step']
    (root / 'raw/derived/a.md').write_text('# A\n')

    def answer(work):
        if work['operation'] == 'native_step':
            return {'write_id': work['write_id'], 'status': 'carried'}
        return agent(knowledge_row={'capture': 'source', 'created': ['raw/derived/a.md']})(work)

    run, _ = finish(sandbox, payload, answer, *extra)
    assert 'lesson-policy' in run['errors'][0]['reason'] and run['auto_apply']['lessons'] == 'failed'
    assert len(section(sandbox, run)['knowledge_captured']) == 1 and lesson_path.exists()
    native = next(row for row in section(sandbox, run)['filing_outcomes'] if row.get('native_step') == 'lessons')
    assert 'lesson-policy' in native['reason']


@pytest.mark.parametrize('break_it', ['routing', 'setting'])
def test_unreadable_auto_apply_input_still_writes_a_watch_report(sandbox, tool, break_it):
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox, mode='watch-only')
    if break_it == 'routing':
        (sandbox[0] / 'routing.md').write_text('lesson-policy: sometimes\n')
    else:
        config = json.loads(sandbox[2].read_text())
        config['auto_apply_lessons'] = 'yes'
        sandbox[2].write_text(json.dumps(config))
    args = decisions(sandbox, [dict(rule='R4', destination='lessons')])
    report = Path(command(sandbox, 'run', '--scope', 'all', *args, '--user-profile', str(profile(sandbox))).stdout.strip())
    run = read_run(report)
    assert run['errors'][0]['path'] == 'auto-apply' and 'auto-apply' in report.read_text().split('```json')[0]
    assert not section(sandbox, run)['would_apply']


def test_delivered_ask_about_a_fact_is_settled_for_the_next_run(sandbox, tool):
    checkout, remote, _ = clone_pair(sandbox[0])
    hook = reject_pushes(remote)
    _, extra = knowledge_root(sandbox)
    source(sandbox, PRODUCER, loops=[lesson(), knowledge()])
    configure(sandbox)
    args = decisions(sandbox, [dict(rule='R4', destination='lessons'), dict(rule='R4', destination='knowledge')])
    command_args = ['run', '--scope', 'all', *args, '--user-profile', str(profile(sandbox))]
    payload = json.loads(command(sandbox, *command_args).stdout)
    run, rounds = finish(sandbox, payload, agent(assessment(checkout / 'rules.md'), FACT), *extra)
    assert sum(row['operation'] == 'ask' for group in rounds for row in group) == 1
    assert (sandbox[1] / (PRODUCER + '.json')).exists()
    hook.unlink()
    payload = json.loads(command(sandbox, *command_args).stdout)
    run, rounds = finish(sandbox, payload, agent(), *extra)
    assert not [row for group in rounds for row in group if row['operation'] in ('ask', 'apply_knowledge')]
    assert any(row['capture'] == 'user_fact' for row in section(sandbox, run)['already_settled'] if 'capture' in row)
    assert archived(sandbox, PRODUCER)


def test_malformed_assessment_fails_its_item_alone(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    good, bad = lesson('A good lesson.'), lesson('A bad lesson.')
    path = source(sandbox, PRODUCER, loops=[good, bad])
    configure(sandbox)

    def answer(work):
        row = assessment(checkout / 'rules.md') if work['text'] == 'A good lesson.' else {'recommend': 'apply'}
        return agent(row)(work)

    run, _ = finish(sandbox, start(sandbox), answer)
    outcomes = {row['identity']['text']: row for row in section(sandbox, run)['filing_outcomes']}
    assert outcomes['A good lesson.']['outcome'] == 'written'
    assert outcomes['A bad lesson.']['outcome'] == 'failed' and 'requires target' in outcomes['A bad lesson.']['error']
    assert path.exists()


@pytest.mark.parametrize('status', ['carried', 'declined', 'failed', None])
def test_an_item_the_agent_does_not_assess_keeps_its_handoff(sandbox, tool, status):
    path = source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)

    def answer(work):
        return {'write_id': work['write_id'], 'status': status, 'error': 'stub'} if status else None

    run, _ = finish(sandbox, start(sandbox), answer)
    assert section(sandbox, run)['filing_outcomes'][0]['outcome'] == (status or 'uncertain')
    assert path.exists()


def test_applied_item_cannot_claim_its_own_write(sandbox, tool):
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    work, = start(sandbox)['work']
    results = sandbox[0] / 'results.json'
    results.write_text(json.dumps([{'write_id': work['write_id'], 'status': 'written', 'receipt': 'r', 'destination': 'd'}]))
    result = command(sandbox, 'complete', '--run-id', work['run_id'], '--results', str(results), code=1)
    assert 'returns its assessment' in result.stderr


def knowledge_root(sandbox):
    root = sandbox[0] / 'knowledge'
    for name in ('raw/research/.keep', 'raw/derived/.keep', 'output/.keep', 'docs/log.md', 'docs/DECISIONS.md',
                 'wiki/hot.md', 'wiki/index.md', 'context/rules.md'):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('# Start\n')
        os.utime(root / name, (1_000_000_000, 1_000_000_000))
    path = sandbox[0] / 'knowledge-profile.md'
    path.write_text('---\n' + '\n'.join(['profile_version: 4', f'knowledge_root: {root}', 'operation_log_file: docs/log.md',
        'decision_log_file: docs/DECISIONS.md', 'artifact_followup_destination: "Task list"',
        'hot_file: wiki/hot.md', 'wiki_followup_destination: "Wiki backlog"']) + '\n---\n')
    return root, ['--knowledge-profile', str(path)]


def test_carried_knowledge_is_captured_with_its_files_as_receipt(sandbox, tool):
    root, extra = knowledge_root(sandbox)
    source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    payload = start(sandbox, 'knowledge')
    work, = payload['work']
    assert work['operation'] == 'apply_knowledge' and work['native_step'] == 'knowledge'
    (root / 'wiki/pickup.md').write_text('# Pickup\n')
    (root / 'wiki/index.md').write_text('# Index\n- pickup\n')
    run, _ = finish(sandbox, payload, agent(knowledge_row={'capture': 'wiki', 'created': ['wiki/pickup.md'],
                                                           'updated': ['wiki/index.md']}), *extra)
    row, = section(sandbox, run)['knowledge_captured']
    assert row['receipt'] == 'wiki/pickup.md, wiki/index.md' and row['destination'] == 'wiki/pickup.md'
    assert archived(sandbox, PRODUCER)
    undo = json.loads(command(sandbox, 'undo', '--run-id', run['run_id'], '--user-started').stdout)
    assert undo['work'] == [] and undo['applied_left_in_place'][0]['created'] == ['wiki/pickup.md']
    assert (root / 'wiki/pickup.md').exists()


def test_capture_written_before_the_run_fails_and_keeps_the_handoff(sandbox, tool):
    _, extra = knowledge_root(sandbox)
    path = source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    row = {'capture': 'wiki', 'updated': ['wiki/index.md']}
    run, _ = finish(sandbox, start(sandbox, 'knowledge'), agent(knowledge_row=row), *extra)
    outcome = section(sandbox, run)['filing_outcomes'][0]
    assert outcome['outcome'] == 'failed' and 'not written during this wrap' in outcome['error']
    assert path.exists()


def test_missing_knowledge_profile_fails_the_item_not_the_run(sandbox, tool):
    path = source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    missing = ['--knowledge-profile', str(sandbox[0] / 'absent.md')]
    run, _ = finish(sandbox, start(sandbox, 'knowledge'),
                    agent(knowledge_row={'capture': 'source', 'created': ['raw/a.md']}), *missing)
    assert 'no knowledge profile' in section(sandbox, run)['filing_outcomes'][0]['error'] and path.exists()


FACT = {'capture': 'user_fact', 'text': 'Prefers short reports.', 'destination': 'context/about.md',
        'source': 'The session summary', 'choices': ['save', 'discard'], 'approve': 'save'}


def test_fact_about_the_user_is_an_ask_and_nothing_is_written(sandbox, tool):
    root, extra = knowledge_root(sandbox)
    source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    run, rounds = finish(sandbox, start(sandbox, 'knowledge'), agent(knowledge_row=FACT), *extra)
    ask, = rounds[1]
    assert ask['operation'] == 'ask' and ask['choices'] == ['save', 'discard']
    assert 'Prefers short reports.' in ask['ask']['text'] and 'default' not in ask['ask']
    assert ask['ask']['approve'] == 'save'
    assert not (root / 'context/about.md').exists()
    assert not section(sandbox, run)['knowledge_captured']
    assert section(sandbox, run)['filing_outcomes'][0]['outcome'] == 'written'
    assert archived(sandbox, PRODUCER)


def test_fact_about_the_user_without_an_ask_binding_keeps_its_handoff(sandbox, tool):
    _, extra = knowledge_root(sandbox)
    path = source(sandbox, PRODUCER, loops=[knowledge()])
    configure(sandbox)
    run, _ = finish(sandbox, start(sandbox, 'knowledge', ask=False), agent(knowledge_row=FACT), *extra)
    assert section(sandbox, run)['asks_raised'][0]['outcome'] == 'unbound' and path.exists()


def test_untyped_legacy_item_is_applied_with_its_sources_identity(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[{'context': 'A legacy lesson.', 'disposition': 'consider'}])
    configure(sandbox)
    run, _ = finish(sandbox, start(sandbox), agent(assessment(checkout / 'rules.md')))
    assert section(sandbox, run)['lessons_applied'][0]['delivery'] == 'pushed'
    assert archived(sandbox, PRODUCER)
