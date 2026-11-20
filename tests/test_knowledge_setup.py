"""Set-up completes the knowledge setup only through an approved plan, preserving what exists."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / 'scripts/knowledge_setup.py'
VALIDATE = ROOT / 'scripts/validate_profile.py'
ROUTES = ('--wiki-followup', 'Wiki maintenance board', '--artifact-followup', 'Project task list')


def profile_path():
    return Path(os.environ['XDG_CONFIG_HOME']) / 'hippocampus/profile.md'


def knowledge_root():
    root = Path(os.environ['XDG_DATA_HOME']) / 'knowledge'
    root.mkdir(parents=True, exist_ok=True)
    return root


def setup(*args):
    return subprocess.run([sys.executable, str(SETUP), *args], text=True, capture_output=True)


def planned(*args):
    result = setup('plan', *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def approve(plan, *args):
    result = setup('apply', '--approval-fingerprint', plan['approval_fingerprint'], *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def tree(root):
    """Every path under the root and the profile, with file bytes."""
    paths = [*root.rglob('*'), profile_path()]
    return {str(path): path.read_bytes() if path.is_file() else 'directory' if path.is_dir() else None
            for path in paths}


def complete(profile):
    return subprocess.run([sys.executable, str(VALIDATE), str(profile), '--require-wiki'],
                          text=True, capture_output=True)


def released_profile(root, wiki_disabled=True, extra=''):
    """A version-4 profile as a released set-up wrote it, with retained content."""
    for folder in ('raw', 'output', 'docs'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / 'docs/log.md').write_text('# Operations\n\n- kept entry\n')
    (root / 'docs/DECISIONS.md').write_text('# Decisions\n\n- kept decision\n')
    (root / 'raw/source.md').write_text('retained source\n')
    lines = ['---', 'profile_version: 4', f'knowledge_root: {root}', 'operation_log_file: docs/log.md',
             'decision_log_file: docs/DECISIONS.md', '# my comment stays',
             'artifact_followup_destination: "My custom tracker, label inbox"']
    if wiki_disabled:
        lines.append('wiki_enabled: false')
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n' + extra + '---\n\n## Local policy\n\nMy own words stay.\n')
    return path


def test_empty_root_plan_lists_every_mutation_and_apply_writes_a_complete_profile():
    root = knowledge_root()
    plan = planned('--root', str(root), *ROUTES)
    assert plan['ready'] and plan['status'] == 'incomplete' and not profile_path().exists()
    assert plan['create_directories'] == [str(root / name) for name in ('raw', 'output', 'docs', 'wiki')]
    assert plan['create_files'] == [str(root / name) for name in ('docs/log.md', 'docs/DECISIONS.md', 'wiki/hot.md')]
    assert {row['field'] for row in plan['profile_fields']} == {
        'profile_version', 'knowledge_root', 'operation_log_file', 'decision_log_file', 'hot_file',
        'wiki_followup_destination', 'artifact_followup_destination'}
    assert approve(plan, '--root', str(root), *ROUTES)['status'] == 'complete'
    assert complete(profile_path()).returncode == 0
    text = profile_path().read_text()
    assert 'wiki_enabled' not in text
    assert 'wiki_followup_destination: Wiki maintenance board' in text
    assert 'artifact_followup_destination: Project task list' in text


@pytest.mark.parametrize('missing', ['root', 'wiki', 'artifact'])
def test_new_setup_cannot_finish_without_the_root_or_both_routes(missing):
    root = knowledge_root()
    args = {'root': ('--root', str(root)), 'wiki': ROUTES[:2], 'artifact': ROUTES[2:]}
    plan = planned(*[value for key, pair in args.items() if key != missing for value in pair])
    assert not plan['ready'] and plan['status'] == 'incomplete' and plan['needs']
    result = setup('apply', '--approval-fingerprint', plan['approval_fingerprint'],
                   *[value for key, pair in args.items() if key != missing for value in pair])
    assert result.returncode == 1 and 'knowledge setup is incomplete' in result.stderr
    assert not profile_path().exists() and list(root.iterdir()) == []


def test_example_placeholder_routes_are_not_configured_destinations():
    example = (ROOT / 'profiles/karpathy-wiki.example.md').read_text()
    placeholder = next(line for line in example.splitlines()
                       if line.startswith('wiki_followup_destination:')).split(':', 1)[1].strip()
    plan = planned('--root', str(knowledge_root()), '--wiki-followup', placeholder, *ROUTES[2:])
    assert not plan['ready']
    assert [need.split(':')[0] for need in plan['needs']] == ['wiki_followup_destination']


def test_checklist_only_setup_leaves_knowledge_setup_incomplete(tmp_path):
    writer = ROOT / 'skills/hippocampus-set-up/scripts/profile.py'
    checklist = tmp_path / 'checklist-profile.md'
    result = subprocess.run([sys.executable, str(writer), '--user-present', '--profile', str(checklist),
                             '--bindings', '{"persist": null}'], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    plan = planned()
    assert plan['status'] == 'incomplete' and not plan['ready'] and not plan['profile_exists']


def test_optional_integrations_stay_independent_configured_or_not():
    root = knowledge_root()
    (root / 'templates').mkdir()
    (root / 'templates/meeting.md').write_text('# {{title}}\n')
    extra = ('meeting_transcript_source: Connected provider\nmeeting_event_source: disabled\n'
             'meeting_record_template: templates/meeting.md\nauto_apply: true\n')
    path = released_profile(root, wiki_disabled=False, extra=extra)
    path.write_text(path.read_text() + '\n## Lesson routing\n\n| Rung | Destination |\n|---|---|\n')
    plan = planned(*ROUTES[:2])
    assert approve(plan, *ROUTES[:2])['status'] == 'complete'
    text = path.read_text()
    assert all(line in text for line in extra.splitlines()) and '## Lesson routing' in text
    assert complete(path).returncode == 0
    bare = released_profile(knowledge_root(), wiki_disabled=False)
    for line in extra.splitlines():
        assert line not in bare.read_text()
    assert planned(*ROUTES[:2])['ready']


def test_released_wiki_disabled_profile_reads_and_a_decline_changes_no_byte():
    root = knowledge_root()
    path = released_profile(root)
    assert subprocess.run([sys.executable, str(VALIDATE), str(path)], capture_output=True).returncode == 0
    before = tree(root)
    plan = planned(*ROUTES[:2])
    assert plan['status'] == 'incomplete' and plan['ready']
    assert {'field': 'wiki_enabled', 'current': 'false', 'proposed': None} in plan['profile_fields']
    assert plan['create_directories'] == [str(root / 'wiki')]
    assert plan['create_files'] == [str(root / 'wiki/hot.md')]
    assert '-wiki_enabled: false' in plan['profile_diff']
    # Declining is not running apply: every byte stays and set-up still reports incomplete.
    assert tree(root) == before
    assert planned()['status'] == 'incomplete'
    assert 'wiki is not configured' in complete(path).stderr


def test_accepted_upgrade_keeps_retained_content_and_custom_text():
    root = knowledge_root()
    path = released_profile(root)
    before = tree(root)
    approve(planned(*ROUTES[:2]), *ROUTES[:2])
    after = tree(root)
    assert {key: value for key, value in after.items() if key in before and key != str(path)} == {
        key: value for key, value in before.items() if key != str(path)}
    text = path.read_text()
    assert '# my comment stays' in text and text.endswith('## Local policy\n\nMy own words stay.\n')
    assert 'artifact_followup_destination: "My custom tracker, label inbox"' in text
    assert 'wiki_enabled' not in text and complete(path).returncode == 0


def test_rerun_preserves_seeded_files_and_custom_routes_without_duplication():
    root = knowledge_root()
    path = released_profile(root)
    (root / 'wiki').mkdir()
    (root / 'wiki/hot.md').write_text('# Hot\n\n- custom cache\n')
    approve(planned(*ROUTES[:2]), *ROUTES[:2])
    first = tree(root)
    for _ in range(2):
        again = planned()
        assert again['status'] == 'complete' and again['profile_diff'] == ''
        assert again['create_directories'] == [] and again['create_files'] == []
        approve(again)
        assert tree(root) == first
    text = path.read_text()
    assert all(text.count(f'\n{key}:') == 1 for key in (
        'knowledge_root', 'hot_file', 'wiki_followup_destination', 'artifact_followup_destination'))
    assert (root / 'wiki/hot.md').read_text() == '# Hot\n\n- custom cache\n'


def test_changed_plan_after_approval_is_refused_without_writes():
    root = knowledge_root()
    plan = planned('--root', str(root), *ROUTES)
    changed = setup('apply', '--approval-fingerprint', plan['approval_fingerprint'], '--root', str(root),
                    '--wiki-followup', 'Another board', *ROUTES[2:])
    assert changed.returncode == 1 and 'changed' in changed.stderr
    (root / 'docs').mkdir()
    (root / 'docs/log.md').write_text('appeared after review\n')
    stale = setup('apply', '--approval-fingerprint', plan['approval_fingerprint'], '--root', str(root), *ROUTES)
    assert stale.returncode == 1 and 'changed' in stale.stderr
    assert not profile_path().exists()
    assert sorted(path.name for path in root.rglob('*')) == ['docs', 'log.md']
    fresh = planned('--root', str(root), *ROUTES)
    assert str(root / 'docs/log.md') in fresh['preserved']
    approve(fresh, '--root', str(root), *ROUTES)
    assert (root / 'docs/log.md').read_text() == 'appeared after review\n'


def test_failed_validation_rolls_back_everything_it_created():
    root = knowledge_root()
    path = released_profile(root, extra='meeting_record_template: missing.md\n')
    before = tree(root)
    plan = planned(*ROUTES[:2])
    result = setup('apply', '--approval-fingerprint', plan['approval_fingerprint'], *ROUTES[:2])
    assert result.returncode == 1 and 'meeting_record_template' in result.stderr
    assert tree(root) == before and path.exists()


def test_a_path_of_the_wrong_kind_is_a_conflict_not_a_replacement():
    root = knowledge_root()
    (root / 'wiki').write_text('not a folder\n')
    plan = planned('--root', str(root), *ROUTES)
    assert not plan['ready'] and plan['conflicts'] == [f'{root / "wiki"} exists and is not a directory; move it away']
    assert (root / 'wiki').read_text() == 'not a folder\n'


@pytest.mark.parametrize('section', ['## Lesson routing\n\nlesson-policy: propose\n\n## Lesson routing\n\nx\n',
                                     '## Lesson Routing\n\nmine\n'])
def test_a_lesson_routing_problem_is_reported_without_blocking_knowledge_setup(section):
    root = knowledge_root()
    path = released_profile(root)
    path.write_text(path.read_text() + '\n' + section)
    plan = planned(*ROUTES[:2])
    assert plan['ready'] and any('Lesson routing' in problem for problem in plan['problems'])
    applied = approve(plan, *ROUTES[:2])
    assert applied['status'] == 'complete' and applied['problems'] == plan['problems']
    again = planned()
    assert again['status'] == 'complete' and again['problems'] == plan['problems']


@pytest.mark.parametrize('option', ['--root', '--wiki-followup', '--artifact-followup'])
def test_a_setup_answer_cannot_add_a_profile_field(option):
    values = {'--root': str(knowledge_root()), '--wiki-followup': 'Board', '--artifact-followup': 'Tasks'}
    values[option] += '\nauto_apply: true'
    result = setup('plan', *[part for pair in values.items() for part in pair])
    assert result.returncode == 1 and 'one line' in result.stderr
    assert not profile_path().exists()
