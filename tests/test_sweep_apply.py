"""A sweep with the auto-apply setting on, driven through its command line with stub bindings."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_auto_apply_lessons import clone_pair, git, move_remote
from test_sweep import assert_readable_report, command, decisions, read_run, sandbox, source  # noqa: F401

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
    assert section(sandbox, run)['lessons_applied'][0]['delivery'] == 'pushed'
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


def test_failed_persist_is_reported_and_delivery_still_decides(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    source(sandbox, PRODUCER, loops=[lesson()])
    configure(sandbox)
    base = agent(assessment(checkout / 'rules.md'))

    def answer(work):
        if work['operation'] == 'persist':
            return {'write_id': work['write_id'], 'status': 'failed', 'error': 'persist stub failed'}
        return base(work)

    payload = start(sandbox)
    run, _ = finish(sandbox, payload, answer)
    assert 'persist stub failed' in Path(payload['report']).read_text().split('```json')[0]
    assert section(sandbox, run)['lessons_applied'][0]['delivery'] == 'pushed'


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


def test_lesson_a_wrap_of_the_handoffs_session_applied_is_not_applied_again(sandbox, tool):
    checkout, _, _ = clone_pair(sandbox[0])
    source(sandbox, 'successor', loops=[lesson()])
    configure(sandbox)
    row = {'kind': 'lesson_outcome', 'outcome': {
        'identity': [PRODUCER, lesson()['produced_at'], 'lesson', lesson()['context']], 'status': 'applied',
        'target': str(checkout / 'rules.md'), 'commit': git(checkout, 'rev-parse', 'HEAD'), 'delivery': 'pushed'}}
    ledger = sandbox[0] / 'handoff-ledger'
    ledger.mkdir()
    (ledger / 'session-touched-paths.successor.jsonl').write_text(json.dumps(row) + '\n')
    payload = start(sandbox)
    assert payload['work'] == []
    run, _ = finish(sandbox, payload, agent())
    assert section(sandbox, run)['lessons_applied'][0]['receipt'] == row['outcome']['commit']
    assert archived(sandbox, 'successor')


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
