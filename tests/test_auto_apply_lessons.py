"""A wrap with the auto-apply setting on, driven through the checklist's command line."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/lib/checklist.py'
SESSION = 'wrap-session'
STEPS = ('record', 'knowledge', 'lessons', 'persist', 'handoff')


def git(cwd, *args, check=True):
    result = subprocess.run(['git', *args], cwd=cwd, text=True, capture_output=True)
    assert not check or result.returncode == 0, result.stderr
    return result.stdout.strip()


def clone_pair(tmp_path, name='rules'):
    """A checkout with one pushed commit, and a second clone that can move the remote."""
    remote = tmp_path / f'{name}.git'
    git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(remote))
    checkout = tmp_path / name
    git(tmp_path, 'clone', '-q', str(remote), str(checkout))
    for path in (checkout,):
        git(path, 'config', 'user.name', 'Test')
        git(path, 'config', 'user.email', 'test@example.invalid')
    (checkout / 'AGENTS.md').write_text('# Rules\n\nKeep tests green.\n')
    (checkout / 'other.md').write_text('other\n')
    git(checkout, 'add', '.')
    git(checkout, 'commit', '-qm', 'start')
    git(checkout, 'push', '-q', '-u', 'origin', 'main')
    other = tmp_path / f'{name}-other'
    git(tmp_path, 'clone', '-q', str(remote), str(other))
    git(other, 'config', 'user.name', 'Other')
    git(other, 'config', 'user.email', 'other@example.invalid')
    return checkout, remote, other


def move_remote(other, name='moved.md'):
    (other / name).write_text('moved\n')
    git(other, 'add', '.')
    git(other, 'commit', '-qm', f'move {name}')
    git(other, 'push', '-q', 'origin', 'main')


def lesson(text='Run the suite before reporting ready.', **changes):
    return {'type': 'lesson', 'session_id': SESSION, 'produced_at': '2026-11-05T12:00:00Z',
            'disposition': 'route through improve-harness', 'context': text, **changes}


def row(index, target, new='Run the suite first.\n', **changes):
    return {'index': index, 'recommend': 'apply', 'target': str(target), 'change': 'Add the suite rule',
            'evidence': 'A generator reported ready with failing tests.', 'edits': [{'new': new}], **changes}


class Wrap:
    """One wrap's environment: profile, configuration, routing and the module's commands."""

    def __init__(self, tmp_path, tool, setting=True, persist=True, ask=True, routing=None, session=SESSION):
        self.tmp = tmp_path
        self.tool = tool
        self.session = session
        self.home = tmp_path / 'home'
        self.home.mkdir(exist_ok=True)
        config = {'auto_apply_lessons': True} if setting else {}
        (tmp_path / 'config.json').write_text(json.dumps(config))
        (tmp_path / 'routing.md').write_text(routing or '# Routing\n')
        profile = {'name': 'user'}
        if persist:
            profile['bindings'] = {'persist': {'command': '/persist', 'consumes': []}}
        if ask:
            profile['ask'] = {'command': '/ask'}
        self.profile = tmp_path / 'profile.md'
        self.profile.write_text('```checklist-profile\n' + json.dumps(profile) + '\n```\n')
        self.handoff_path = tmp_path / 'handoff.json'
        self.env = {**os.environ, 'HOME': str(self.home), 'HIPPOCAMPUS_CONFIG': str(tmp_path / 'config.json'),
                    'HIPPOCAMPUS_ROUTING': str(tmp_path / 'routing.md'), 'CLAUDE_CODE_ENTRYPOINT': 'cli',
                    'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'), 'HANDOFF_PATH': str(self.handoff_path),
                    'HANDOFF_STATE_DIR': str(tmp_path / 'state'), 'CHECKLIST_STATE_DIR': str(tmp_path / 'checklist'),
                    'HANDOFF_COMPACT_STATE_DIR': str(tmp_path / 'compact'), 'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude'),
                    'CODEX_HOME': str(tmp_path / 'codex'), 'CLAUDE_SESSION_ID': session,
                    'CLAUDE_CODE_SESSION_ID': session, 'CODEX_THREAD_ID': '', 'HIPPOCAMPUS_HARNESS': tool}
        if tool == 'codex':
            self.env['CODEX_THREAD_ID'] = session
            transcript = tmp_path / f'codex/sessions/{session}.jsonl'
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(json.dumps({'type': 'session_meta',
                                              'payload': {'id': session, 'source': 'cli'}}) + '\n')

    def run(self, operation, *args):
        return subprocess.run([sys.executable, str(CLI), operation, '--user-profile', str(self.profile), *map(str, args)],
                              text=True, capture_output=True, env=self.env, cwd=self.tmp)

    def save(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data))
        return path

    def payload(self, items, session_items=()):
        return {'schema_version': 1, 'subject': {'session_id': self.session, 'working_directory': str(self.tmp)},
                'session_items': list(session_items),
                'resume': {'headline': 'Worked', 'next_action': 'Continue', 'open_loops': items,
                           'session_summary': 'Worked on the rules.', 'history_entry': 'Worked on the rules.'}}

    def plan(self):
        result = self.run('plan', '--session-id', self.session)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def apply(self, items, rows, session_items=()):
        result = self.run('apply-lessons', '--handoff', self.save('items.json', self.payload(items, session_items)),
                          '--lessons', self.save('lessons.json', rows))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def deliver(self, data):
        result = self.run('deliver-lessons', '--handoff', self.save('applied.json', data))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def file(self, data, rows=()):
        result = self.run('file', '--handoff', self.save('delivered.json', data),
                          '--filing', self.save('filing.json', list(rows)))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def finish(self, data):
        """Write the handoff, then return the report and the wrap check."""
        written = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint', '--cwd',
                                  str(self.tmp), '--session-id', self.session, '--trigger', 'wrap'],
                                 input=json.dumps(data), text=True, capture_output=True, env=self.env)
        assert written.returncode == 0, written.stderr
        results = self.save('results.json', [{'id': step, 'status': 'run', 'writes': []} for step in STEPS])
        report = self.run('report', '--handoff', self.handoff_path, '--results', results)
        wrap = self.run('wrap-check', '--written-handoff', self.handoff_path)
        assert report.stdout, report.stderr
        return json.loads(report.stdout), wrap, json.loads(self.handoff_path.read_text())


@pytest.fixture(params=['claude', 'codex'])
def tool(request):
    return request.param


def test_each_lesson_is_one_commit_a_revert_removes_exactly(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    target = checkout / 'AGENTS.md'
    data = wrap.apply([lesson('First lesson.'), lesson('Second lesson.')],
                      [row(0, target, 'First rule.\n', change='Add the first rule'),
                       row(1, target, 'Second rule.\n', change='Add the second rule')])
    assert data['resume']['open_loops'] == []
    assert git(checkout, 'log', '--format=%s', '-2').splitlines() == ['lesson: Add the second rule',
                                                                       'lesson: Add the first rule']
    first = data['lesson_outcomes'][0]['commit']
    data = wrap.deliver(data)
    assert git(checkout, 'rev-list', 'HEAD', '--not', '--remotes') == ''
    report, check, handoff = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    assert report['report'] == 'ok'
    assert report['saved_line'].startswith('All saved and pushed:') and 'rules (main)' in report['saved_line']
    applied = report['lessons']['applied']
    assert [(r['target'], r['change'], r['branch'], r['delivery']) for r in applied] == [
        (str(target.resolve()), 'Add the first rule', 'main', 'pushed'),
        (str(target.resolve()), 'Add the second rule', 'main', 'pushed')]
    assert applied[0]['commit'] == first
    assert handoff['resume']['open_loops'] == []
    git(checkout, 'revert', '--no-edit', applied[1]['commit'])
    assert 'First rule.' in target.read_text() and 'Second rule.' not in target.read_text()
    assert git(checkout, 'diff', '--stat', f'{first}', 'HEAD') == ''


def test_commit_holds_only_the_lessons_lines_in_a_changed_file(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    target = checkout / 'AGENTS.md'
    target.write_text('# Rules\n\nUncommitted user line.\n\nKeep tests green.\n')
    (checkout / 'other.md').write_text('staged user change\n')
    git(checkout, 'add', 'other.md')
    data = wrap.apply([lesson()], [row(0, target, change='Replace the green rule') | {
        'edits': [{'old': 'Keep tests green.', 'new': 'Keep every suite green.'}]}])
    assert data['lesson_outcomes'][0]['status'] == 'applied'
    shown = git(checkout, 'show', '--format=', '--unified=0', 'HEAD')
    assert '+Keep every suite green.' in shown and '-Keep tests green.' in shown
    assert 'Uncommitted user line' not in shown and 'other.md' not in shown
    assert 'Uncommitted user line.' in target.read_text() and 'Keep every suite green.' in target.read_text()
    status = subprocess.run(['git', 'status', '--porcelain=v1'], cwd=checkout, text=True, capture_output=True)
    assert sorted(status.stdout.splitlines()) == [' M AGENTS.md', 'M  other.md']
    assert 'Uncommitted user line' in git(checkout, 'diff', '--', 'AGENTS.md')


def test_target_outside_git_is_written_without_a_commit(tmp_path, tool):
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    target = tmp_path / 'plain/notes.md'
    data = wrap.apply([lesson()], [row(0, target)])
    assert target.read_text() == 'Run the suite first.\n'
    report, check, _ = wrap.finish(wrap.file(wrap.deliver(data)))
    assert check.returncode == 0, check.stderr
    assert report['lessons']['applied'][0]['delivery'] == 'not in a git repository'
    assert 'commit' not in report['lessons']['applied'][0]


def test_skip_is_dropped_and_listed_and_dictated_rule_applies_anyway(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.apply([lesson('Noise lesson.'), lesson('Dictated lesson.')], [
        {'index': 0, 'recommend': 'skip', 'reason': 'Advisory noise only', 'target': 'a hook'},
        row(1, checkout / 'AGENTS.md', recommend='skip', dictated=True, change='Add the dictated rule')])
    assert data['resume']['open_loops'] == []
    report, check, handoff = wrap.finish(wrap.file(wrap.deliver(data)))
    assert check.returncode == 0, check.stderr
    assert report['lessons']['dropped'] == [{'target': 'a hook', 'change': 'Noise lesson.',
                                             'reason': 'Advisory noise only'}]
    assert report['asks'] == []
    assert [r['change'] for r in report['lessons']['applied']] == ['Add the dictated rule']
    assert handoff['resume']['open_loops'] == []


@pytest.mark.parametrize('kind', ['user-rules', 'imported', 'composed'])
def test_always_loaded_target_is_applied_and_raises_a_text_ask(tmp_path, tool, kind):
    checkout, _, _ = clone_pair(tmp_path)
    target = checkout / 'AGENTS.md'
    routing = None
    home = tmp_path / ('claude' if tool == 'claude' else 'codex')
    home.mkdir(exist_ok=True)
    rules = home / ('CLAUDE.md' if tool == 'claude' else 'AGENTS.md')
    if kind == 'user-rules':
        rules.symlink_to(target)
    elif kind == 'imported':
        rules.write_text(f'@{target}\n')
    else:
        routing = (f'Produced surfaces:\n  {target}:\n    - path: {tmp_path}/made/CLAUDE.md\n'
                   '      regeneration command: "make rules"\n')
    wrap = Wrap(tmp_path, tool, routing=routing)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson(choices=['approve', 'decline'])], [row(0, target)]))
    commit = data['lesson_outcomes'][0]['commit']
    [ask] = data['lesson_asks']
    assert ask['choices'] == []
    assert 'choices' not in data['resume']['open_loops'][0]
    filed = wrap.file(data, [{'index': 0, 'rule': 'R3', 'status': 'filed', 'destination': 'ask receipt 7'}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert handoff['resume']['open_loops'] == []
    [raised] = report['asks']
    for text in (str(target.resolve()), 'Run the suite first.', 'A generator reported ready', commit,
                 'already applied', 'reverting that commit', "repository's normal delivery"):
        assert text in raised['text']
    assert raised['choices'] == []
    assert 'approve' not in json.dumps(report)
    assert report['saved_line'].startswith('All saved and pushed:')


def test_a_new_lesson_found_during_the_wrap_raises_its_ask(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    target = checkout / 'AGENTS.md'
    found = lesson('Found this wrap.')
    data = wrap.apply([], [row(0, target, always_loaded=True)], session_items=[found])
    assert data['resume']['open_loops'] == [] and data['session_items'][0]['applied'] is True
    data = wrap.deliver(data)
    [ask] = data['lesson_asks']
    assert ask['choices'] == [] and 'already applied' in ask['text']
    assert ask['text'] == data['session_items'][0]['ask_text']
    filed = wrap.file(data, [{'index': 0, 'rule': 'R3', 'status': 'filed', 'destination': 'ask receipt 9'}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert [raised['text'] for raised in report['asks']] == [ask['text']]
    assert handoff['resume']['open_loops'] == []
    assert wrap.plan()['handoff']['resume']['open_loops'] == []


def test_dictated_rule_for_an_always_loaded_target_still_raises_the_ask(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md', recommend='skip', dictated=True,
                                                    always_loaded=True)]))
    assert len(data['lesson_asks']) == 1
    filed = wrap.file(data, [{'index': 0, 'rule': 'R3', 'status': 'filed', 'destination': 'ask receipt 8'}])
    report, check, _ = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert 'already applied' in report['asks'][0]['text']


def test_ask_with_nothing_bound_stays_in_the_report_and_is_not_applied_again(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool, ask=False)
    wrap.plan()
    target = checkout / 'AGENTS.md'
    data = wrap.deliver(wrap.apply([lesson()], [row(0, target, always_loaded=True)]))
    filed = wrap.file(data, [{'index': 0, 'rule': 'R3', 'status': 'filed', 'destination': 'ask'}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert 'already applied' in report['asks'][0]['text']
    [carried] = handoff['resume']['open_loops']
    assert carried['applied'] is True
    again = wrap.apply([carried], [row(0, target, always_loaded=True)])
    assert target.read_text().count('Run the suite first.') == 1
    assert again['resume']['open_loops'] == [carried]


def test_rejected_push_brings_in_the_remote_and_retries(tmp_path, tool):
    checkout, _, other = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')])
    commit = data['lesson_outcomes'][0]['commit']
    move_remote(other)
    report, check, _ = wrap.finish(wrap.file(wrap.deliver(data)))
    assert check.returncode == 0, check.stderr
    [applied] = report['lessons']['applied']
    assert (applied['delivery'], applied['attempts'], applied['commit']) == ('pushed', 2, commit)
    assert (checkout / 'moved.md').exists()


def backup_remote(tmp_path, checkout):
    """A second remote, starting level with the checkout's branch."""
    backup = tmp_path / 'backup.git'
    git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(backup))
    git(checkout, 'remote', 'add', 'backup', str(backup))
    git(checkout, 'push', '-q', 'backup', 'main')
    return backup


def test_commit_on_another_remote_is_still_pushed_to_the_selected_one(tmp_path, tool):
    checkout, remote, _ = clone_pair(tmp_path)
    backup = backup_remote(tmp_path, checkout)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')])
    commit = data['lesson_outcomes'][0]['commit']
    git(checkout, 'push', '-q', 'backup', 'main')
    assert git(remote, 'rev-parse', 'main') != commit
    report, check, _ = wrap.finish(wrap.file(wrap.deliver(data)))
    assert check.returncode == 0, check.stderr
    [applied] = report['lessons']['applied']
    assert (applied['delivery'], applied['attempts']) == ('pushed', 1)
    assert git(remote, 'rev-parse', 'main') == commit == git(backup, 'rev-parse', 'main')


def test_commit_on_the_fetch_remote_is_still_pushed_to_the_push_remote(tmp_path, tool):
    checkout, remote, _ = clone_pair(tmp_path)
    backup = backup_remote(tmp_path, checkout)
    git(checkout, 'config', 'branch.main.pushRemote', 'backup')
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')])
    commit = data['lesson_outcomes'][0]['commit']
    git(checkout, 'push', '-q', 'origin', 'main')
    data = wrap.deliver(data)
    assert data['lesson_outcomes'][0]['delivery'] == 'pushed'
    assert git(backup, 'rev-parse', 'main') == commit


def test_push_rejected_twice_is_committed_not_pushed_and_not_saved(tmp_path, tool):
    checkout, _, other = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')])
    move_remote(other)
    # The remote moves again the moment its commits come in, so the one retry is rejected too.
    hook = checkout / '.git/hooks/post-merge'
    hook.write_text(f'#!/bin/sh\nunset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE\ncd "{other}"\n'
                    'echo again > again.md && git add . && git commit -qm again && git push -q origin main\n')
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    report, check, _ = wrap.finish(wrap.file(wrap.deliver(data)))
    [applied] = report['lessons']['applied']
    assert (applied['delivery'], applied['attempts']) == ('committed, not pushed', 2)
    assert 'rejected' in applied['error']
    assert 'Not saved:' in report['saved_line'] and 'committed, not pushed' in report['saved_line']
    assert check.returncode == 1


def pull_request_command(tmp_path):
    """A user's command: logs its request and prints the pull request's reference."""
    log = tmp_path / 'requests.log'
    command = tmp_path / 'open-request.sh'
    command.write_text(f'#!/bin/sh\ncat >> "{log}"\necho >> "{log}"\necho https://example.invalid/pull/7\n')
    command.chmod(0o755)
    return log, f'lesson-pull-request-command: {command}\n'


def assert_pull_request_delivery(report, check, checkout, remote, log, target_line='Run the suite first.'):
    assert check.returncode == 0, check.stderr
    [applied] = report['lessons']['applied']
    assert applied['delivery'] == 'pull request'
    assert applied['pull_request'] == 'https://example.invalid/pull/7'
    branch = applied['lesson_branch']
    assert target_line in git(remote, 'show', f'{branch}:AGENTS.md')
    assert git(remote, 'rev-parse', branch) == applied['commit']
    assert target_line not in git(remote, 'show', 'main:AGENTS.md')
    request = json.loads(log.read_text().splitlines()[0])
    assert (request['base'], request['branch'], request['remote']) == ('main', branch, 'origin')
    assert request['title'] == 'lesson: Add the suite rule'
    assert report['saved_line'].startswith('All saved and pushed:')


def refuse_main(remote):
    hook = remote / 'hooks/update'
    hook.write_text('#!/bin/sh\nif [ "$1" = refs/heads/main ]; then\n'
                    'echo "Changes must be made through a pull request." >&2\nexit 1\nfi\n')
    hook.chmod(0o755)


def test_refused_direct_push_goes_to_its_own_branch_and_pull_request(tmp_path, tool):
    checkout, remote, _ = clone_pair(tmp_path)
    refuse_main(remote)
    log, routing = pull_request_command(tmp_path)
    wrap = Wrap(tmp_path, tool, routing=routing)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')]))
    report, check, _ = wrap.finish(wrap.file(data))
    assert_pull_request_delivery(report, check, checkout, remote, log)


def test_several_lessons_for_one_file_all_reach_the_pull_request(tmp_path, tool):
    checkout, remote, _ = clone_pair(tmp_path)
    refuse_main(remote)
    log, routing = pull_request_command(tmp_path)
    wrap = Wrap(tmp_path, tool, routing=routing)
    wrap.plan()
    target = checkout / 'AGENTS.md'
    data = wrap.deliver(wrap.apply([lesson('One.'), lesson('Two.')], [
        row(0, target, 'First rule.\n', change='Add the first rule'),
        row(1, target, 'Second rule.\n', change='Add the second rule')]))
    report, check, _ = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    applied = report['lessons']['applied']
    assert [(r['change'], r['delivery'], r['pull_request']) for r in applied] == [
        ('Add the first rule', 'pull request', 'https://example.invalid/pull/7'),
        ('Add the second rule', 'pull request', 'https://example.invalid/pull/7')]
    [branch] = {r['lesson_branch'] for r in applied}
    shown = git(remote, 'show', f'{branch}:AGENTS.md')
    assert 'First rule.' in shown and 'Second rule.' in shown
    assert git(remote, 'log', '--format=%s', 'main..' + branch).splitlines() == [
        'lesson: Add the second rule', 'lesson: Add the first rule']
    assert git(remote, 'rev-parse', branch) == applied[1]['commit']
    assert git(remote, 'rev-parse', branch + '^') == applied[0]['commit']
    [request] = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert request['title'] == 'lessons: 2 applied at wrap'
    assert [entry['commit'] for entry in request['lessons']] == [r['commit'] for r in applied]
    assert report['saved_line'].startswith('All saved and pushed:')


def test_a_later_wrap_passes_after_pull_request_delivery(tmp_path, tool):
    checkout, remote, other = clone_pair(tmp_path)
    refuse_main(remote)
    log, routing = pull_request_command(tmp_path)
    wrap = Wrap(tmp_path, tool, routing=routing)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')]))
    report, check, _ = wrap.finish(wrap.file(data))
    assert_pull_request_delivery(report, check, checkout, remote, log)
    [first] = report['lessons']['applied']
    # The local commit stays on main (re-applied in the same second it may even share its SHA).
    assert set(git(checkout, 'rev-list', 'HEAD', '--not', '--remotes').split()) <= {first['local_commit']}
    assert git(checkout, 'rev-parse', f"refs/hippocampus/delivered/{first['local_commit']}") == first['commit']

    # A later session wraps in the same checkout before the request merges.
    later = Wrap(tmp_path, tool, routing=routing, session='later-session')
    later.plan()
    data = later.deliver(later.apply([lesson('Later.')], [row(0, checkout / 'other.md', 'Later rule.\n')]))
    report, check, _ = later.finish(later.file(data))
    assert check.returncode == 0, check.stderr
    assert report['saved_line'].startswith('All saved and pushed:')
    assert report['lessons']['applied'][0]['delivery'] == 'pull request'

    # The first request merges as a squash and its branch is deleted.
    git(other, 'fetch', '-q', 'origin')
    git(other, 'merge', '-q', '--squash', 'origin/' + first['lesson_branch'])
    git(other, 'commit', '-qm', 'squash lesson')
    hook = remote / 'hooks/update'
    hook.unlink()
    git(other, 'push', '-q', 'origin', 'main')
    git(other, 'push', '-q', 'origin', '--delete', first['lesson_branch'])
    refuse_main(remote)
    git(checkout, 'fetch', '-q', '--prune', 'origin')
    last = Wrap(tmp_path, tool, routing=routing, session='last-session')
    last.plan()
    data = last.deliver(last.apply([lesson('Last.')], [row(0, checkout / 'other.md', 'Last rule.\n')]))
    report, check, _ = last.finish(last.file(data))
    assert check.returncode == 0, check.stderr
    assert report['saved_line'].startswith('All saved and pushed:')


def test_refused_push_with_no_pull_request_command_is_reported_not_saved(tmp_path, tool):
    checkout, remote, _ = clone_pair(tmp_path)
    hook = remote / 'hooks/update'
    hook.write_text('#!/bin/sh\necho "Changes must be made through a pull request." >&2\nexit 1\n')
    hook.chmod(0o755)
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')]))
    report, check, _ = wrap.finish(wrap.file(data))
    [applied] = report['lessons']['applied']
    assert applied['delivery'] == 'committed, not pushed'
    assert 'lesson-pull-request-command' in applied['error']
    assert check.returncode == 1


def test_routing_file_requires_a_pull_request_for_a_repository(tmp_path, tool):
    checkout, remote, _ = clone_pair(tmp_path)
    _, command = pull_request_command(tmp_path)
    routing = f'{command}lesson-pull-requests:\n  - {tmp_path.name}/rules\n'
    wrap = Wrap(tmp_path, tool, routing=routing)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson('One.'), lesson('Two.')], [
        row(0, checkout / 'AGENTS.md'), row(1, checkout / 'other.md', 'Second rule.\n')]))
    assert [r['delivery'] for r in data['lesson_outcomes']] == ['pull request', 'pull request']
    first, second = data['lesson_outcomes']
    assert first['lesson_branch'] == second['lesson_branch']
    assert git(remote, 'show', '--format=', '--name-only', first['commit']).split() == ['AGENTS.md']
    assert git(remote, 'show', '--format=', '--name-only', second['commit']).split() == ['other.md']
    report, check, _ = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    assert report['saved_line'].startswith('All saved and pushed:')


def test_branch_other_than_default_is_named_in_the_report(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    git(checkout, 'remote', 'set-head', 'origin', 'main')
    git(checkout, 'switch', '-q', '-c', 'topic')
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')]))
    report, check, _ = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    [applied] = report['lessons']['applied']
    assert (applied['branch'], applied['note']) == ('topic', 'Reaches main when topic does.')


def test_persist_unbound_keeps_the_existing_not_pushed_rule(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool, persist=False)
    wrap.plan()
    data = wrap.deliver(wrap.apply([lesson()], [row(0, checkout / 'AGENTS.md')]))
    report, check, _ = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    assert report['lessons']['applied'][0]['delivery'] == 'committed, not pushed'
    assert 'Not pushed:' in report['saved_line'] and 'committed, not pushed' in report['saved_line']


@pytest.mark.parametrize('case', ['missing text', 'hook refuses', 'detached'])
def test_failed_lesson_is_reported_kept_and_the_wrap_continues(tmp_path, tool, case):
    checkout, _, _ = clone_pair(tmp_path)
    target = checkout / 'AGENTS.md'
    before = target.read_text()
    failing = row(0, target, change='Change a line') | {'edits': [{'old': 'No such line', 'new': 'x'}]}
    if case == 'hook refuses':
        failing = row(0, target)
        hook = checkout / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\necho refused by hook >&2\nexit 1\n')
        hook.chmod(0o755)
    elif case == 'detached':
        failing = row(0, target)
        git(checkout, 'switch', '-q', '--detach')
    wrap = Wrap(tmp_path, tool)
    wrap.plan()
    item = lesson()
    head = git(checkout, 'rev-parse', 'HEAD')
    data = wrap.apply([item, lesson('Good lesson.')], [failing, row(1, tmp_path / 'plain.md', 'Good.\n')])
    assert data['resume']['open_loops'] == [item]
    assert target.read_text() == before and git(checkout, 'rev-parse', 'HEAD') == head
    assert (tmp_path / 'plain.md').read_text() == 'Good.\n'
    error = data['lesson_outcomes'][0]['error']
    assert error
    data = wrap.deliver(data)
    filed = wrap.file(data, [{'index': 0, 'rule': 'R4', 'status': 'failed', 'error': error}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert report['report'] == 'incomplete'
    assert report['lessons']['failed'][0]['error'] == error
    assert handoff['resume']['open_loops'] == [item]
    assert 'stays carried' in report['saved_line']


def test_generated_copy_is_never_edited(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    source = checkout / 'AGENTS.md'
    made = checkout / 'other.md'
    routing = f'Produced surfaces:\n  {source}:\n    - path: {made}\n      regeneration command: "make rules"\n'
    wrap = Wrap(tmp_path, tool, routing=routing)
    wrap.plan()
    data = wrap.apply([lesson()], [row(0, made)])
    [outcome] = data['lesson_outcomes']
    assert outcome['target'] == str(source.resolve())
    assert outcome['surfaces'][0]['regeneration command'] == 'make rules'
    assert 'Run the suite first.' in source.read_text() and made.read_text() == 'other\n'

    header = tmp_path / 'composed.md'
    header.write_text('<!-- hippocampus-rules: generated from ["a"]; do not hand-edit -->\nrules\n')
    data = wrap.apply([lesson('Second.')], [row(0, header)])
    assert data['lesson_outcomes'][-1]['status'] == 'failed'
    assert 'generated copy' in data['lesson_outcomes'][-1]['error']
    assert 'Run the suite' not in header.read_text()


def test_an_applied_lesson_is_settled_and_never_applied_twice(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool)
    target = checkout / 'AGENTS.md'
    item = lesson()
    wrap.apply([item], [row(0, target)])
    again = wrap.apply([item], [row(0, target)])
    assert again['resume']['open_loops'] == []
    assert target.read_text().count('Run the suite first.') == 1
    assert wrap.plan()['handoff']['resume']['open_loops'] == []


def test_plan_runs_auto_apply_unattended_too(tmp_path, tool):
    wrap = Wrap(tmp_path, tool)
    result = wrap.run('plan', '--session-id', SESSION, '--unattended')
    assert json.loads(result.stdout)['auto_apply'] == {'lessons': 'apply'}


def test_routing_file_that_requires_proposals_wins_and_the_report_says_so(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    wrap = Wrap(tmp_path, tool, routing='lesson-policy: propose\n')
    assert wrap.plan()['auto_apply']['lessons'] == 'propose'
    target = checkout / 'AGENTS.md'
    before = target.read_text()
    item = lesson(choices=['approve', 'decline'])
    data = wrap.apply([item], [row(0, target)])
    assert target.read_text() == before and data['resume']['open_loops'] == [item]
    filed = wrap.file(wrap.deliver(data), [{'index': 0, 'rule': 'R4', 'status': 'filed', 'destination': 'ask',
                                            'choices': item['choices']}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert 'routing file' in report['lessons']['reason'] and 'requires it' in report['lessons']['reason']
    assert report['lessons']['carried'] == [item['context']]
    assert handoff['resume']['open_loops'] == [item]


def test_setting_off_changes_nothing(tmp_path, tool):
    checkout, _, _ = clone_pair(tmp_path)
    head = git(checkout, 'rev-parse', 'HEAD')
    wrap = Wrap(tmp_path, tool, setting=False)
    plan = wrap.plan()
    assert 'auto_apply' not in plan
    refused = wrap.run('apply-lessons', '--handoff', wrap.save('i.json', wrap.payload([lesson()])),
                       '--lessons', wrap.save('l.json', [row(0, checkout / 'AGENTS.md')]))
    assert refused.returncode == 1 and 'setting is off' in refused.stderr
    assert git(checkout, 'rev-parse', 'HEAD') == head and git(checkout, 'status', '--porcelain') == ''
    item = lesson(choices=['approve', 'decline'])
    filed = wrap.file(wrap.payload([item]), [{'index': 0, 'rule': 'R4', 'status': 'pending',
                                              'reason': 'Awaiting approval'}])
    assert 'lessons' not in filed['filing']
    report, _, handoff = wrap.finish(filed)
    assert 'lessons' not in report
    assert handoff['resume']['open_loops'] == [item]
    assert [ask['text'] for ask in report['asks']] == [item['context']]


def test_a_mistyped_setting_is_an_error(tmp_path, tool):
    wrap = Wrap(tmp_path, tool)
    (tmp_path / 'config.json').write_text('{"auto_apply_lessons": "yes"}')
    result = wrap.run('plan', '--session-id', SESSION)
    assert result.returncode == 1 and 'must be true or false' in result.stderr
