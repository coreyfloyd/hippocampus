"""Saved-state verdicts through filing, reporting, and wrap command lines."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest
from test_record_writes import ROOT, CLI, item, payload, row, run, store


@pytest.fixture(autouse=True, params=['claude', 'codex'])
def tool_flow(tmp_path, monkeypatch, request):
    monkeypatch.setenv('CLAUDE_CODE_ENTRYPOINT', 'cli')
    if request.param == 'codex':
        monkeypatch.setenv('HIPPOCAMPUS_HARNESS', 'codex')
        monkeypatch.setenv('CODEX_THREAD_ID', 'successor')
        monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
        transcript = tmp_path / 'codex/sessions/successor.jsonl'
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({'type': 'session_meta',
            'payload': {'id': 'successor', 'source': 'cli'}}) + '\n')
    return request.param


def check(tmp_path, profile, data, cwd=None):
    profile_path = tmp_path / 'profile.json'
    profile_path.write_text(json.dumps(profile))
    target = tmp_path / 'handoff.json'
    env = dict(os.environ, CLAUDE_CODE_ENTRYPOINT='cli', HANDOFF_PATH=str(target),
               HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'), HANDOFF_STATE_DIR=str(tmp_path))
    data['resume'].update(headline='Finished recording work', next_action=data['resume'].get('next_action', 'Session finished.'),
                          session_summary='Recorded changes and checked saved state.')
    checkpoint = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint',
        '--cwd', str(cwd or tmp_path), '--session-id', 'successor', '--trigger', 'wrap'],
        input=json.dumps(data), text=True, capture_output=True, env=env)
    assert checkpoint.returncode == 0, checkpoint.stderr
    results = tmp_path / 'results.json'
    results.write_text(json.dumps([dict(id=s, status='run', writes=[]) for s in
                                  ('record', 'knowledge', 'lessons', 'persist', 'handoff')]))
    summary = tmp_path / 'summary.txt'
    summary.write_text('Recorded changes and checked saved state.')
    common = ['--user-profile', str(profile_path)]
    report = subprocess.run([sys.executable, str(CLI), 'report', *common, '--handoff', str(target),
        '--results', str(results), '--summary', str(summary)], text=True, capture_output=True, env=env)
    wrap = subprocess.run([sys.executable, str(CLI), 'wrap-check', *common, '--written-handoff',
        str(target), '--record-at', '2099-01-01T00:00:00Z'], text=True, capture_output=True, env=env)
    return report, wrap


@pytest.mark.parametrize('state', ['receipt', 'reused', 'dropped', 'ask', 'unbound', 'noask',
                                   'failed', 'uncertain', 'read failed', 'pending'])
def test_saved_state_table(tmp_path, state):
    binding = store(tmp_path, {'failed': 'failed', 'uncertain': 'lost'}.get(state, 'ok'))
    profile = {'name': 'user', 'record_writes': {'documents': binding}}
    source = payload([item('Keep the complete change', record_kind='documents', disposition='File this change')])
    outcome = row()
    if state in ('ask', 'noask', 'pending'):
        source['resume']['open_loops'][0].update(type='decision', choices=['approve', 'defer'], author='user', location='session')
        outcome = dict(index=0, rule='R3', status='filed' if state == 'ask' else 'pending',
                       destination='ask receipt', error='no ask receipt')
        if state != 'noask':
            profile['ask'] = {'command': '/ask'}
    elif state == 'dropped':
        outcome = dict(index=0, rule='R6', status='dropped', reason='Already recorded')
    elif state == 'unbound':
        profile.pop('record_writes')
    elif state == 'read failed':
        outcome.update(status='read failed', error='record unavailable')
    if state == 'reused':
        assert run(tmp_path, 'record', profile, source, [outcome]).returncode == 0
    filed = run(tmp_path, 'record', profile, source, [outcome])
    data = json.loads(filed.stdout)
    report, wrap = check(tmp_path, profile, data)
    output = json.loads(report.stdout)
    failed = state in ('failed', 'uncertain', 'read failed', 'pending')
    assert report.returncode == int(failed), report.stderr
    assert wrap.returncode == int(failed), wrap.stderr
    line = output['saved_line']
    assert list(output)[-2:] == ['saved_line', 'asks']
    if failed:
        assert 'Not saved:' in line and 'Keep the complete change' in line
        assert ('record unavailable' if state == 'read failed' else
                'no ask receipt' if state == 'pending' else 'write') in line
    elif state in ('unbound', 'noask'):
        assert 'Kept:' in line and 'Keep the complete change' in line
        assert ('documents' if state == 'unbound' else 'ask') in line
        assert output['warnings']
    else:
        assert line == 'All saved and pushed'
    if state in ('ask', 'noask', 'pending'):
        assert output['asks'][0]['text'] == 'Keep the complete change'
        assert output['asks'][0]['choices'] == ['approve', 'defer']


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True, text=True, capture_output=True)


def pushed_repository(tmp_path):
    repo = tmp_path / 'repository'
    repo.mkdir()
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(repo, 'init', '-q')
    (repo / 'folder').mkdir()
    (repo / 'folder/change.txt').write_text('original')
    (repo / '.gitignore').write_text('.worktrees/\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'Initial')
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-u', 'origin', 'HEAD')
    return repo


def ledger_command(tmp_path, tool_flow, cwd, command):
    script = 'scripts/codex-hook.py' if tool_flow == 'codex' else 'scripts/lib/handoff.py'
    event = dict(session_id='successor', cwd=str(cwd), hook_event_name='PostToolUse',
                 tool_name='Bash', tool_input={'command': command}, tool_response={'exit_code': 0},
                 transcript_path=str(tmp_path / 'codex/sessions/successor.jsonl'))
    result = subprocess.run([sys.executable, str(ROOT / script), 'ledger-record'],
        input=json.dumps(event), text=True, capture_output=True,
        env=dict(os.environ, HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger')))
    assert result.returncode == 0, result.stderr


def ledger_file(tmp_path, repo, path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'ledger-file',
        str(path), '--cwd', str(repo), '--session-id', 'successor'], text=True, capture_output=True,
        env=dict(os.environ, HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger')))
    assert result.returncode == 0, result.stderr


def check_repository_problem(tmp_path, bound, checkout, reason, cwd=None):
    profile = {'name': 'user'}
    if bound:
        profile['bindings'] = {'persist': {'command': '/persist', 'consumes': []}}
    report, wrap = check(tmp_path, profile, payload([]), cwd=cwd)
    assert report.returncode == int(bound), report.stdout + report.stderr
    assert wrap.returncode == int(bound), wrap.stdout + wrap.stderr
    output = json.loads(report.stdout)
    line = output['saved_line']
    assert str(checkout) in line
    assert reason in line
    assert ('Not saved:' if bound else 'Not pushed:') in line
    if not bound:
        assert 'changes were not pushed' in line
        assert output['warnings']
    assert list(output)[-2:] == ['saved_line', 'asks']
    return line


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('observation', ['cwd', 'git-command', 'quoted-git-command'])
@pytest.mark.parametrize('subject', ['outside', 'main', 'sibling'])
def test_git_observations_check_each_touched_worktree(tmp_path, tool_flow, bound, observation, subject):
    repo = pushed_repository(tmp_path)
    linked = tmp_path / ('linked checkout' if observation == 'quoted-git-command' else 'linked')
    git(repo, 'worktree', 'add', '-qb', 'linked', str(linked))
    sibling = tmp_path / 'sibling'
    git(repo, 'worktree', 'add', '-qb', 'sibling', str(sibling))
    cwd = {'outside': tmp_path, 'main': repo, 'sibling': sibling}[subject]
    observed_cwd = linked if observation == 'cwd' else cwd
    prefix = 'git' if observation == 'cwd' else f'git -C {shlex.quote(str(linked))}'
    ledger_command(tmp_path, tool_flow, observed_cwd, prefix + ' status')
    (linked / 'folder/change.txt').write_text('unpublished work')
    git(linked, 'commit', '-qam', 'Changed in linked checkout')
    ledger_command(tmp_path, tool_flow, observed_cwd, prefix + ' commit -qam change')
    check_repository_problem(tmp_path, bound, linked, 'changes were not pushed', cwd=cwd)


def test_git_command_keeps_hash_inside_checkout_name(tmp_path, tool_flow):
    repo = pushed_repository(tmp_path)
    linked = tmp_path / 'linked#1'
    git(repo, 'worktree', 'add', '-qb', 'linked', str(linked))
    (linked / 'folder/change.txt').write_text('unpublished work')
    git(linked, 'commit', '-qam', 'Changed in linked checkout')
    ledger_command(tmp_path, tool_flow, repo, f'git -C {linked} commit -qam change')
    check_repository_problem(tmp_path, True, linked, 'changes were not pushed', cwd=repo)


@pytest.mark.parametrize('bound', [False, True])
def test_deleted_tracked_directory_uses_ledger_checkout(tmp_path, bound):
    repo = pushed_repository(tmp_path)
    linked = tmp_path / 'linked'
    git(repo, 'worktree', 'add', '-qb', 'linked', str(linked))
    path = linked / 'folder/change.txt'
    ledger_file(tmp_path, linked, path)
    shutil.rmtree(path.parent)
    line = check_repository_problem(tmp_path, bound, linked, 'uncommitted changes', cwd=path.parent)
    assert 'cannot check' not in line
    assert json.loads((tmp_path / 'handoff.json').read_text())['uncommitted_files'] == [str(path)]


@pytest.mark.parametrize('bound', [False, True])
def test_file_checkout_is_not_replaced_with_subject_worktree(tmp_path, bound):
    repo = pushed_repository(tmp_path)
    linked = tmp_path / 'linked'
    git(repo, 'worktree', 'add', '-qb', 'linked', str(linked))
    path = repo / 'folder/change.txt'
    path.write_text('unpublished work in main checkout')
    ledger_file(tmp_path, repo, path)
    git(repo, 'commit', '-qam', 'Changed in main checkout')
    check_repository_problem(tmp_path, bound, repo, 'changes were not pushed', cwd=linked)


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('missing', ['directory', 'git-file'])
def test_unavailable_checkout_does_not_fall_back_to_parent(tmp_path, tool_flow, bound, missing):
    repo = pushed_repository(tmp_path)
    linked = repo / '.worktrees/linked'
    git(repo, 'worktree', 'add', '-qb', 'linked', str(linked))
    ledger_command(tmp_path, tool_flow, linked, 'git status')
    if missing == 'directory':
        shutil.rmtree(linked)
    else:
        (linked / '.git').unlink()
    check_repository_problem(tmp_path, bound, linked, 'cannot check commit and push state')


@pytest.mark.parametrize('bound', [False, True])
def test_repository_without_checkout_evidence_is_not_assumed_saved(tmp_path, bound):
    repo = pushed_repository(tmp_path)
    ledger = tmp_path / 'ledger'
    ledger.mkdir()
    (ledger / 'session-touched-paths.successor.jsonl').write_text(json.dumps(
        dict(repo_root=str(repo), head=git(repo, 'rev-parse', 'HEAD').stdout.strip())) + '\n')
    check_repository_problem(tmp_path, bound, repo, 'missing checkout', cwd=repo)


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('state', ['dirty', 'unpushed', 'pushed', 'no-upstream'])
def test_repository_saved_state(tmp_path, bound, state):
    repo = tmp_path / 'repository'
    repo.mkdir()
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'change.txt').write_text('original')
    git(repo, 'add', 'change.txt')
    git(repo, 'commit', '-qm', 'Initial')
    if state != 'no-upstream':
        git(repo, 'remote', 'add', 'origin', str(remote))
        git(repo, 'push', '-u', 'origin', 'HEAD')
    if state == 'dirty':
        (repo / 'change.txt').write_text('changed')
    elif state == 'unpushed':
        (repo / 'change.txt').write_text('changed')
        git(repo, 'commit', '-qam', 'Changed')
    ledger = tmp_path / 'ledger'
    ledger.mkdir()
    (ledger / 'session-touched-paths.successor.jsonl').write_text(json.dumps(
        dict(kind='file', session_id='successor', path=str(repo / 'change.txt'), checkout=str(repo))) + '\n')
    profile = {'name': 'user'}
    if bound:
        profile['bindings'] = {'persist': {'command': '/persist', 'consumes': []}}
    report, wrap = check(tmp_path, profile, payload([]))
    failed = bound and state != 'pushed'
    assert report.returncode == int(failed), report.stderr
    assert wrap.returncode == int(failed), wrap.stderr
    output = json.loads(report.stdout)
    if state == 'pushed':
        assert output['saved_line'] == 'All saved and pushed'
    else:
        assert str(repo) in output['saved_line']
        assert ('Not saved:' if bound else 'Not pushed:') in output['saved_line']


@pytest.mark.parametrize('status', ['pending', 'failed'])
def test_native_item_without_a_receipt_is_not_saved(tmp_path, status):
    source = payload([item('Capture the finding', disposition='Capture it')])
    source['resume']['open_loops'][0]['type'] = 'knowledge'
    filed = run(tmp_path, 'record', {'name': 'user'}, source,
                [dict(index=0, rule='R4', status=status, reason='capture unavailable')])
    report, wrap = check(tmp_path, {'name': 'user'}, json.loads(filed.stdout))
    assert report.returncode == 1
    assert wrap.returncode == 1
    line = json.loads(report.stdout)['saved_line']
    assert 'Not saved:' in line and 'Capture the finding' in line and 'capture unavailable' in line
