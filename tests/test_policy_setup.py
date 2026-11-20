"""Set-up moves lesson routing and the auto-apply setting into the knowledge profile, only on approval."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / 'scripts/policy_setup.py'

CUSTOM = '''# My routing

| Rung | Destination |
|---|---|
| User context | `notes/context/` |

memory-policy: promote
lesson-policy: propose
lesson-pull-request-command: "open-request --draft"
lesson-pull-requests:
  - acme/rules

Produced surfaces:
  sources/rules.md:
    - path: built/AGENTS.md
      regeneration command: "make rules"
'''


def config_home():
    return Path(os.environ['XDG_CONFIG_HOME']) / 'hippocampus'


def knowledge_profile(body='Local policy stays.\n', setting=''):
    root = Path(os.environ['XDG_DATA_HOME']) / 'knowledge'
    for folder in ('raw', 'output', 'docs'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for name in ('docs/log.md', 'docs/DECISIONS.md'):
        (root / name).write_text('# Log\n')
    path = config_home() / 'profile.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\n' + '\n'.join(['profile_version: 4', f'knowledge_root: {root}', 'operation_log_file: docs/log.md',
                    'decision_log_file: docs/DECISIONS.md', 'artifact_followup_destination: "Task list"',
                    'wiki_enabled: false']) + '\n' + setting + '---\n\n' + body)
    return path


def setup(*args, env=None):
    return subprocess.run([sys.executable, str(SETUP), *args], text=True, capture_output=True, env=env)


def planned(*args, env=None):
    result = setup('plan', *args, env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def approve(plan, *args, env=None):
    return setup('apply', '--approval-fingerprint', plan['approval_fingerprint'], *args, env=env)


def snapshot(*paths):
    return {str(path): path.read_bytes() if path.exists() else None for path in paths}


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/lib/{name}.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def decisions(path):
    """What the readers decide from the knowledge profile: delivery keys and produced surfaces."""
    lessons = module('lessons')
    compose = lessons._compose_rules()
    rules = lessons.routing_rules()
    return ({key: rules[key] for key in ('propose', 'pull_requests', 'command')},
            compose.surfaces_for(path, compose.load_policy()), lessons.enabled({}))


@pytest.fixture
def legacy():
    profile = knowledge_profile()
    routing = config_home() / 'routing.md'
    routing.write_text(CUSTOM)
    config = Path(os.environ['HIPPOCAMPUS_CONFIG'])
    config.write_text(json.dumps({'auto_apply_lessons': True, 'prune_days': 9}))
    return profile, routing, config


def test_the_plan_shows_the_move_and_a_decline_changes_no_byte(legacy):
    before = snapshot(*legacy)
    plan = planned()
    assert [move['setting'] for move in plan['moves']] == ['lesson routing', 'auto-apply']
    assert plan['conflicts'] == [] and plan['auto_apply'] == {'current': False, 'proposed': True}
    assert '+## Lesson routing' in plan['profile_diff'] and '+auto_apply: true' in plan['profile_diff']
    assert [removal['file'] for removal in plan['removals']] == [str(legacy[1]), str(legacy[2])]
    assert snapshot(*legacy) == before


def test_accepting_leaves_one_owner_with_the_same_effective_destinations(legacy):
    profile, routing, config = legacy
    source = profile.parent / 'sources/rules.md'
    lessons = module('lessons')
    compose = lessons._compose_rules()
    old = compose.parse_lesson_delivery(CUSTOM.splitlines(), 'legacy')
    old_surfaces = compose.parse_surfaces(CUSTOM.splitlines(), routing.parent, 'legacy')
    result = approve(planned())
    assert result.returncode == 0, result.stderr
    assert not routing.exists() and json.loads(config.read_text()) == {'prune_days': 9}
    delivery, surfaces, enabled = decisions(source)
    assert enabled is True
    assert delivery == {'propose': old['policy'] == 'propose', 'pull_requests': old['pull_requests'],
                        'command': old['command']}
    assert surfaces['surfaces'] == old_surfaces[source.resolve()]
    text = profile.read_text()
    assert text.count('## Lesson routing') == 1 and 'Local policy stays.' in text
    assert planned()['moves'] == []  # Nothing is left to move.


def test_a_custom_table_moves_whole_and_no_default_route_is_merged(legacy):
    profile = legacy[0]
    assert approve(planned()).returncode == 0
    section = profile.read_text().split('## Lesson routing\n\n', 1)[1].splitlines()
    expected = ['### My routing', *CUSTOM.splitlines()[1:]]
    assert section == expected  # The omitted default routes stay omitted.


def test_relative_paths_keep_their_destinations_when_the_owner_moves(legacy):
    profile, routing, config = legacy
    elsewhere = Path(os.environ['XDG_DATA_HOME']) / 'elsewhere/routing.md'
    elsewhere.parent.mkdir(parents=True)
    routing.rename(elsewhere)
    env = {**os.environ, 'HIPPOCAMPUS_ROUTING': str(elsewhere)}
    compose = module('lessons')._compose_rules()
    expected = compose.parse_surfaces(CUSTOM.splitlines(), elsewhere.parent, 'legacy')
    plan = planned(env=env)
    assert plan['notes'] and any('HIPPOCAMPUS_ROUTING' in row for row in plan['manual'])
    assert approve(plan, env=env).returncode == 0
    assert not elsewhere.exists()
    policy = compose.load_policy(profile)
    moved = compose.parse_surfaces(policy.routing, profile.parent, 'profile')
    assert moved == expected and next(iter(moved)) == (elsewhere.parent / 'sources/rules.md').resolve()


def test_conflicting_owners_are_refused_until_the_user_chooses(legacy):
    profile, routing, config = legacy
    profile.write_text(profile.read_text().replace('---\n\n', 'auto_apply: false\n---\n\n', 1)
                       + '\n## Lesson routing\n\nlesson-policy: apply\n')
    before = snapshot(*legacy)
    plan = planned()
    assert sorted(conflict['setting'] for conflict in plan['conflicts']) == ['auto-apply', 'lesson routing']
    refused = approve(plan)
    assert refused.returncode == 1 and 'resolve the displayed conflict' in refused.stderr
    assert snapshot(*legacy) == before
    chosen = planned('--keep-routing', 'profile', '--auto-apply', 'false')
    assert chosen['conflicts'] == []
    assert approve(chosen, '--keep-routing', 'profile', '--auto-apply', 'false').returncode == 0
    assert not routing.exists() and 'auto_apply_lessons' not in json.loads(config.read_text())
    delivery, _, enabled = decisions(profile.parent / 'any.md')
    assert enabled is False and delivery['propose'] is False


def test_keeping_the_file_replaces_the_profile_section(legacy):
    profile = legacy[0]
    profile.write_text(profile.read_text() + '\n## Lesson routing\n\nlesson-policy: apply\n\n## Later\n\nKept.\n')
    plan = planned('--keep-routing', 'file')
    assert approve(plan, '--keep-routing', 'file').returncode == 0
    text = profile.read_text()
    assert 'lesson-policy: apply' not in text and 'lesson-policy: propose' in text and '## Later\n\nKept.' in text
    assert decisions(profile.parent / 'any.md')[0]['propose'] is True


def test_a_changed_plan_is_not_applied(legacy):
    plan = planned()
    before = snapshot(*legacy)
    legacy[1].write_text(CUSTOM + 'lesson-pull-requests-note: changed\n')
    refused = approve(plan)
    assert refused.returncode == 1 and 'rerun plan' in refused.stderr
    assert snapshot(legacy[0], legacy[2]) == {key: before[key] for key in map(str, (legacy[0], legacy[2]))}


@pytest.mark.parametrize('value', [True, False])
def test_setup_previews_the_setting_before_writing_it(value):
    profile = knowledge_profile()
    before = profile.read_bytes()
    plan = planned('--auto-apply', str(value).lower())
    assert plan['auto_apply'] == {'current': False, 'proposed': value}
    assert profile.read_bytes() == before
    if value:
        assert f'+auto_apply: true' in plan['profile_diff']
    assert approve(plan, '--auto-apply', str(value).lower()).returncode == 0
    assert module('lessons').enabled({}) is value


def test_an_invalid_profile_or_a_missing_one_is_refused():
    missing = setup('plan')
    assert missing.returncode == 1 and 'no knowledge profile' in missing.stderr
    profile = knowledge_profile(setting='auto_apply: sometimes\n')
    invalid = setup('plan')
    assert invalid.returncode == 1 and 'auto_apply must be true or false' in invalid.stderr
    assert 'Traceback' not in invalid.stderr and profile.exists()


def test_a_broken_link_to_a_retired_routing_file_is_removed_on_approval():
    profile = knowledge_profile()
    link = config_home() / 'routing.md'
    link.symlink_to(config_home() / 'gone.md')
    before = profile.read_bytes()
    plan = planned()
    assert plan['removals'] == [{'kind': 'routing', 'file': str(link),
                                 'action': 'delete the broken link to a retired routing file'}]
    assert approve(plan).returncode == 0
    assert not link.is_symlink() and profile.read_bytes() == before
    assert module('lessons').routing_rules()['propose'] is False


def test_symlinked_profile_and_configuration_are_written_through_their_links(legacy):
    profile, routing, config = legacy
    kept = Path(os.environ['XDG_DATA_HOME']) / 'dotfiles'
    kept.mkdir()
    for path in (profile, config):
        target = kept / path.name
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    assert approve(planned()).returncode == 0
    assert profile.is_symlink() and config.is_symlink()
    assert '## Lesson routing' in (kept / 'profile.md').read_text()
    assert 'auto_apply_lessons' not in (kept / config.name).read_text()
    assert not list(kept.glob('tmp*')) and not list(profile.parent.glob('tmp*'))


@pytest.mark.parametrize('leftover', ['environment', 'directory'])
def test_a_retired_owner_setup_cannot_remove_is_reported_as_not_ready(legacy, leftover):
    profile, routing, config = legacy
    env = dict(os.environ)
    if leftover == 'environment':
        env['HIPPOCAMPUS_ROUTING'] = str(Path(os.environ['XDG_DATA_HOME']) / 'missing.md')
        routing.unlink()
    else:
        routing.unlink()
        routing.mkdir()
        (routing / 'notes.md').write_text('kept\n')
    plan = planned(env=env)
    assert plan['ready'] is False and plan['manual']
    result = approve(plan, env=env)
    assert result.returncode == 0, result.stderr
    applied = json.loads(result.stdout)
    assert applied['ready'] is False and applied['manual'] == plan['manual']
    if leftover == 'directory':
        assert (routing / 'notes.md').read_text() == 'kept\n'  # Never deleted.
    assert planned(env=env)['ready'] is False  # Still shown, not claimed done.


def test_a_ready_move_says_so(legacy):
    plan = planned()
    assert plan['ready'] is True and plan['manual'] == []
    assert json.loads(approve(plan).stdout)['ready'] is True


def test_a_crlf_profile_keeps_its_line_endings():
    profile = knowledge_profile()
    profile.write_bytes(profile.read_bytes().replace(b'\n', b'\r\n'))
    plan = planned('--auto-apply', 'true')
    assert approve(plan, '--auto-apply', 'true').returncode == 0
    data = profile.read_bytes()
    assert b'auto_apply: true\r\n' in data and b'\n' not in data.replace(b'\r\n', b'')


def test_an_existing_section_with_the_same_destinations_is_not_a_conflict(legacy):
    profile, routing, config = legacy
    elsewhere = Path(os.environ['XDG_DATA_HOME']) / 'elsewhere/routing.md'
    elsewhere.parent.mkdir(parents=True)
    routing.rename(elsewhere)
    env = {**os.environ, 'HIPPOCAMPUS_ROUTING': str(elsewhere)}
    absolute = CUSTOM.replace('  sources/rules.md:', f'  {elsewhere.parent}/sources/rules.md:').replace(
        'path: built/AGENTS.md', f'path: {elsewhere.parent}/built/AGENTS.md').replace('# My routing', '### My routing')
    profile.write_text(profile.read_text() + '\n## Lesson routing\n\n' + absolute)
    plan = planned(env=env)
    assert plan['conflicts'] == [] and [move['setting'] for move in plan['moves']] == ['auto-apply']
    assert str(elsewhere) in [removal['file'] for removal in plan['removals']]
    changed = absolute.replace('lesson-policy: propose', 'lesson-policy: apply')
    profile.write_text(profile.read_text().replace(absolute, changed))
    assert [row['setting'] for row in planned(env=env)['conflicts']] == ['lesson routing']


def test_the_configuration_loses_only_the_retired_key_and_the_plan_shows_it(legacy):
    config = legacy[2]
    config.write_text('{"prune_days":9,  "auto_apply_lessons" : true,\n "handoff_dir": "~/h"}')
    plan = planned()
    assert '-{"prune_days":9,  "auto_apply_lessons" : true,' in plan['config_diff']
    assert approve(plan).returncode == 0
    assert config.read_text() == '{"prune_days":9,\n "handoff_dir": "~/h"}'


def test_fences_of_another_kind_do_not_end_the_section():
    profile = knowledge_profile(body='Local.\n\n## Lesson routing\n\n````markdown\nAn unclosed inner fence:\n```\n## Not a heading\n````\n\n'
                                     'lesson-policy: propose\n\n## Later\n')
    assert module('lessons').routing_rules()['propose'] is True
    lines = profile.read_text().splitlines()
    compose = module('lessons')._compose_rules()
    assert len(compose.policy_sections(lines, lines.index('---', 1) + 1)) == 1


def test_headings_too_deep_to_move_two_levels_refuse_the_move(legacy):
    routing = legacy[1]
    routing.write_text(CUSTOM + '\n##### Deep\n')
    before = snapshot(*legacy)
    plan = planned()
    assert [row['setting'] for row in plan['conflicts']] == ['lesson routing headings']
    assert approve(plan).returncode == 1 and snapshot(*legacy) == before


def test_setup_moves_policy_only_into_the_profile_the_readers_read(legacy):
    other = Path(os.environ['XDG_DATA_HOME']) / 'other/profile.md'
    other.parent.mkdir(parents=True)
    other.write_bytes(legacy[0].read_bytes())
    before = snapshot(*legacy, other)
    for command in ('plan', 'apply'):
        result = setup(command, '--profile', str(other), '--approval-fingerprint', 'x')
        assert result.returncode != 0 and snapshot(*legacy, other) == before
    assert planned()['profile'] == str(legacy[0])


def test_a_spaced_setting_key_is_read_and_replaced_in_place():
    profile = knowledge_profile(setting='auto_apply : true\n')
    assert module('lessons').enabled({}) is True
    plan = planned('--auto-apply', 'false')
    assert '-auto_apply : true' in plan['profile_diff'] and '+auto_apply: false' in plan['profile_diff']
    assert approve(plan, '--auto-apply', 'false').returncode == 0
    assert profile.read_text().count('auto_apply') == 1 and module('lessons').enabled({}) is False


@pytest.mark.parametrize('deep', [False, True])
def test_keeping_the_profile_routing_needs_a_profile_section(legacy, deep):
    if deep:
        legacy[1].write_text(CUSTOM + '\n##### Deep\n')
    before = snapshot(*legacy)
    result = setup('plan', '--keep-routing', 'profile')
    assert result.returncode == 1 and 'Lesson routing' in result.stderr and 'Traceback' not in result.stderr
    if deep:  # The conflict names only the resolution that exists.
        conflict, = planned()['conflicts']
        assert '--keep-routing profile' not in conflict['resolve']
    assert snapshot(*legacy) == before


@pytest.mark.parametrize('heading', ['## Lesson Routing', '##  Lesson routing', '## Lesson routing (mine)',
                                     '## Lesson routing ##', '### Lesson routing'])
def test_a_near_miss_routing_heading_is_an_error_not_the_default_table(heading):
    knowledge_profile(body=f'Local.\n\n{heading}\n\nlesson-policy: propose\n', setting='auto_apply: true\n')
    lessons = module('lessons')
    assert lessons.enabled({}) is True  # The setting stays readable; only lessons refuse.
    with pytest.raises(ValueError, match='Lesson routing'):
        lessons.routing_rules()


def test_the_moved_title_inside_the_section_is_not_a_near_miss():
    knowledge_profile(body='## Lesson routing\n\n### Lesson routing\n\nlesson-policy: propose\n')
    assert module('lessons').routing_rules()['propose'] is True


def test_an_exported_routing_file_moves_on_approval_and_the_unset_step_stays_reported(legacy):
    profile, routing, config = legacy
    exported = Path(os.environ['XDG_DATA_HOME']) / 'exported.md'
    routing.rename(exported)
    env = {**os.environ, 'HIPPOCAMPUS_ROUTING': str(exported)}
    plan = planned(env=env)
    assert plan['ready'] is False and 'HIPPOCAMPUS_ROUTING' in plan['manual'][0]
    applied = json.loads(approve(plan, env=env).stdout)
    # Moving while exported is the only order that reads this file: unset first and nothing points at it.
    assert '## Lesson routing' in profile.read_text() and not exported.exists()
    assert applied['ready'] is False and applied['manual'] == plan['manual']
