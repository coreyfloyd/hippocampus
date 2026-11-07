"""The unattended slim: the helper's command line against rule files recorded from real ones."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_over_limit_records import Session, git

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/lib/slim.py'
HARNESS = ROOT / 'skills/slim-harness/scripts/harness.py'
RULES = (ROOT / 'tests/fixtures/slim-harness/rules.md').read_text().splitlines(keepends=True)
SKILL = (ROOT / 'tests/fixtures/slim-harness/SKILL.md').read_text()
REPOSITORY = 'acme/rules'
ADDRESS = 'https://example.invalid/acme/rules.git'
# Real rules from the fixture, each once in it: the slims below cut these exact lines.
START = next(number for number, line in enumerate(RULES) if line.startswith('- **Questions are not authorization.**'))
CUT = ''.join(RULES[START:START + 2])
HEADING = '## Push back on contradictions (IMPORTANT)\n'


def text(lines):
    return ''.join(RULES[:lines])


class Remote:
    """A hosted repository: a bare remote behind a hosted address, and the user's checkout of it."""

    def __init__(self, tmp_path, name='rules', slug=REPOSITORY, address=ADDRESS):
        self.tmp, self.slug, self.address = tmp_path, slug, address
        self.bare = tmp_path / f'{name}.git'
        git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(self.bare))
        self.checkout = tmp_path / name
        self.checkout.mkdir()
        git(self.checkout, 'init', '-q', '-b', 'main')
        git(self.checkout, 'config', 'user.name', 'Example')
        git(self.checkout, 'config', 'user.email', 'example@example.invalid')
        git(self.checkout, 'remote', 'add', 'origin', address)

    def publish(self, files):
        """Commit files to the checkout and the hosted default branch."""
        for path, content in files.items():
            target = self.checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'Publish rules')
        git(self.checkout, 'push', '-q', str(self.bare), 'main')

    def show(self, branch, path):
        return git(self.bare, 'show', f'{branch}:{path}')

    def branches(self):
        return git(self.bare, 'for-each-ref', '--format=%(refname:short)', 'refs/heads').split()

    def snapshot(self):
        files = {path: path.read_bytes() for path in self.checkout.rglob('*')
                 if path.is_file() and '.git' not in path.parts}
        return files, git(self.checkout, 'rev-parse', 'HEAD'), git(self.checkout, 'status', '--porcelain')


class Slim:
    """The slim step's environment; wraps record into its store through the real commands."""

    def __init__(self, tmp_path, tool, *remotes):
        self.tmp, self.tool, self.remotes = tmp_path, tool, remotes
        self.session = Session(tmp_path, tool, 'wrap')
        self.configure()
        gitconfig = tmp_path / 'gitconfig'
        gitconfig.write_text('[user]\n\tname = Example\n\temail = example@example.invalid\n' + ''.join(
            f'[url "{remote.bare}"]\n\tinsteadOf = {remote.address}\n' for remote in remotes))
        self.env = {**self.session.env, 'GIT_CONFIG_GLOBAL': str(gitconfig)}
        self.count = 0

    def configure(self):
        (self.tmp / 'config.json').write_text(json.dumps({'auto_apply_lessons': True, 'slim_checkouts': {
            remote.slug: str(remote.checkout) for remote in self.remotes}}))

    def wrap(self, session='wrap'):
        """A wrap's session; starting one rewrites the shared configuration, so restore it."""
        wrap = Session(self.tmp, self.tool, session)
        self.configure()
        return wrap

    def records(self, *paths, session='wrap'):
        """A wrap's over-limit records, measured from the checkout's rules files, as a records file."""
        wrap = self.wrap(session)
        wrap.record(*paths)
        return self.export(wrap)

    def export(self, wrap=None):
        self.count += 1
        path = self.tmp / f'records-{self.count}.json'
        path.write_text(json.dumps({'records': (wrap or self.session).records()}))
        return path

    def run(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], text=True, capture_output=True,
                              env=self.env, cwd=self.tmp)

    def ok(self, *args):
        result = self.run(*args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def plan(self, *records):
        return self.ok('plan', *[arg for record in records for arg in ('--records', record)])

    def begin(self, run):
        return self.ok('begin', '--run', run['run_id'])

    def finish(self, run, result):
        self.count += 1
        path = self.tmp / f'result-{self.count}.json'
        path.write_text(json.dumps(result))
        return self.ok('finish', '--run', run['run_id'], '--result', path)

    def complete(self, run):
        """Finish every file with no edits and return the closed run."""
        while True:
            brief = self.begin(run)
            if brief['done']:
                return brief
            self.finish(run, {'left': 'Nothing could go without changing intent.'})


def cut_result(path=None, repository=REPOSITORY, old=CUT, **extra):
    return {'rules': [{'path': path or 'AGENTS.md', 'action': 'removed', 'text': old.strip(), 'reason': 'Default behavior.'}],
            'changes': [{'repository': repository, 'path': path or 'AGENTS.md', 'edits': [{'old': old, 'new': ''}]}],
            'left': 'The remaining rules are still needed.', **extra}


@pytest.fixture(params=['claude', 'codex'])
def tool(request):
    return request.param


@pytest.fixture
def remote(tmp_path):
    return Remote(tmp_path)


def test_a_run_analyzes_three_files_largest_overage_first(tmp_path, tool, remote):
    remote.publish({'a.md': text(230), 'b.md': text(260), 'c.md': text(290), 'd.md': text(308), 'small.md': text(100)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(*[remote.checkout / name for name in ('a.md', 'b.md', 'c.md', 'd.md', 'small.md')])
    run = slim.plan(records)
    assert run['queued'] == 5  # small.md shares rules with the others, so it is recorded with no overage.
    seen = []
    while True:
        brief = slim.begin(run)
        if brief['done']:
            break
        assert slim.begin(run)['path'] == brief['path'], 'a slim stays open until it is finished'
        seen.append(brief['path'])
        slim.finish(run, {'left': 'Nothing could go.'})
    assert seen == ['d.md', 'c.md', 'b.md']
    assert brief['analyzed'] == 3
    assert [row['path'] for row in brief['waiting']] == ['a.md', 'small.md']


def test_overage_compares_units_as_a_share_of_each_limit(tmp_path, tool, remote):
    remote.publish({'rules.md': text(290)})
    skill = remote.checkout / 'skills/x/SKILL.md'
    remote.publish({'skills/x/SKILL.md': SKILL})
    slim = Slim(tmp_path, tool, remote)
    wrap = slim.wrap()
    wrap.record(remote.checkout / 'rules.md', (skill, 'skill', 'full'))
    run = slim.plan(slim.export(wrap))
    # The skill is 10% over in body lines but 106% over in body bytes; rules.md is 45% over in lines.
    assert slim.begin(run)['path'] == 'skills/x/SKILL.md'


def test_records_of_one_file_from_several_machines_are_one_slim(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    first = slim.records(remote.checkout / 'AGENTS.md', session='first')
    second = tmp_path / 'other-machine.json'
    [row] = json.loads(first.read_text())['records']
    second.write_text(json.dumps({'records': [{**row, 'sessions': ['elsewhere'], 'last_recorded': '2999-01-01T00:00:00Z',
                                               'limits': [{**row['limits'][0], 'measured': 400}]}]}))
    run = slim.plan(first, second)
    assert run['queued'] == 1
    brief = slim.begin(run)
    assert [limit['measured'] for limit in brief['limits']] == [400]


def test_a_slim_cuts_a_branch_from_the_hosted_default_and_leaves_the_checkout_alone(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    # A lesson committed locally and an unsaved edit: neither may reach the slim's branch.
    (remote.checkout / 'AGENTS.md').write_text(text(308) + 'A lesson committed here.\n')
    git(remote.checkout, 'commit', '-q', '-am', 'lesson: A lesson')
    (remote.checkout / 'AGENTS.md').write_text(text(308) + 'A lesson committed here.\nUnsaved work.\n')
    before = remote.snapshot()
    run = slim.plan(records)
    brief = slim.begin(run)
    assert Path(brief['file']).read_text() == text(308)
    finished = slim.finish(run, cut_result())
    assert finished['status'] == 'slimmed'
    closed = slim.begin(run)
    [branch] = finished['branches']
    assert remote.snapshot() == before
    assert sorted(remote.branches()) == sorted(['main', branch['branch']])
    assert CUT.strip() not in remote.show(branch['branch'], 'AGENTS.md')
    assert 'A lesson committed here' not in remote.show(branch['branch'], 'AGENTS.md')
    assert remote.show('main', 'AGENTS.md') == text(308).rstrip('\n'), 'the package never merges'
    log = git(remote.bare, 'log', '--format=%s', f"main..{branch['branch']}").splitlines()
    assert log == ['slim: AGENTS.md']
    [ask] = closed['asks']
    assert ask['choices'] == [] and 'default' not in ask and 'deadline' not in ask
    assert not Path(brief['file']).exists(), 'the temporary clone is removed'


def test_a_duplicate_is_removed_and_a_contradiction_listed_first(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308), 'owner.md': text(60)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md', remote.checkout / 'owner.md')
    [entry] = [row for row in json.loads(records.read_text())['records'] if row['path'] == 'AGENTS.md']
    assert entry['duplicates'], 'the wrap recorded the cross-file duplicate'
    run = slim.plan(records)
    brief = slim.begin(run)
    assert brief['path'] == 'AGENTS.md' and brief['duplicates']
    slim.finish(run, {
        'contradictions': [{'rules': 'AGENTS.md says wait; owner.md says act.', 'winner': 'wait', 'reason': 'Safer.'}],
        'duplicates': [{'rule': CUT.strip(), 'owner': 'owner.md', 'reason': 'It keeps the procedure.'}],
        'rules': [{'path': 'AGENTS.md', 'action': 'removed', 'text': CUT.strip(), 'reason': 'Owned by owner.md.'}],
        'changes': [{'path': 'AGENTS.md', 'edits': [{'old': CUT, 'new': ''}]}],
        'left': 'The rest is in use.'})
    # The other file was recorded too, and shares no change, so it is slimmed next.
    assert slim.begin(run)['path'] == 'owner.md'
    slim.finish(run, {})
    [ask] = slim.begin(run)['asks']
    positions = [ask['text'].index(title) for title in (
        'Contradictions and the winner chosen:', 'Cross-file duplicates and the owner chosen:',
        'Rules removed or rewritten:', 'Sizes against each limit:', 'Branches:', 'To undo or stop it:')]
    assert positions == sorted(positions)
    assert 'Winner: wait' in ask['text'] and 'Owner: owner.md' in ask['text']
    assert f'{tool} lines: 308 before, 306 after, limit 200' in ask['text']
    assert CUT.strip() in remote.show('main', 'owner.md'), 'the owner keeps the rule'


def test_a_best_effort_result_says_what_is_left_and_why(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    run = slim.plan(slim.records(remote.checkout / 'AGENTS.md'))
    slim.begin(run)
    without = {key: value for key, value in cut_result().items() if key != 'left'}
    path = tmp_path / 'incomplete.json'
    path.write_text(json.dumps(without))
    refused = slim.run('finish', '--run', run['run_id'], '--result', path)
    assert refused.returncode == 1 and 'requires left' in refused.stderr
    assert remote.branches() == ['main'], 'a refused result changes nothing'
    assert slim.finish(run, cut_result(left='100 lines over: every remaining rule is a boundary.'))['status'] == 'slimmed'
    [ask] = slim.begin(run)['asks']
    assert 'Still over a limit: 100 lines over: every remaining rule is a boundary.' in ask['text']


def test_a_file_awaiting_its_decision_is_skipped_by_later_runs(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    run = slim.plan(records)
    slim.begin(run)
    slim.finish(run, cut_result())
    slim.begin(run)
    later = slim.plan(records)
    assert later['queued'] == 0
    assert [row['reason'] for row in later['skipped']] == ['slim branch awaiting its decision']


def rejected(slim, remote, records):
    run = slim.plan(records)
    slim.begin(run)
    [branch] = slim.finish(run, cut_result())['branches']
    slim.begin(run)
    return branch['branch']


def test_a_rejected_file_waits_until_a_session_measures_it_larger(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    branch = rejected(slim, remote, records)
    assert slim.ok('decide', '--repository', REPOSITORY, '--branch', branch, '--decision', 'rejected')['status'] == 'rejected'
    later = slim.plan(records)
    assert later['queued'] == 0
    [row] = later['skipped']
    assert row['line'].startswith('over limit, slim rejected: acme/rules AGENTS.md')
    remote.publish({'AGENTS.md': text(308) + 'A rule added after the rejection.\n'})
    assert slim.plan(slim.records(remote.checkout / 'AGENTS.md'))['queued'] == 1


def test_a_branch_deleted_without_merging_is_a_rejection(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    branch = rejected(slim, remote, records)
    git(remote.bare, 'branch', '-q', '-D', branch)
    assert [row['reason'] for row in slim.plan(records)['skipped']] == ['over limit, slim rejected']


def test_a_merged_branch_frees_the_file(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    branch = rejected(slim, remote, records)
    remote.publish({'AGENTS.md': text(308).replace(CUT, '')})  # The user's own automation merged it.
    git(remote.bare, 'branch', '-q', '-D', branch)
    later = slim.plan(records)
    assert later['skipped'] == [] and later['queued'] == 1


def test_a_later_merge_replaces_an_earlier_rejection(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    branch = rejected(slim, remote, slim.records(remote.checkout / 'AGENTS.md'))
    slim.ok('decide', '--repository', REPOSITORY, '--branch', branch, '--decision', 'rejected')
    remote.publish({'AGENTS.md': text(308) + 'A rule added after the rejection.\n'})
    records = slim.records(remote.checkout / 'AGENTS.md')
    branch = rejected(slim, remote, records)
    slim.ok('decide', '--repository', REPOSITORY, '--branch', branch, '--decision', 'merged')
    # After the merge the file is smaller than at the rejection, and still over its limit.
    remote.publish({'AGENTS.md': text(250)})
    later = slim.plan(slim.records(remote.checkout / 'AGENTS.md'))
    assert later['skipped'] == [] and later['queued'] == 1


def test_a_file_an_earlier_slim_changed_is_left_alone_and_deferred(tmp_path, tool, remote):
    remote.publish({'first.md': text(308), 'second.md': text(280), 'third.md': text(260)})
    slim = Slim(tmp_path, tool, remote)
    run = slim.plan(slim.records(*[remote.checkout / name for name in ('first.md', 'second.md', 'third.md')]))
    assert slim.begin(run)['path'] == 'first.md'
    # The first slim also reaches third.md, which is itself recorded.
    result = cut_result('first.md')
    result['changes'].append({'path': 'third.md', 'edits': [{'old': CUT, 'new': ''}]})
    [first] = slim.finish(run, result)['branches']
    brief = slim.begin(run)
    assert brief['path'] == 'second.md'
    assert {'repository': REPOSITORY, 'path': 'first.md', 'changed_by': first['branch']} in brief['frozen']
    # The second slim tries to edit a frozen file: that edit is dropped, its own stands.
    result = cut_result('second.md')
    result['changes'].append({'path': 'first.md', 'edits': [{'old': HEADING, 'new': '## Contradictions\n'}]})
    [second] = slim.finish(run, result)['branches']
    assert second['changed'] == ['second.md']
    closed = slim.begin(run)
    assert closed['analyzed'] == 2, 'a deferred file is not analyzed'
    assert [row['path'] for row in closed['deferred']] == ['third.md']
    first_ask = next(ask for ask in closed['asks'] if ask['path'] == 'first.md')
    second_ask = next(ask for ask in closed['asks'] if ask['path'] == 'second.md')
    assert 'Deferred to a later run' in second_ask['text'] and 'acme/rules first.md: already changed by' in second_ask['text']
    assert 'acme/rules third.md: already changed by' in first_ask['text']
    assert HEADING.strip() in remote.show(first['branch'], 'first.md')
    assert HEADING.strip() in remote.show(second['branch'], 'second.md')


def test_a_frozen_file_defers_every_change_grouped_with_it(tmp_path, tool, remote):
    remote.publish({'first.md': text(308), 'second.md': text(280), 'other.md': text(50)})
    slim = Slim(tmp_path, tool, remote)
    run = slim.plan(slim.records(remote.checkout / 'first.md', remote.checkout / 'second.md'))
    slim.begin(run)
    slim.finish(run, cut_result('first.md'))
    slim.begin(run)
    result = cut_result('second.md')
    result['changes'] = [
        {'path': 'second.md', 'group': 'move', 'edits': [{'old': CUT, 'new': ''}]},
        {'path': 'first.md', 'group': 'move', 'edits': [{'new': CUT}]}]
    assert slim.finish(run, result)['status'] == 'unchanged'
    assert len(remote.branches()) == 2


def test_edits_in_two_repositories_make_one_branch_each_under_one_ask(tmp_path, tool, remote):
    other = Remote(tmp_path, 'shared', 'acme/shared', 'https://example.invalid/acme/shared.git')
    remote.publish({'AGENTS.md': text(308)})
    other.publish({'core.md': text(60)})
    slim = Slim(tmp_path, tool, remote, other)
    run = slim.plan(slim.records(remote.checkout / 'AGENTS.md'))
    slim.begin(run)
    workspace = slim.ok('workspace', '--run', run['run_id'], '--repository', 'acme/shared')['workspace']
    assert (Path(workspace) / 'core.md').read_text() == text(60)
    result = cut_result()
    result['changes'].append({'repository': 'acme/shared', 'path': 'core.md', 'edits': [{'old': HEADING, 'new': '## Pushback\n'}]})
    branches = slim.finish(run, result)['branches']
    assert [row['repository'] for row in branches] == [REPOSITORY, 'acme/shared']
    assert len(other.branches()) == 2
    [ask] = slim.begin(run)['asks']
    assert 'acme/rules slim/' in ask['text'] and 'acme/shared slim/' in ask['text']


def routing(tmp_path, source, surface):
    (tmp_path / 'routing.md').write_text(f'# Routing\n\nProduced surfaces:\n  {source}:\n    - path: {surface}\n'
                                         '      regeneration command: compose --refresh\n')


def test_an_unverified_surface_produces_no_branch_and_an_ordinary_ask(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    surface = tmp_path / 'composed.md'
    routing(tmp_path, remote.checkout.resolve() / 'AGENTS.md', surface)
    run = slim.plan(records)
    assert [row['path'] for row in slim.begin(run)['surfaces']] == [str(surface)]
    assert slim.finish(run, cut_result())['status'] == 'unverified'
    closed = slim.begin(run)
    assert remote.branches() == ['main']
    [ask] = closed['asks']
    assert 'produced no branch' in ask['text'] and str(surface) in ask['text']
    assert ask['choices'] and not ask['applied']


def test_a_verified_surface_builds_the_branch_and_names_its_regeneration(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    surface = tmp_path / 'composed.md'
    routing(tmp_path, remote.checkout.resolve() / 'AGENTS.md', surface)
    run = slim.plan(records)
    slim.begin(run)
    assert slim.finish(run, cut_result(surfaces_verified=[str(surface)]))['status'] == 'slimmed'
    [ask] = slim.begin(run)['asks']
    assert 'compose --refresh' in ask['text'] and ask['choices'] == []


def test_an_undelivered_ask_returns_until_its_receipt(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    run = slim.plan(records)
    slim.begin(run)
    slim.finish(run, cut_result())
    [ask] = slim.begin(run)['asks']
    assert slim.plan(records)['undelivered_asks'] == [ask]
    slim.ok('ask-delivered', '--ask', ask['id'], '--receipt', 'delivered-1')
    assert slim.plan(records)['undelivered_asks'] == []


def test_a_repository_with_no_checkout_is_reported_and_waits(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    (tmp_path / 'config.json').write_text(json.dumps({'auto_apply_lessons': True}))
    run = slim.plan(records)
    assert run['queued'] == 0
    assert 'slim_checkouts' in run['unreachable'][0]['reason']


def test_the_setting_off_or_a_propose_policy_refuses(tmp_path, tool, remote):
    remote.publish({'AGENTS.md': text(308)})
    slim = Slim(tmp_path, tool, remote)
    records = slim.records(remote.checkout / 'AGENTS.md')
    (tmp_path / 'routing.md').write_text('# Routing\n\nlesson-policy: propose\n')
    refused = slim.run('plan', '--records', records)
    assert refused.returncode == 1 and 'requires it' in refused.stderr
    (tmp_path / 'routing.md').write_text('# Routing\n')
    (tmp_path / 'config.json').write_text('{}')
    refused = slim.run('plan', '--records', records)
    assert refused.returncode == 1 and 'the auto-apply setting is off' in refused.stderr
    assert not (tmp_path / 'ledger/slim-state.json').exists()


@pytest.mark.parametrize('setting', [True, False])
def test_the_attended_review_still_refuses_to_run_unattended(tmp_path, setting):
    target = tmp_path / 'AGENTS.md'
    target.write_text(text(308))
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'path': str(target), 'before': HEADING, 'after': '## Other\n', 'mode': 'unattended'}))
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'auto_apply_lessons': setting}))
    result = subprocess.run([sys.executable, str(HARNESS), 'edit', str(request), str(tmp_path / 'journal.json')],
                            text=True, capture_output=True, env={**os.environ, 'HIPPOCAMPUS_CONFIG': str(config)})
    assert json.loads(result.stdout)['needs_user'] is True
    assert target.read_text() == text(308)
    skill = (ROOT / 'skills/slim-harness/SKILL.md').read_text()
    assert 'needs the user present; edited nothing' in skill
    assert 'This skill **never commits**' in skill


def test_the_documents_state_the_ask_and_the_levels():
    glossary = (ROOT / 'docs/glossary.md').read_text()
    assert 'An ask is text: it reports what happened and how to undo or stop it, and carries no choice that runs anything.' in glossary
    guide = (ROOT / 'docs/session-guide.md').read_text()
    for level in ('Low', 'Medium', 'High', 'Critical'):
        assert f'| {level} |' in guide
    assert 'slim-unattended' in guide and 'ships no scheduler' in guide
