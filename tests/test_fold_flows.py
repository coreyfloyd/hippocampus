"""The nine fold acceptance flows, at installed CLI and instruction seams.

No model conversations are simulated. Setup review/decline policy is checked in
its installed instructions; approved choices and failures run the real writers.
The native-step receipts below are explicit contract inputs, not model output.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(env, *args, data=None, check=True):
    result = subprocess.run(list(map(str, args)), env=env, capture_output=True,
                            text=True, input=json.dumps(data) if data is not None else None,
                            timeout=180)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(params=['claude', 'codex'])
def user(tmp_path, request):
    if request.param == 'codex':
        request.getfixturevalue('requires_codex_cli')
    home = tmp_path / 'home'
    home.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_', 'CODEX_', 'CHECKLIST_', 'HANDOFF_', 'HIPPOCAMPUS_', 'XDG_'))}
    env.update(HOME=str(home), CODEX_HOME=str(home / '.codex'),
               CLAUDE_CODE_ENTRYPOINT='cli', HIPPOCAMPUS_HARNESS=request.param,
               HIPPOCAMPUS_CONFIG=str(home / '.config/hippocampus/config.json'),
               HANDOFF_LEDGER_DIR=str(home / 'ledger'), CHECKLIST_STATE_DIR=str(home / 'checklist'))
    if request.param == 'codex':
        rollout = home / '.codex/sessions/rollout-captured-session.jsonl'
        rollout.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tests/fixtures/codex-hippocampus/interactive.jsonl', rollout)
        env['CODEX_THREAD_ID'] = 'captured-session'
    assert shutil.which(request.param), f'{request.param} CLI required for fold acceptance'
    return request.param, home, env


def install(user, *extra, check=True):
    tool, _, env = user
    return run(env, sys.executable, ROOT / f'scripts/install-{tool}.py', *extra, check=check)


def runtime(user):
    tool, home, env = user
    if tool == 'codex':
        return home / '.local/share/hippocampus/current'
    plugins = json.loads(run(env, 'claude', 'plugin', 'list', '--json').stdout)
    plugin, = [p for p in plugins if p['id'] == 'hippocampus@hippocampus']
    return Path(plugin['installPath'])


def engine(user, root, operation, *args, data=None, check=True):
    return run(user[2], sys.executable, root / 'scripts/lib/checklist.py', operation,
               *args, data=data, check=check)


def checkpoint(user, root, source, name='wrapped.json', expected=0):
    path = user[1] / name
    env = dict(user[2], HANDOFF_PATH=str(path))
    run(env, sys.executable, root / 'scripts/lib/handoff.py', 'checkpoint',
        '--cwd', user[1], '--session-id', 'captured-session', '--trigger', 'wrap', data=source)
    checked = engine(user, root, 'wrap-check', '--written-handoff', path, check=False)
    assert checked.returncode == expected, checked.stderr
    return path


def report(user, root, handoff, statuses, expected=0):
    rows = [{'id': s, 'status': statuses.get(s, 'run'), 'writes': [],
             'reason': 'explicit fixture outcome', 'error': 'fixture failure' if statuses.get(s) == 'failed' else ''}
            for s in ('record', 'knowledge', 'lessons', 'persist', 'handoff')]
    path = user[1] / 'results.json'
    path.write_text(json.dumps(rows))
    result = engine(user, root, 'report', '--handoff', handoff, '--results', path, check=False)
    assert result.returncode == expected, result.stderr
    return json.loads(result.stdout)


def source(home):
    # Frozen schema-v2 handoff from before the fold; never rewrite it via a
    # current producer before testing pickup.
    value = json.loads((ROOT / 'docs/examples/handoff.json').read_text())
    value['subject'] = {'working_directory': str(home), 'session_id': 'captured-session'}
    value['resume']['session_history'][-1]['session_id'] = 'captured-session'
    value['git'] = {'repository_root': '', 'branch': '', 'head': ''}
    value['uncommitted_files'] = []
    value['resume']['open_loops'] = [
        {'type': kind, 'context': f'Carried {kind}', 'session_id': 'captured-session',
         'produced_at': value['written_at'], 'disposition': 'carry to native step'} for kind in ('knowledge', 'lesson')]
    return value


def test_flow_1_new_session_without_knowledge_profile(user):
    install(user)
    root = runtime(user)
    plan = json.loads(engine(user, root, 'plan', '--session-id', 'captured-session').stdout)
    assert [s['id'] for s in plan['steps']] == ['record', 'knowledge', 'lessons', 'persist', 'handoff']
    assert not (user[1] / '.config/hippocampus/profile.md').exists()
    handoff = checkpoint(user, root, source(user[1]))
    assert report(user, root, handoff, {'knowledge': 'not configured', 'lessons': 'nothing'})['report'] == 'ok'
    assert len(json.loads(handoff.read_text())['resume']['open_loops']) == 2


def test_flow_2_upgrade_preserves_profile_composer_and_discovery(user):
    tool, home, env = user
    run(env, 'bash', ROOT / 'install.sh')
    profile = home / '.config/hippocampus/profile.md'
    profile.write_text('User knowledge policy stays byte-identical.\n')
    foreign = home / f'.{tool}/skills/personal'
    foreign.symlink_to(home / 'personal-skill')
    install(user)
    root = runtime(user)
    assert profile.read_text() == 'User knowledge policy stays byte-identical.\n'
    assert (home / '.local/share/hippocampus/current/scripts/compose_rules.py').is_file()
    assert (root / 'scripts/compose_rules.py').is_file()
    assert foreign.is_symlink()
    for skill in (ROOT / 'skills').iterdir():
        if not (skill / 'SKILL.md').is_file():
            continue
        link = home / f'.{tool}/skills' / skill.name
        assert (root / 'skills' / skill.name / 'SKILL.md').is_file()
        assert link.is_symlink() if tool == 'codex' else not link.is_symlink()
    hooks = json.loads((home / '.codex/hooks.json' if tool == 'codex' else root / 'hooks/hooks.json').read_text())['hooks']
    commands = [h['command'] for groups in hooks.values() for g in groups for h in g['hooks']]
    assert len(commands) == len(set(commands))


def test_flow_3_refusal_then_install_after_manual_uninstall(user):
    tool, home, _ = user
    # This is detection-only fixture state. No migration or old runtime code.
    old = 'continu' + 'ity'
    marker = home / ('.claude/plugins/installed_plugins.json' if tool == 'claude' else f'.codex/{old}-install.json')
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'version': 2, 'plugins': {old + '@example': []}}) if tool == 'claude' else '{}')
    before = marker.read_bytes()
    result = install(user, check=False)
    assert result.returncode != 0 and 'uninstall' in result.stderr
    assert marker.read_bytes() == before
    assert not (home / '.local/share/hippocampus/current').exists()
    marker.unlink()  # user's manual uninstall completed
    install(user)
    assert (runtime(user) / 'skills/pickup/SKILL.md').is_file()


def test_flow_4_foreign_codex_trust_survives_update_and_uninstall(user):
    tool, home, env = user
    if tool != 'codex':
        pytest.skip('Codex hook trust is tool-specific')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from lib import codex_trust as trust
    codex = home / '.codex'
    codex.mkdir(exist_ok=True)
    handler = {'type': 'command', 'command': 'echo foreign', 'timeout': 1}
    group = {'hooks': [handler]}
    hooks = {'hooks': {'Stop': [group]}}
    target = codex / 'hooks.json'
    target.write_text(json.dumps(hooks))
    key = f'{target.resolve()}:stop:0:0'
    config = 'model = "custom"\n' + f'[hooks.state.{json.dumps(key)}]\ntrusted_hash = {json.dumps(trust.hook_hash("Stop", group, handler))}\n'
    (codex / 'config.toml').write_text(config)
    for _ in range(2):
        install(user)
        assert json.loads(target.read_text())['hooks']['Stop'][0] == group
        assert (codex / 'config.toml').read_text().startswith(config)
    install(user, '--uninstall')
    assert json.loads(target.read_text()) == hooks
    assert (codex / 'config.toml').read_text().strip() == config.strip()


@pytest.mark.parametrize('status', ['nothing', 'not configured', 'failed', 'declined', 'pending', 'filed'])
def test_flow_5_resumed_handoff_reaches_native_steps_and_valid_wrap(user, status):
    install(user)
    root = runtime(user)
    before = source(user[1])
    path = user[1] / 'pre-fold.json'
    path.write_text(json.dumps(before))
    resumed = json.loads(run(user[2], 'bash', root / 'scripts/pickup.sh', '--handoff', path).stdout)
    assert resumed['source'] == 'handoff'
    # Pickup's exact handoff is the next plan's input.
    assert resumed['handoff']['resume']['open_loops'] == before['resume']['open_loops']
    planned = json.loads(engine(user, root, 'plan', '--handoff', path, '--session-id', 'captured-session').stdout)
    for step, kind in zip(planned['steps'][1:3], ('knowledge', 'lesson')):
        assert step['carried_items'][0]['item']['type'] == kind
        assert step['native']
    rows = [{'index': i, 'rule': 'R4', 'status': status if i == 0 or status != 'not configured' else 'nothing',
             'reason': 'explicit native outcome', 'error': 'fixture failure',
             'destination': 'capture disposition or applied lesson receipt'} for i in range(2)]
    filing = user[1] / 'filing.json'
    filing.write_text(json.dumps(rows))
    filed = json.loads(engine(user, root, 'file', '--handoff', path, '--filing', filing).stdout)
    assert filed['resume']['open_loops'] == ([] if status == 'filed' else before['resume']['open_loops'])
    unsaved = status in ('failed', 'pending')
    written = checkpoint(user, root, filed, expected=int(unsaved))
    statuses = {'knowledge': 'run' if status == 'filed' else status,
                'lessons': 'run' if status == 'filed' else 'nothing' if status == 'not configured' else status}
    result = report(user, root, written, statuses, expected=int(unsaved))
    assert result['report'] == ('failed' if unsaved else 'incomplete' if status == 'declined' else 'ok')


def test_flow_6_failed_update_restores_previous_install(user):
    install(user)
    tool, home, env = user
    root = runtime(user)
    marker = root / 'previous-runtime-marker'
    # Claude local marketplace may read the checkout directly; only snapshot
    # registry/settings there, never modify that source installation.
    if tool == 'codex':
        marker.write_text('previous runtime')
    config = home / f'.{tool}'
    watched = ['hooks.json', 'config.toml', 'hippocampus-install.json'] if tool == 'codex' else ['settings.json', 'plugins/installed_plugins.json']
    before = {p: (config / p).read_bytes() for p in watched}
    broken = home / 'failing-cli'
    broken.write_text('#!/bin/sh\nexit 1\n')
    broken.chmod(0o755)
    result = install(user, '--' + tool, str(broken), check=False)
    assert result.returncode != 0
    assert {p: (config / p).read_bytes() for p in watched} == before
    assert (runtime(user) / 'skills/pickup/SKILL.md').is_file()
    if tool == 'codex':
        assert marker.read_text() == 'previous runtime'


def setup(user, root, bindings, *extra, check=True):
    return run(user[2], sys.executable, root / 'skills/hippocampus-set-up/scripts/profile.py',
               '--bindings', json.dumps(bindings), *extra, check=check)


def test_flow_7_session_only_setup_probes_record_and_validates_profile(user):
    install(user)
    root = runtime(user)
    response = {'kind': 'ticket_status', 'rows': [{'reference': 'example/work#1',
                'title': 'Fixture work', 'state': 'open', 'link': 'https://example.invalid/work/1',
                'latest_progress': 'Fixture record read'}]}
    # This fixture response tests the deterministic seam; access to a user's
    # real record is verified conversationally by setup, not fabricated here.
    probe = run(user[2], sys.executable, root / 'scripts/lib/record_read.py',
                '--expect', 'ticket_status', data=response)
    assert probe.stdout.strip() == 'valid'
    setup(user, root, {'persist': None}, '--user-present',
          '--ask', '{"command":"/ask-user"}', '--record-read', '/read-work')
    profile = user[1] / '.config/hippocampus/checklist-profile.md'
    plan = json.loads(engine(user, root, 'plan', '--user-profile', profile, '--session-id', 'captured-session').stdout)
    assert plan['record_read'] == {'command': '/read-work'}
    assert plan['ask'] == {'command': '/ask-user'}
    assert not (profile.parent / 'profile.md').exists()


def test_flow_8_extend_existing_knowledge_profile_preserves_other_choices(user):
    install(user)
    root = runtime(user)
    folder = user[1] / '.config/hippocampus'
    folder.mkdir(parents=True, exist_ok=True)
    knowledge = folder / 'profile.md'
    knowledge_root = user[1] / 'knowledge'
    for name in ('raw', 'output', 'docs'):
        (knowledge_root / name).mkdir(parents=True)
    for name in ('log.md', 'DECISIONS.md'):
        (knowledge_root / 'docs' / name).touch()
    knowledge.write_text('---\nprofile_version: 4\nknowledge_root: ' + str(knowledge_root) +
                         '\nwiki_enabled: false\noperation_log_file: docs/log.md\n'
                         'decision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Tasks\n'
                         '---\nKeep knowledge policy.\n')
    run(user[2], sys.executable, root / 'scripts/validate_profile.py', knowledge)
    profile = folder / 'checklist-profile.md'
    original = {'name': 'user', 'record_writes': {'tickets': {'command': 'keep-record'}},
                'steps': [{'id': 'tidy', 'after': 'persist', 'instructions': 'Keep addition'}]}
    profile.write_text('# Keep prose\n```checklist-profile\n' + json.dumps(original) + '\n```\n')
    before = knowledge.read_bytes()
    setup(user, root, {'persist': {'command': '/save-work', 'consumes': []}}, '--user-present')
    plan = json.loads(engine(user, root, 'plan', '--user-profile', profile, '--session-id', 'captured-session').stdout)
    assert knowledge.read_bytes() == before
    assert profile.read_text().startswith('# Keep prose\n')
    assert plan['steps'][0]['record_writes'] == original['record_writes']
    assert plan['steps'][-2]['id'] == 'tidy'
    assert plan['steps'][3]['binding']['command'] == '/save-work'
    checklist_before = profile.read_bytes()
    homes = json.dumps({tool: str(user[1] / ('settings-' + tool))
                        for tool in ('claude-code', 'codex', 'openclaw')})
    args = ['--profile', knowledge, '--homes', homes, '--preset', 'standard']
    proposal = json.loads(run(user[2], sys.executable, root / 'scripts/rules_setup.py', 'plan', *args).stdout)
    assert knowledge.read_bytes() == before  # preparing the exact review writes nothing
    declined = run(user[2], sys.executable, root / 'scripts/rules_setup.py', 'apply', *args,
                   '--approval-fingerprint', proposal['approval_fingerprint'], check=False)
    assert declined.returncode != 0 and knowledge.read_bytes() == before
    run(user[2], sys.executable, root / 'scripts/rules_setup.py', 'apply', *args,
        '--approve', '--approval-fingerprint', proposal['approval_fingerprint'])
    assert knowledge.read_text().endswith('---\nKeep knowledge policy.\n')
    assert 'preset: standard' in knowledge.read_text()
    assert profile.read_bytes() == checklist_before
    run(user[2], sys.executable, root / 'scripts/validate_profile.py', knowledge)


def test_flow_9_declined_or_invalid_setup_writes_nothing_unapproved(user):
    install(user)
    root = runtime(user)
    profile = user[1] / '.config/hippocampus/checklist-profile.md'
    result = setup(user, root, {}, check=False)
    assert result.returncode != 0 and 'without writes' in result.stderr
    assert not profile.exists()
    setup(user, root, {'persist': None}, '--user-present')
    before = profile.read_bytes()
    result = setup(user, root, {'record': {'command': '', 'consumes': []}}, '--user-present', check=False)
    assert result.returncode != 0
    assert profile.read_bytes() == before
    paths = set(profile.parent.iterdir())
    writer = root / 'skills/hippocampus-set-up/scripts/profile.py'
    code = ('import os,runpy,sys; from unittest.mock import patch; '
            'sys.argv=sys.argv[1:]; '
            'patcher=patch.object(os, "replace", side_effect=OSError("injected write failure")); '
            'patcher.start(); runpy.run_path(sys.argv[0], run_name="__main__")')
    failed = run(user[2], sys.executable, '-c', code, writer, '--bindings',
                 '{"persist":null}', '--user-present', check=False)
    assert failed.returncode != 0 and 'injected write failure' in failed.stderr
    assert profile.read_bytes() == before and set(profile.parent.iterdir()) == paths
    assert not (profile.parent / 'profile.md').exists()


def test_session_installation_guides_resolve_local_links_and_layout():
    for name in ('session-guide.md', 'session-installation.md'):
        path = ROOT / 'docs' / name
        text = path.read_text()
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in target or target.startswith('#'):
                continue
            assert (path.parent / target.split('#')[0]).exists(), (name, target)
        assert '~/.codex/hippocampus/' not in text
        assert 'seven skills' not in text
    guide = (ROOT / 'docs/session-guide.md').read_text()
    assert '(architecture/session/runtime.html)' in guide
    assert '(session-presentation.html)' in guide
    deck = (ROOT / 'docs/session-presentation.html').read_text()
    assert 'python3 scripts/install-claude.py' in deck
    assert 'Seven skills' not in deck
    assert 'href="architecture/session/runtime.html"' in deck
