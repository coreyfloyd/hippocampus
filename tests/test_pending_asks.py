"""Complete pending asks through the public continuation and report commands."""
import json
import os
from pathlib import Path
import subprocess
import sys

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
