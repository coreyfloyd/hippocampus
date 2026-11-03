"""Complete pending asks through the public continuation and report commands."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('ask_status', ['filed', 'failed'])
def test_full_asks_survive_continuation_and_end_report(tmp_path, unattended, bound, ask_status):
    config = tmp_path / 'config.json'
    config.write_text('{}')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'name': 'user', **({'ask': {'command': '/ask'}} if bound else {})}))
    env = dict(os.environ, HIPPOCAMPUS_CONFIG=str(config), CLAUDE_CODE_ENTRYPOINT='cli',
               HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'), CHECKLIST_STATE_DIR=str(tmp_path / 'state'),
               HANDOFF_STATE_DIR=str(tmp_path / 'handoffs'), CHECKLIST_USER_PROFILE=str(profile),
               HANDOFF_COMPACT_STATE_DIR=str(tmp_path / 'backups'))

    def invoke(script, *args, payload=None, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                                input=json.dumps(payload) if payload is not None else None,
                                env=env, text=True, capture_output=True)
        assert result.returncode == expected, result.stderr
        return result

    choices = ['Approve ' + 'complete choice detail ' * 50, 'Decline']
    proposal = dict(target_file='rules/conventions.md', section='Evidence',
                    proposed_text='Keep the full proposal.\n' * 100,
                    evidence=['Observed a missing choice.\n' * 100])
    common = dict(session_id='producer', produced_at='2026-10-23T12:00:00Z', disposition='carry')
    decision = dict(common, type='decision', context='Approve this action?\n' * 100,
                    author='user', location='https://example.test/decision')
    lesson = dict(common, type='lesson', context=json.dumps(proposal), **proposal)
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'subject': {'session_id': 'producer', 'working_directory': str(tmp_path)},
                                 'resume': {'headline': 'Review pending asks', 'open_loops': [decision, lesson]}}))
    outcomes = tmp_path / 'outcomes.json'
    outcomes.write_text(json.dumps([
        dict(index=0, rule='R3', status=ask_status, error='Ask store refused write', destination='ask receipt', choices=choices),
        dict(index=1, rule='R4', status='filed', destination='ask', choices=choices)]))
    mode = ['--unattended'] if unattended else []
    filed = json.loads(invoke('scripts/lib/checklist.py', 'file', '--user-profile', profile,
                             '--handoff', source, '--filing', outcomes, *mode).stdout)
    invoke('scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path, '--session-id', 'producer', payload=filed)
    written = next((tmp_path / 'handoffs').rglob('*.json'))
    invoke('scripts/lib/handoff.py', 'pre-compact', payload={'cwd': str(tmp_path), 'session_id': 'producer'})
    assert list((tmp_path / 'backups').glob('pre-compact-*.json'))
    # A fresh process after compaction reads only the durable handoff.
    picked = json.loads(invoke('skills/pickup/scripts/pickup.py', '--handoff', written, '--json').stdout)
    carried = picked['resume']['open_loops']
    assert next(item for item in carried if item['type'] == 'lesson')['choices'] == choices
    assert any(lesson['context'] in row['line'] or json.dumps(lesson['context'])[1:-1] in row['line']
               for row in picked['briefing'])
    assert next(item for item in carried if item['type'] == 'lesson')['proposed_text'] == proposal['proposed_text']
    invoke('scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path, '--session-id', 'producer',
           '--trigger', 'wrap', payload=picked['handoff'])
    invoke('scripts/lib/checklist.py', 'wrap-check', '--user-profile', profile,
           '--written-handoff', written, *mode, expected=int(bound and ask_status == 'failed'))
    results = tmp_path / 'results.json'
    results.write_text(json.dumps([dict(id=step, status='run', writes=[])
                                  for step in ['record', 'knowledge', 'lessons', 'persist', 'handoff']]))
    report = json.loads(invoke('scripts/lib/checklist.py', 'report', '--user-profile', profile,
                              '--handoff', written, '--results', results, *mode,
                              expected=int(bound and ask_status == 'failed')).stdout)
    assert list(report)[-1] == 'asks'
    asks = report['asks']
    assert len(asks) == 2
    assert [ask['text'] for ask in asks] == [lesson['context'], decision['context']]
    assert all(ask['choices'] == choices for ask in asks)
    assert all(asks[0][key] == value for key, value in proposal.items())


@pytest.mark.parametrize('choices', [['apply', 'decline'], [''], ['apply', ' '], 'apply'])
def test_report_includes_carried_ask_without_filing_report(tmp_path, choices):
    source = tmp_path / 'handoff.json'
    env = dict(os.environ, HIPPOCAMPUS_CONFIG=str(tmp_path / 'absent.json'),
               HANDOFF_PATH=str(source), HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'),
               CLAUDE_CODE_ENTRYPOINT='cli')
    item = dict(type='lesson', context='Target: rules.md, section: Evidence\n' + 'Proposed text and evidence. ' * 60,
                choices=choices, session_id='producer', produced_at='2026-10-23T12:00:00Z',
                disposition='carry')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint',
                             '--cwd', str(tmp_path), '--session-id', 'producer'],
                            input=json.dumps({'resume': {'headline': 'Pending proposal', 'open_loops': [item]}}),
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    results = tmp_path / 'results.json'
    results.write_text(json.dumps([dict(id=step, status='carried' if step in ('record', 'persist') else 'run', writes=[])
                                  for step in ['record', 'knowledge', 'lessons', 'persist', 'handoff']]))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/checklist.py'), 'report',
                             '--handoff', str(source), '--results', str(results)], env=env,
                            text=True, capture_output=True)
    if choices == ['apply', 'decline']:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['asks'][0]['text'] == item['context']
    else:
        assert result.returncode == 1
        assert "an ask requires the user's choices" in result.stderr


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('status', ['pending', 'declined', 'failed'])
@pytest.mark.parametrize('choice_source', ['item', 'outcome', 'none'])
def test_native_lesson_decisions_and_backlog_through_wrap(tmp_path, unattended, status, choice_source):
    """Native failures keep lessons; only proposals with a user decision are asks."""
    source = tmp_path / 'source.json'
    written = tmp_path / 'handoff.json'
    env = dict(os.environ, HIPPOCAMPUS_CONFIG=str(tmp_path / 'absent.json'),
               HANDOFF_PATH=str(written), HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'),
               HANDOFF_COMPACT_STATE_DIR=str(tmp_path / 'compact'),
               CHECKLIST_STATE_DIR=str(tmp_path / 'state'), CLAUDE_CODE_ENTRYPOINT='cli',
               CHECKLIST_USER_PROFILE=str(tmp_path / 'profile.json'))
    (tmp_path / 'profile.json').write_text(json.dumps({'name': 'user'}))
    mode = ['--unattended'] if unattended else []

    def invoke(script, *args, payload=None):
        result = subprocess.run([sys.executable, str(ROOT / script), *map(str, args)], env=env,
                                input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.startswith('{') else result.stdout

    proposal = dict(target_file='rules/evidence.md', section='Verification',
                    proposed_text='Keep every detail.\n' * 80, evidence=['Observed omission.\n' * 80])
    choices = ['Apply the full proposal. ' * 50, 'Decline this proposal']
    lesson = dict(type='lesson', context=json.dumps(proposal), **proposal,
                  session_id='producer', produced_at='2026-10-23T12:00:00Z', disposition='carry')
    if choice_source == 'item':
        lesson['choices'] = choices
    # Native-step outcomes can carry the choices discovered by the lessons step.
    row = dict(index=0, rule='R4', status=status, reason='Native lesson remains unsaved')
    if choice_source == 'outcome':
        row['choices'] = choices
    source.write_text(json.dumps({'resume': {'headline': 'Pending native lesson', 'open_loops': [lesson]}}))
    outcomes = tmp_path / 'outcomes.json'
    outcomes.write_text(json.dumps([row]))
    filed = invoke('scripts/lib/checklist.py', 'file', '--handoff', source, '--filing', outcomes, *mode)
    invoke('scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path, '--session-id', 'producer', payload=filed)
    invoke('scripts/lib/handoff.py', 'pre-compact', payload={'cwd': str(tmp_path), 'session_id': 'producer'})
    picked = invoke('skills/pickup/scripts/pickup.py', '--handoff', written, '--json')
    carried, = picked['resume']['open_loops']
    assert carried['context'] == lesson['context']
    assert all(carried[key] == value for key, value in proposal.items())
    if choice_source != 'none':
        assert carried['choices'] == choices
    invoke('scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path, '--session-id', 'producer',
           '--trigger', 'wrap', payload=picked['handoff'])
    invoke('scripts/lib/checklist.py', 'wrap-check', '--written-handoff', written, *mode)
    results = tmp_path / 'results.json'
    results.write_text(json.dumps([dict(id=step, status='carried' if step in ('record', 'persist') else 'run', writes=[])
                                  for step in ['record', 'knowledge', 'lessons', 'persist', 'handoff']]))
    report = invoke('scripts/lib/checklist.py', 'report', '--handoff', written, '--results', results, *mode)
    assert list(report)[-1] == 'asks'
    assert report['report'] == 'incomplete'
    assert report['incomplete'][0]['id'] == 'lessons'
    assert report['filing']['items'][0]['status'] == status
    assert report['filing']['items'][0]['item']['context'] == lesson['context']
    if choice_source == 'none':
        assert report['asks'] == []
    else:
        ask, = report['asks']
        assert ask['text'] == lesson['context']
        assert ask['choices'] == choices
        assert all(ask[key] == value for key, value in proposal.items())


@pytest.fixture
def failed_wrap(tmp_path):
    """A filed decision and a carried, complete lesson available to a failed wrap."""
    source, written = tmp_path / 'source.json', tmp_path / 'handoff.json'
    profile, outcomes = tmp_path / 'profile.json', tmp_path / 'outcomes.json'
    results = tmp_path / 'results.json'
    env = {key: value for key, value in os.environ.items()
           if key not in ('CODEX_THREAD_ID', 'HIPPOCAMPUS_HARNESS')}
    env.update(HIPPOCAMPUS_CONFIG=str(tmp_path / 'absent.json'), CLAUDE_CODE_ENTRYPOINT='cli',
               HANDOFF_PATH=str(written), HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'),
               CHECKLIST_STATE_DIR=str(tmp_path / 'state'))

    def invoke(script, *args, payload=None):
        return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                              input=json.dumps(payload) if payload is not None else None,
                              env=env, text=True, capture_output=True)

    profile.write_text(json.dumps({'name': 'user', 'ask': {'command': '/ask'}, 'bindings': {
        slot: {'command': '/' + slot, 'consumes': ['progress']} for slot in ('record', 'persist')}}))
    choices = ['Apply with every condition.\n' * 50, 'Decline']
    common = dict(session_id='producer', produced_at='2026-10-23T12:00:00Z', disposition='carry')
    decision = dict(common, type='decision', context='Approve the complete action?\n' * 100,
                    choices=choices, author='user', location='https://example.test/decision')
    lesson = dict(common, type='lesson', context='Review the complete lesson proposal.\n' * 100,
                  choices=choices, target_file='rules/evidence.md', section='Verification',
                  proposed_text='Retain every detail.\n' * 100, evidence=['Observed omission.\n' * 100])
    items = [decision, lesson]
    rows = [dict(index=0, rule='R3', status='filed', destination='ask receipt', choices=choices),
            dict(index=1, rule='R4', status='pending', reason='Approve the lesson', choices=choices)]

    def checkpoint():
        source.write_text(json.dumps({'subject': {'session_id': 'producer', 'working_directory': str(tmp_path)},
                                     'resume': {'headline': 'Pending asks', 'open_loops': items}}))
        outcomes.write_text(json.dumps(rows))
        filed = invoke('scripts/lib/checklist.py', 'file', '--user-profile', profile,
                       '--handoff', source, '--filing', outcomes)
        assert filed.returncode == 0, filed.stderr
        saved = invoke('scripts/lib/handoff.py', 'checkpoint', '--cwd', tmp_path,
                       '--session-id', 'producer', '--trigger', 'wrap', payload=json.loads(filed.stdout))
        assert saved.returncode == 0, saved.stderr

    checkpoint()
    results.write_text(json.dumps([dict(id=step, status='run', writes=[])
                                  for step in ['record', 'knowledge', 'lessons', 'persist', 'handoff']]))

    def report(unattended, *, summary_args=None, results_args=None, handoff_args=None):
        return invoke('scripts/lib/checklist.py', 'report', '--user-profile', profile,
                      *(handoff_args if handoff_args is not None else ['--handoff', written]),
                      *(results_args if results_args is not None else ['--results', results]),
                      *(summary_args if summary_args is not None else ['--no-summary', 'Summary unavailable']),
                      *(['--unattended'] if unattended else []))

    def assert_asks(result, *, expected=1, status='failed'):
        assert result.returncode == expected, result.stderr
        output = json.loads(result.stdout)
        assert output['report'] == status
        assert list(output)[-1] == 'asks'
        asks = output['asks']
        assert len(asks) == 2
        assert [ask['text'] for ask in asks] == [lesson['context'], decision['context']]
        for ask, item in zip(asks, [lesson, decision]):
            assert all(ask[key] == value for key, value in item.items())
        return output

    return SimpleNamespace(profile=profile, handoff=written, results=results, items=items, rows=rows,
                           checkpoint=checkpoint, report=report, assert_asks=assert_asks)


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('step', ['record', 'persist'])
def test_failed_bound_step_still_reports_every_ask(failed_wrap, unattended, step):
    results = json.loads(failed_wrap.results.read_text())
    next(row for row in results if row['id'] == step).update(status='failed', error='Write refused')
    failed_wrap.results.write_text(json.dumps(results))
    result = failed_wrap.report(unattended)
    output = failed_wrap.assert_asks(result)
    error = f'{step}: bound write failed: Write refused'
    assert error in result.stderr
    assert error in output['errors']


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('failure', ['ask write', 'record write', 'record read', 'missing retained item'])
def test_filing_failure_still_reports_every_ask(failed_wrap, unattended, failure):
    error = 'Store refused the operation'
    if failure == 'ask write':
        failed_wrap.rows[0].update(status='failed', error=error)
    elif failure in ('record write', 'record read'):
        failed_wrap.items.append(dict(failed_wrap.items[1], type='progress', context='Record the work', choices=[]))
        failed_wrap.rows.append(dict(index=2, rule='R2', status='failed', read_status='ok', error=error))
        if failure == 'record read':
            failed_wrap.rows[-1]['read_status'] = 'failed'
    failed_wrap.checkpoint()
    if failure == 'missing retained item':
        handoff = json.loads(failed_wrap.handoff.read_text())
        handoff['resume']['open_loops'] = []
        failed_wrap.handoff.write_text(json.dumps(handoff))
        error = 'retained item missing from handoff'
    result = failed_wrap.report(unattended)
    output = failed_wrap.assert_asks(result)
    assert error in result.stderr
    assert any(error in problem for problem in output['errors'])


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('step', ['knowledge', 'lessons'])
@pytest.mark.parametrize('status', ['failed', 'declined', 'pending'])
def test_incomplete_native_step_still_reports_every_ask(failed_wrap, unattended, step, status):
    results = json.loads(failed_wrap.results.read_text())
    next(row for row in results if row['id'] == step).update(status=status, reason='Native work remains unsaved')
    failed_wrap.results.write_text(json.dumps(results))
    output = failed_wrap.assert_asks(failed_wrap.report(unattended), expected=0, status='incomplete')
    assert dict(id=step, status=status, reason='Native work remains unsaved') in output['incomplete']


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('failure', [
    'missing results argument', 'unreadable results', 'malformed results', 'results not array',
    'results not objects', 'missing step', 'missing status', 'pending writes', 'pending reason',
    'native failure reason', 'missing summary', 'empty summary reason', 'conflicting summary',
    'empty summary', 'unreadable summary', 'invalid handoff', 'malformed filing',
    'malformed filing row', 'malformed filing items', 'malformed ask payload', 'malformed resume',
    'malformed carried item', 'invalid ask choices',
    'unreadable profile', 'malformed profile', 'invalid profile',
])
def test_report_validation_errors_do_not_suppress_asks(failed_wrap, tmp_path, unattended, failure):
    summary_args, results_args = None, None
    results = json.loads(failed_wrap.results.read_text())
    if failure == 'missing results argument':
        results_args = []
        error = 'report requires --results and --handoff'
    elif failure == 'unreadable results':
        failed_wrap.results.unlink()
        error = 'results.json'
    elif failure == 'malformed results':
        failed_wrap.results.write_text('{')
        error = 'results'
    elif failure in ('results not array', 'results not objects'):
        failed_wrap.results.write_text(json.dumps({} if failure == 'results not array' else [None]))
        error = 'results must be an array of step objects'
    elif failure in ('missing step', 'missing status', 'pending writes', 'pending reason', 'native failure reason'):
        if failure == 'missing step':
            results.pop()
            error = 'steps reported'
        elif failure == 'missing status':
            results[0].pop('status')
            error = 'status None'
        elif failure == 'pending writes':
            results[1].update(status='pending', reason='Approve capture', writes=['notes.md'])
            error = 'a pending step writes nothing'
        elif failure == 'pending reason':
            results[1]['status'] = 'pending'
            error = 'a pending step names the answer it needs'
        else:
            results[1]['status'] = 'failed'
            error = 'failed requires a reason or error'
        failed_wrap.results.write_text(json.dumps(results))
    elif failure == 'missing summary':
        summary_args = []
        error = 'session summary: missing'
    elif failure == 'empty summary reason':
        summary_args = ['--no-summary', ' ']
        error = '--no-summary names why it is unavailable'
    elif failure in ('conflicting summary', 'empty summary', 'unreadable summary'):
        summary = tmp_path / 'summary.md'
        summary_args = ['--summary', summary]
        if failure == 'conflicting summary':
            summary.write_text('Session work')
            summary_args += ['--no-summary', 'Unavailable']
            error = 'pass --summary or --no-summary, not both'
        elif failure == 'empty summary':
            summary.write_text(' \n')
            error = 'summary file is empty'
        else:
            error = 'summary.md'
    elif failure in ('invalid handoff', 'malformed filing', 'malformed filing row', 'malformed filing items',
                     'malformed ask payload', 'malformed resume',
                     'malformed carried item', 'invalid ask choices'):
        handoff = json.loads(failed_wrap.handoff.read_text())
        if failure == 'invalid handoff':
            del handoff['git']
            error = 'schema_version 2 requires a git block'
        elif failure == 'malformed filing':
            # The filed ask is also carried here so all asks remain recoverable.
            handoff['resume']['open_loops'].append(failed_wrap.items[0])
            handoff['filing'] = []
            error = 'filing report must be an object'
        elif failure == 'malformed filing row':
            handoff['filing']['items'].insert(0, None)
            error = 'filing.items[0]'
        elif failure == 'malformed filing items':
            handoff['filing']['items'] = None
            error = 'filing.items must be an array'
        elif failure == 'malformed ask payload':
            handoff['filing']['items'][0]['ask'] = None
            error = 'ask must be an object'
        elif failure == 'malformed resume':
            handoff['resume'] = None
            error = 'missing/invalid resume block'
        elif failure == 'malformed carried item':
            handoff['resume']['open_loops'].insert(0, None)
            error = 'open_loops[0]'
        else:
            handoff['resume']['open_loops'].insert(0, dict(failed_wrap.items[1], context='Malformed ask', choices=['']))
            error = "an ask requires the user's choices"
        failed_wrap.handoff.write_text(json.dumps(handoff))
    elif failure == 'unreadable profile':
        failed_wrap.profile.unlink()
        error = 'profile.json'
    elif failure == 'malformed profile':
        failed_wrap.profile.write_text('{')
        error = 'profile'
    else:
        failed_wrap.profile.write_text(json.dumps({'name': 'user', 'bindings': {'lessons': None}}))
        error = 'knowledge and lessons are native steps'
    result = failed_wrap.report(unattended, summary_args=summary_args, results_args=results_args)
    output = failed_wrap.assert_asks(result)
    assert error in result.stderr
    assert any(error in problem for problem in output['errors'])


@pytest.mark.parametrize('unattended', [False, True])
def test_combined_wrap_failures_keep_all_errors_and_asks(failed_wrap, unattended):
    results = json.loads(failed_wrap.results.read_text())
    results[0].update(status='failed', error='Record unavailable')
    results[3].update(status='failed', error='Push refused')
    failed_wrap.results.write_text(json.dumps(results))
    failed_wrap.rows[0].update(status='failed', error='Ask store unavailable')
    failed_wrap.checkpoint()
    result = failed_wrap.report(unattended, summary_args=[])
    output = failed_wrap.assert_asks(result)
    for error in ('Record unavailable', 'Push refused', 'Ask store unavailable', 'session summary: missing'):
        assert error in result.stderr
        assert any(error in problem for problem in output['errors'])


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('failure', ['omitted', 'missing', 'malformed JSON', 'not object'])
def test_report_without_readable_handoff_reports_failure(failed_wrap, unattended, failure):
    handoff_args = None
    if failure == 'omitted':
        handoff_args = []
    elif failure == 'missing':
        failed_wrap.handoff.unlink()
    else:
        failed_wrap.handoff.write_text('{' if failure == 'malformed JSON' else '[]')
    result = failed_wrap.report(unattended, handoff_args=handoff_args)
    assert result.returncode == 1
    assert 'handoff' in result.stderr
    output = json.loads(result.stdout)
    assert output['report'] == 'failed'
    assert any('handoff' in problem for problem in output['errors'])
    assert list(output)[-1] == 'asks'
    assert output['asks'] == []  # No readable source from which to recover asks.


@pytest.mark.parametrize('unattended', [False, True])
def test_applied_native_proposal_is_not_reported_as_pending(failed_wrap, unattended):
    failed_wrap.rows[1].update(status='filed', destination='Applied to rules/evidence.md')
    failed_wrap.checkpoint()
    result = failed_wrap.report(unattended)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output['report'] == 'ok'
    assert [ask['text'] for ask in output['asks']] == [failed_wrap.items[0]['context']]


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('persist_failed', [False, True])
@pytest.mark.parametrize('difference', ['ticket', 'choices', 'target_file', 'section',
                                      'proposed_text', 'diff', 'evidence', 'proposal'])
def test_distinct_asks_with_same_item_identity_survive_report(failed_wrap, unattended, persist_failed, difference):
    lesson = failed_wrap.items[1]
    lesson['anchor'] = {'ticket': 'https://example.test/tickets/first'}
    variant = copy.deepcopy(lesson)
    if difference == 'ticket':
        variant['anchor']['ticket'] = 'https://example.test/tickets/second'
    elif difference == 'choices':
        variant['choices'] = ['Apply the alternate choice.\n' * 100, 'Defer']
    elif difference == 'evidence':
        variant['evidence'] = ['A separate observation.\n' * 100]
    elif difference == 'proposal':
        variant['proposal'] = {'text': 'A separate proposal.\n' * 100}
    else:
        variant[difference] = 'A separate proposal detail.\n' * 100
    failed_wrap.items.append(variant)
    # The second lesson appears as a filed ask, a grouped ask, and a carried item.
    failed_wrap.rows.append(dict(index=2, rule='R4', status='filed', destination='ask', choices=variant['choices']))
    failed_wrap.checkpoint()
    if persist_failed:
        results = json.loads(failed_wrap.results.read_text())
        next(row for row in results if row['id'] == 'persist').update(status='failed', error='Push refused')
        failed_wrap.results.write_text(json.dumps(results))
    result = failed_wrap.report(unattended)
    assert result.returncode == int(persist_failed), result.stderr
    output = json.loads(result.stdout)
    assert output['report'] == ('failed' if persist_failed else 'incomplete')
    if persist_failed:
        assert 'Push refused' in result.stderr
        assert any('Push refused' in error for error in output['errors'])
    assert list(output)[-1] == 'asks'
    asks = output['asks']
    assert len(asks) == 3
    assert [ask['type'] for ask in asks] == ['lesson', 'lesson', 'decision']
    for ask, item in zip(asks, [lesson, variant, failed_wrap.items[0]]):
        assert ask['text'] == item['context']
        assert all(ask[key] == value for key, value in item.items())
        assert ask['ticket'] == item.get('anchor', {}).get('ticket')


@pytest.mark.parametrize('unattended', [False, True])
def test_identical_filed_grouped_and_carried_asks_appear_once(failed_wrap, unattended):
    failed_wrap.rows[1].update(status='filed', destination='ask')
    failed_wrap.checkpoint()
    handoff = json.loads(failed_wrap.handoff.read_text())
    for directory, asks in handoff['filing']['asks'].items():
        handoff['filing']['asks'][directory] = [dict(reversed(list(ask.items()))) for ask in asks]
    handoff['resume']['open_loops'] = [dict(reversed(list(item.items())))
                                     for item in handoff['resume']['open_loops']]
    failed_wrap.handoff.write_text(json.dumps(handoff))
    failed_wrap.assert_asks(failed_wrap.report(unattended), expected=0, status='incomplete')


@pytest.mark.parametrize('unattended', [False, True])
@pytest.mark.parametrize('source', ['item', 'group'])
@pytest.mark.parametrize('invalid', ['missing choices', 'empty choices', 'blank choice', 'non-string choice',
                                   'choices not array', 'missing text', 'blank text', 'text not string'])
def test_invalid_stored_ask_fails_without_hiding_valid_asks(failed_wrap, unattended, source, invalid):
    handoff = json.loads(failed_wrap.handoff.read_text())
    payload = copy.deepcopy(handoff['filing']['items'][0]['ask'])
    if invalid == 'missing choices':
        del payload['choices']
    elif invalid == 'empty choices':
        payload['choices'] = []
    elif invalid == 'blank choice':
        payload['choices'] = ['Apply', ' \n']
    elif invalid == 'non-string choice':
        payload['choices'] = ['Apply', None]
    elif invalid == 'choices not array':
        payload['choices'] = 'Apply'
    elif invalid == 'missing text':
        del payload['text']
    elif invalid == 'blank text':
        payload['text'] = ' \n'
    else:
        payload['text'] = ['Approve?']
    if source == 'item':
        row = copy.deepcopy(handoff['filing']['items'][0])
        row.update(index=2, ask=payload)
        handoff['filing']['items'].append(row)
        label = 'filing.items[2].ask'
    else:
        handoff['filing']['asks'][payload['directory']].append(payload)
        label = 'filing.asks['
    failed_wrap.handoff.write_text(json.dumps(handoff))
    result = failed_wrap.report(unattended)
    output = failed_wrap.assert_asks(result)
    error = 'an ask requires non-empty text' if 'text' in invalid else "an ask requires the user's choices"
    assert error in result.stderr
    assert any(label in problem and error in problem for problem in output['errors'])


@pytest.mark.parametrize('unattended', [False, True])
def test_stored_ask_validation_preserves_its_text_and_ticket(failed_wrap, unattended):
    handoff = json.loads(failed_wrap.handoff.read_text())
    payload = copy.deepcopy(handoff['filing']['items'][0]['ask'])
    # Stored text and ticket are already resolved; validation must not rebuild them from item fields.
    payload.update(text='Approve this separate stored ask?\n' * 100,
                   ticket='https://example.test/tickets/stored',
                   directory='/work/original', context='Source context differs',
                   anchor={'ticket': 'https://example.test/tickets/source'})
    handoff['filing']['asks'].setdefault(payload['directory'], []).append(payload)
    failed_wrap.handoff.write_text(json.dumps(handoff))
    result = failed_wrap.report(unattended)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output['report'] == 'incomplete'
    assert list(output)[-1] == 'asks'
    assert len(output['asks']) == 3
    assert output['asks'][-1] == payload
