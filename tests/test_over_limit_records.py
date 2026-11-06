"""Over-limit records: a wrap with the auto-apply setting on records, and does not ask."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/lib/checklist.py'
HARNESS = ROOT / 'skills/slim-harness/scripts/harness.py'
RULE = 'Run the whole suite before you report that the work is ready.'


def git(cwd, *args):
    result = subprocess.run(['git', *args], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def repository(tmp_path, name='rules', remote='https://example.invalid/acme/rules.git'):
    checkout = tmp_path / name
    checkout.mkdir()
    git(checkout, 'init', '-q', '-b', 'main')
    if remote:
        git(checkout, 'remote', 'add', 'origin', remote)
    return checkout


def rules_file(path, lines=230, extra=''):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('# Rules\n\n' + extra + ''.join(f'- Rule {n} of {path.name} keeps its own words.\n' for n in range(lines)))
    return path


class Session:
    """One session's environment; sessions share the ledger directory, as on one machine."""

    def __init__(self, tmp_path, tool, session, setting=True):
        self.tmp = tmp_path
        self.tool = tool
        self.session = session
        home = tmp_path / 'home'
        home.mkdir(exist_ok=True)
        (tmp_path / 'config.json').write_text(json.dumps({'auto_apply_lessons': True} if setting else {}))
        (tmp_path / 'routing.md').write_text('# Routing\n')
        self.profile = tmp_path / 'profile.md'
        self.profile.write_text('```checklist-profile\n' + json.dumps({'name': 'user'}) + '\n```\n')
        self.env = {**os.environ, 'HOME': str(home), 'HIPPOCAMPUS_CONFIG': str(tmp_path / 'config.json'),
                    'HIPPOCAMPUS_ROUTING': str(tmp_path / 'routing.md'), 'CLAUDE_CODE_ENTRYPOINT': 'cli',
                    'HANDOFF_LEDGER_DIR': str(tmp_path / 'ledger'),
                    'HANDOFF_PATH': str(tmp_path / f'{session}-handoff.json'),
                    'HANDOFF_STATE_DIR': str(tmp_path / 'state'), 'CHECKLIST_STATE_DIR': str(tmp_path / 'checklist'),
                    'HANDOFF_COMPACT_STATE_DIR': str(tmp_path / 'compact'),
                    'CLAUDE_CONFIG_DIR': str(tmp_path / 'claude'), 'CODEX_HOME': str(tmp_path / 'codex'),
                    'CLAUDE_SESSION_ID': session, 'CLAUDE_CODE_SESSION_ID': session, 'CODEX_THREAD_ID': '',
                    'HIPPOCAMPUS_HARNESS': tool}
        if tool == 'codex':
            self.env['CODEX_THREAD_ID'] = session
            transcript = tmp_path / f'codex/sessions/{session}.jsonl'
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(json.dumps({'type': 'session_meta',
                                              'payload': {'id': session, 'source': 'cli'}}) + '\n')

    def slim_helper(self, operation, *files):
        manifest = self.tmp / f'{self.session}-manifest.json'
        manifest.write_text(json.dumps({'tool': self.tool, 'files': [
            {'path': str(path), 'kind': 'rules', 'loaded': 'auto'} for path in files]}))
        result = subprocess.run([sys.executable, str(HARNESS), operation, str(manifest)],
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        path = self.tmp / f'{self.session}-{operation}.json'
        path.write_text(result.stdout)
        return path

    def run(self, operation, *args):
        return subprocess.run([sys.executable, str(CLI), operation, '--user-profile', str(self.profile),
                               '--session-id', self.session, *map(str, args)],
                              text=True, capture_output=True, env=self.env, cwd=self.tmp)

    def record(self, *files, duplicates=True):
        args = ['--measure', self.slim_helper('measure', *files)]
        if duplicates:
            args += ['--duplicates', self.slim_helper('duplicates', *files)]
        result = self.run('record-over-limit', *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def records(self):
        result = self.run('over-limit-records')
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)['records']


@pytest.fixture(params=['claude', 'codex'])
def tool(request):
    return request.param


def test_a_record_names_repository_and_path_never_a_home_path(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'rules/AGENTS.md')
    output = Session(tmp_path, tool, 'first').record(target)
    assert [row['line'] for row in output['recorded']] == [
        'Over limit, recorded for a later slim: acme/rules rules/AGENTS.md (232 lines, limit 200)']
    assert output['reported'] == []
    [entry] = Session(tmp_path, tool, 'reader').records()
    assert (entry['repository'], entry['path']) == ('acme/rules', 'rules/AGENTS.md')
    assert entry['limits'] == [{'unit': 'lines', 'measured': 232, 'limit': 200}]
    assert entry['size']['lines'] == 232 and entry['sessions'] == ['first']
    stored = (tmp_path / 'ledger/over-limit-records.json').read_text()
    assert str(tmp_path) not in stored and 'example.invalid' not in stored
    assert 'slim-harness' not in stored


def test_several_sessions_record_one_file_as_one_entry(tmp_path, tool):
    target = rules_file(repository(tmp_path, remote='git@example.invalid:acme/rules.git') / 'AGENTS.md')
    Session(tmp_path, tool, 'first').record(target)
    rules_file(target, lines=260)
    Session(tmp_path, tool, 'second').record(target)
    Session(tmp_path, tool, 'second').record(target)
    [entry] = Session(tmp_path, tool, 'reader').records()
    assert entry['path'] == 'AGENTS.md' and entry['repository'] == 'acme/rules'
    assert entry['sessions'] == ['first', 'second']
    assert entry['limits'] == [{'unit': 'lines', 'measured': 262, 'limit': 200}]


def test_a_record_survives_a_wrapped_and_an_abandoned_session(tmp_path, tool):
    checkout = repository(tmp_path)
    wrapped = rules_file(checkout / 'wrapped.md')
    abandoned = rules_file(checkout / 'abandoned.md')
    first = Session(tmp_path, tool, 'wrapped')
    first.record(wrapped)
    data = {'schema_version': 1, 'subject': {'session_id': 'wrapped', 'working_directory': str(tmp_path)},
            'resume': {'headline': 'Worked', 'next_action': 'Continue', 'open_loops': [],
                       'session_summary': 'Worked.', 'history_entry': 'Worked.'}}
    written = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint', '--cwd',
                              str(tmp_path), '--session-id', 'wrapped', '--trigger', 'wrap'],
                             input=json.dumps(data), text=True, capture_output=True, env=first.env)
    assert written.returncode == 0, written.stderr
    # The second session records and then ends without a wrap or a handoff.
    Session(tmp_path, tool, 'abandoned').record(abandoned)
    paths = [entry['path'] for entry in Session(tmp_path, tool, 'later').records()]
    assert paths == ['abandoned.md', 'wrapped.md']


def test_a_file_outside_a_repository_is_reported_with_the_attended_command(tmp_path, tool):
    outside = rules_file(tmp_path / 'loose/AGENTS.md')
    no_remote = rules_file(repository(tmp_path, 'local', remote=None) / 'AGENTS.md')
    output = Session(tmp_path, tool, 'first').record(outside, no_remote, duplicates=False)
    assert output['recorded'] == []
    reasons = {row['path']: row['reason'] for row in output['reported']}
    assert reasons == {str(outside): 'not in a git repository',
                       str(no_remote): 'its repository has no remote that names it'}
    assert all(row['action'] == f"run /hippocampus:slim-harness on `{row['path']}`" for row in output['reported'])
    assert Session(tmp_path, tool, 'reader').records() == []


def test_duplicate_rules_are_recorded_for_each_file_they_name(tmp_path, tool):
    checkout = repository(tmp_path)
    left = rules_file(checkout / 'AGENTS.md', lines=3, extra=RULE + '\n\n')
    right = rules_file(checkout / 'skills/CLAUDE.md', lines=3, extra=RULE + '\n\n')
    outside = rules_file(tmp_path / 'loose.md', lines=3, extra=RULE + '\n\n')
    output = Session(tmp_path, tool, 'first').record(left, right)
    assert [row['line'] for row in output['recorded']] == [
        'Duplicate rule, recorded for the slim of the files it names: '
        'acme/rules AGENTS.md:3 and acme/rules skills/CLAUDE.md:3']
    Session(tmp_path, tool, 'second').record(left, right)
    entries = Session(tmp_path, tool, 'reader').records()
    assert [entry['path'] for entry in entries] == ['AGENTS.md', 'skills/CLAUDE.md']
    for entry in entries:
        assert entry['limits'] == [] and entry['sessions'] == ['first', 'second']
        [finding] = entry['duplicates']
        assert finding['match'] == 'exact'
        assert [(s['repository'], s['path'], s['text']) for s in finding['spans']] == [
            ('acme/rules', 'AGENTS.md', RULE), ('acme/rules', 'skills/CLAUDE.md', RULE)]
    # A duplicate naming a file no record could name stays attended, as today.
    mixed = Session(tmp_path, tool, 'third').record(left, outside)
    assert mixed['recorded'] == []
    [row] = mixed['reported']
    assert row['type'] == 'duplicate-rule' and row['reason'] == f'{outside}: not in a git repository'
    assert row['action'].startswith('run /hippocampus:slim-harness')


def test_with_the_setting_off_nothing_is_recorded_and_the_blocks_are_unchanged(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'AGENTS.md')
    session = Session(tmp_path, tool, 'first', setting=False)
    measure = session.slim_helper('measure', target)
    result = session.run('record-over-limit', '--measure', measure)
    assert result.returncode == 1 and 'the auto-apply setting is off' in result.stderr
    assert not (tmp_path / 'ledger/over-limit-records.json').exists()
    [row] = json.loads(measure.read_text())['over_limit']
    assert set(row) == {'path', 'source', 'size', 'limits', 'action'}
    assert row['action'] == f'run /hippocampus:slim-harness on `{target}`'
    plan = session.run('plan')
    assert plan.returncode == 0, plan.stderr
    assert 'auto_apply' not in json.loads(plan.stdout)



def test_a_routing_file_that_requires_proposals_still_records(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'AGENTS.md')
    session = Session(tmp_path, tool, 'first')
    (tmp_path / 'routing.md').write_text('lesson-policy: propose\n')
    output = session.record(target, duplicates=False)
    assert [row['path'] for row in output['recorded']] == ['AGENTS.md']
