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


def rules_file(path, lines=230, extra='', tracked=True):
    """A rules file; inside a repository it is tracked, as a file another machine can find."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('# Rules\n\n' + extra + ''.join(f'- Rule {n} of {path.name} keeps its own words.\n' for n in range(lines)))
    if tracked and subprocess.run(['git', 'rev-parse'], cwd=path.parent, capture_output=True).returncode == 0:
        git(path.parent, 'add', '--', str(path))
    return path


def skill_file(path, description_characters=1100, body_lines=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    description = ('Use for anything at all. ' * 60)[:description_characters].strip().ljust(description_characters, 'x')
    path.write_text('---\nname: x\ndescription: ' + description + '\n---\n# Skill\n\n'
                    + ''.join(f'- Step {n} of the skill body.\n' for n in range(body_lines)))
    git(path.parent, 'add', '--', str(path))
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
        """Files are rules loaded automatically, or (path, kind, loaded) rows of the slim helper's manifest."""
        manifest = self.tmp / f'{self.session}-manifest.json'
        manifest.write_text(json.dumps({'tool': self.tool, 'files': [
            {'path': str(row[0]), 'kind': row[1], 'loaded': row[2]} if isinstance(row, tuple)
            else {'path': str(row), 'kind': 'rules', 'loaded': 'auto'} for row in files]}))
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

    def record(self, *files):
        result = self.run('record-over-limit', '--measure', self.slim_helper('measure', *files),
                          '--duplicates', self.slim_helper('duplicates', *files))
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
    outside = rules_file(tmp_path / 'loose/AGENTS.md', tracked=False)
    no_remote = rules_file(repository(tmp_path, 'local', remote=None) / 'AGENTS.md')
    local = rules_file(repository(tmp_path, 'path-remote', remote=str(tmp_path / 'srv/git/rules.git')) / 'AGENTS.md')
    file_url = rules_file(repository(tmp_path, 'file-remote', remote='file:///srv/git/rules.git') / 'AGENTS.md')
    no_owner = rules_file(repository(tmp_path, 'no-owner', remote='https://example.invalid/rules.git') / 'AGENTS.md')
    output = Session(tmp_path, tool, 'first').record(outside, no_remote, local, file_url, no_owner)
    assert output['recorded'] == []
    rows = [row for row in output['reported'] if 'type' not in row]
    remoteless = 'its repository has no hosted remote that names it'
    assert {row['path']: row['reason'] for row in rows} == {
        str(outside): 'not in a git repository', str(no_remote): remoteless, str(local): remoteless,
        str(file_url): remoteless, str(no_owner): remoteless}
    assert all(row['action'] == f"run /hippocampus:slim-harness on `{row['path']}`" for row in rows)
    assert Session(tmp_path, tool, 'reader').records() == []


def test_duplicate_rules_are_recorded_for_each_file_they_name(tmp_path, tool):
    checkout = repository(tmp_path)
    left = rules_file(checkout / 'AGENTS.md', lines=3, extra=RULE + '\n\n')
    right = rules_file(checkout / 'skills/CLAUDE.md', lines=3, extra=RULE + '\n\n')
    outside = rules_file(tmp_path / 'loose.md', lines=3, extra=RULE + '\n\n', tracked=False)
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
    # A duplicate naming a file no record could name stays attended, as today; the file
    # measured again within its limits, with no recordable duplicate left, loses its record.
    mixed = Session(tmp_path, tool, 'third').record(left, outside)
    assert mixed['recorded'] == []
    [row] = mixed['reported']
    assert row['type'] == 'duplicate-rule' and row['reason'] == f'{outside}: not in a git repository'
    assert row['action'].startswith('run /hippocampus:slim-harness')
    assert [entry['path'] for entry in Session(tmp_path, tool, 'reader').records()] == ['skills/CLAUDE.md']


def test_with_the_setting_off_nothing_is_recorded_and_the_blocks_are_unchanged(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'AGENTS.md')
    session = Session(tmp_path, tool, 'first', setting=False)
    measure = session.slim_helper('measure', target)
    result = session.run('record-over-limit', '--measure', measure,
                         '--duplicates', session.slim_helper('duplicates', target))
    assert result.returncode == 1 and 'the auto-apply setting is off' in result.stderr
    assert not (tmp_path / 'ledger/over-limit-records.json').exists()
    [row] = json.loads(measure.read_text())['over_limit']
    assert set(row) == {'path', 'source', 'size', 'limits', 'action'}
    assert row['action'] == f'run /hippocampus:slim-harness on `{target}`'
    plan = session.run('plan')
    assert plan.returncode == 0, plan.stderr
    assert 'auto_apply' not in json.loads(plan.stdout)



def test_a_routing_file_that_requires_proposals_records_nothing(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'AGENTS.md')
    session = Session(tmp_path, tool, 'first')
    (tmp_path / 'routing.md').write_text('lesson-policy: propose\n')
    result = session.run('record-over-limit', '--measure', session.slim_helper('measure', target),
                         '--duplicates', session.slim_helper('duplicates', target))
    assert result.returncode == 1 and 'requires it' in result.stderr
    assert not (tmp_path / 'ledger/over-limit-records.json').exists()


@pytest.mark.parametrize('remote,repository_name', [
    ('https://example.invalid/acme/rules.git', 'acme/rules'),
    ('ssh://git@example.invalid:2222/acme/rules', 'acme/rules'),
    ('git@example.invalid:acme/rules.git', 'acme/rules'),
    ('https://example.invalid/group/sub/rules.git', 'group/sub/rules')])
def test_a_hosted_remote_names_the_whole_repository_path(tmp_path, tool, remote, repository_name):
    target = rules_file(repository(tmp_path, remote=remote) / 'AGENTS.md')
    Session(tmp_path, tool, 'first').record(target)
    [entry] = Session(tmp_path, tool, 'reader').records()
    assert entry['repository'] == repository_name


@pytest.mark.parametrize('remote', [
    'ssh://me@example.invalid/Users/someone/repos/rules.git',
    'ssh://git@example.invalid:22/~me/repos/rules.git',
    'me@example.invalid:/Users/someone/rules.git',
    'me@example.invalid:~someone/rules.git',
    'https://example.invalid/home/someone/rules.git'])
def test_a_remote_whose_path_is_a_home_path_names_no_repository(tmp_path, tool, remote):
    target = rules_file(repository(tmp_path, remote=remote) / 'AGENTS.md')
    output = Session(tmp_path, tool, 'first').record(target)
    [row] = output['reported']
    assert output['recorded'] == [] and row['reason'] == 'its repository has no hosted remote that names it'
    assert Session(tmp_path, tool, 'reader').records() == []


def test_a_file_git_does_not_track_is_reported_not_recorded(tmp_path, tool):
    checkout = repository(tmp_path)
    (checkout / '.gitignore').write_text('CLAUDE.local.md\n')
    git(checkout, 'add', '.gitignore')
    ignored = rules_file(checkout / 'CLAUDE.local.md', tracked=False)
    untracked = rules_file(checkout / 'notes/AGENTS.md', tracked=False)
    tracked = rules_file(checkout / 'AGENTS.md')
    output = Session(tmp_path, tool, 'first').record(ignored, untracked, tracked)
    assert [row['line'] for row in output['recorded']] == [
        'Over limit, recorded for a later slim: acme/rules AGENTS.md (232 lines, limit 200)']
    rows = [row for row in output['reported'] if 'type' not in row]
    assert {row['path']: row['reason'] for row in rows} == {
        str(ignored): 'git does not track it, so another machine could not find it',
        str(untracked): 'git does not track it, so another machine could not find it'}
    assert all(row['action'] == f"run /hippocampus:slim-harness on `{row['path']}`" for row in rows)
    assert [entry['path'] for entry in Session(tmp_path, tool, 'reader').records()] == ['AGENTS.md']


def test_a_listed_skill_measurement_replaces_only_its_description_limits(tmp_path, tool):
    skill = skill_file(repository(tmp_path) / 'skills/x/SKILL.md', body_lines=520)
    full, listed = (skill, 'skill', 'full'), (skill, 'skill', 'listed')
    output = Session(tmp_path, tool, 'first').record(full)
    [line] = [row['line'] for row in output['recorded']]
    assert line == ('Over limit, recorded for a later slim: acme/rules skills/x/SKILL.md '
                    '(522 body lines, limit 500; 1100 description characters, limit 1024)')
    # A wrap that only lists the skill measures its description alone: the body limit stays.
    skill_file(skill, description_characters=1090, body_lines=520)
    output = Session(tmp_path, tool, 'second').record(listed)
    assert [row['line'] for row in output['recorded']] == [
        'Over limit, recorded for a later slim: acme/rules skills/x/SKILL.md (1090 description characters, limit 1024)']
    [entry] = Session(tmp_path, tool, 'reader').records()
    assert [(row['unit'], row['measured']) for row in entry['limits']] == [
        ('body lines', 522), ('description characters', 1090)]
    assert entry['size']['lines'] and entry['size']['description_characters'] == 1090
    assert entry['sessions'] == ['first', 'second']
    # Trimmed, the description limit goes; the body limit, which this wrap did not measure, stays.
    skill_file(skill, description_characters=100, body_lines=520)
    assert Session(tmp_path, tool, 'third').record(listed)['recorded'] == []
    [entry] = Session(tmp_path, tool, 'reader').records()
    assert [(row['unit'], row['measured']) for row in entry['limits']] == [('body lines', 522)]
    # A full load within every limit removes the record.
    skill_file(skill, description_characters=100, body_lines=3)
    assert Session(tmp_path, tool, 'fourth').record(full)['recorded'] == []
    assert Session(tmp_path, tool, 'reader').records() == []


def test_a_listed_skill_trimmed_within_its_limit_loses_its_record(tmp_path, tool):
    skill = skill_file(repository(tmp_path) / 'skills/x/SKILL.md')
    listed = (skill, 'skill', 'listed')
    Session(tmp_path, tool, 'first').record(listed)
    [entry] = Session(tmp_path, tool, 'reader').records()
    assert entry['limits'] == [{'unit': 'description characters', 'measured': 1100, 'limit': 1024}]
    skill_file(skill, description_characters=100)
    assert Session(tmp_path, tool, 'second').record(listed)['recorded'] == []
    assert Session(tmp_path, tool, 'reader').records() == []


def test_a_damaged_store_is_a_clear_error_and_is_left_alone(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'AGENTS.md')
    store = tmp_path / 'ledger/over-limit-records.json'
    store.parent.mkdir()
    store.write_text(json.dumps({'schema_version': 1, 'records': [{'x': 1}]}))
    session = Session(tmp_path, tool, 'first')
    result = session.run('record-over-limit', '--measure', session.slim_helper('measure', target),
                         '--duplicates', session.slim_helper('duplicates', target))
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.strip() == f'checklist: over-limit records: {store} row 1 is not a record'
    assert json.loads(store.read_text())['records'] == [{'x': 1}]
    listing = session.run('over-limit-records')
    assert listing.returncode == 1 and 'row 1 is not a record' in listing.stderr


def test_a_new_measurement_replaces_findings_and_within_limits_removes_the_record(tmp_path, tool):
    checkout = repository(tmp_path)
    target = rules_file(checkout / 'AGENTS.md', extra=RULE + '\n\n')
    other = rules_file(checkout / 'other.md', lines=3, extra=RULE + '\n\n')
    Session(tmp_path, tool, 'first').record(target, other)
    [entry, _] = Session(tmp_path, tool, 'reader').records()
    assert entry['limits'][0]['unit'] == 'lines' and len(entry['duplicates']) == 1
    # Slimmed under the line limit, with the duplicate's text reworded in both files.
    rules_file(target, lines=40, extra='A reworded rule that no other file states anywhere.\n\n')
    rules_file(other, lines=3, extra='Another rule entirely, for the second file only.\n\n')
    output = Session(tmp_path, tool, 'second').record(target, other)
    assert output['recorded'] == []
    assert Session(tmp_path, tool, 'reader').records() == []


def test_a_file_git_cannot_read_is_reported_not_recorded(tmp_path, tool):
    target = rules_file(repository(tmp_path) / 'AGENTS.md')
    session = Session(tmp_path, tool, 'first')
    measure, duplicates = session.slim_helper('measure', target), session.slim_helper('duplicates', target)
    session.env['PATH'] = str(tmp_path / 'no-git')
    result = session.run('record-over-limit', '--measure', measure, '--duplicates', duplicates)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    [row] = output['reported']
    assert output['recorded'] == [] and row['reason'].startswith('git could not be read')
    assert row['action'] == f'run /hippocampus:slim-harness on `{target}`'
