"""Setup's file-writing seam, through the public profile composer."""
import contextlib
import json
import os
import runpy
import shutil
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / 'skills/hippocampus-set-up/scripts/profile.py'
COMPOSER = ROOT / 'scripts/lib/checklist.py'


def write(home, bindings, *extra, present=True):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('CHECKLIST_', 'XDG_', 'CODEX_', 'CLAUDE_'))}
    env['HOME'] = str(home)
    args = [sys.executable, str(WRITER), '--bindings', json.dumps(bindings), *extra]
    if present:
        args.append('--user-present')
    return subprocess.run(args, env=env, capture_output=True, text=True)


def plan(path):
    return subprocess.run([sys.executable, str(COMPOSER), 'plan', '--user-profile', str(path)],
                          capture_output=True, text=True,
                          env={key: value for key, value in os.environ.items()
                               if not key.startswith(('CODEX_', 'CLAUDE_'))})


def test_clean_home_declined_slots_keep_native_steps(tmp_path):
    result = write(tmp_path, dict.fromkeys(('persist',)),
                   '--record-read', '/read-work')
    assert result.returncode == 0, result.stderr
    profile = tmp_path / '.config/hippocampus/checklist-profile.md'
    composed = plan(profile)
    assert composed.returncode == 0, composed.stderr
    value = json.loads(composed.stdout)
    assert value['record_read'] == {'command': '/read-work'}
    assert [s['id'] for s in value['steps']] == ['record', 'knowledge', 'lessons', 'persist', 'handoff']
    assert all(s['binding'] is None for s in value['steps'] if 'slot' in s)
    assert value['steps'][2]['native'] is True


def test_extend_preserves_prose_sections_steps_and_unselected_bindings(tmp_path):
    profile = tmp_path / 'profile.md'
    existing = {'name': 'user', 'record_writes': {'tickets': {'command': 'write-tickets'}},
                'steps': [{'id': 'tidy', 'after': 'persist', 'instructions': 'Tidy up'}]}
    prefix = '# My profile\n\nKeep these notes.\n\n```checklist-profile\n'
    suffix = '\n```\n\n## Record\n\nKeep my record instructions.\n'
    profile.write_text(prefix + json.dumps(existing) + suffix)
    result = write(tmp_path, {'persist': {'command': '/persist-step', 'consumes': []}},
                   '--profile', str(profile), '--record-read', '/read-work')
    assert result.returncode == 0, result.stderr
    text = profile.read_text()
    assert text.startswith(prefix) and text.endswith(suffix)
    updated = json.loads(text.split('```checklist-profile\n')[1].split('\n```')[0])
    assert updated['record_writes'] == existing['record_writes']
    assert updated['steps'] == existing['steps']
    assert plan(profile).returncode == 0


def test_json_profile_and_invalid_changes_do_not_damage_existing_file(tmp_path):
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'name': 'user', 'steps': []}))
    assert write(tmp_path, {'persist': None}, '--profile', str(profile)).returncode == 0
    before = profile.read_bytes()
    result = write(tmp_path, {'record': {'command': '', 'consumes': []}}, '--profile', str(profile))
    assert result.returncode != 0
    assert profile.read_bytes() == before


def test_no_presence_confirmation_writes_nothing(tmp_path):
    result = write(tmp_path, {}, present=False)
    assert result.returncode != 0
    assert 'user present' in result.stderr.lower()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('custom_path', [False, True])
def test_invalid_candidate_in_clean_home_leaves_no_directories(tmp_path, custom_path):
    args = ('--profile', str(tmp_path / 'custom/deep/profile.json')) if custom_path else ()
    result = write(tmp_path, {'record': {'command': '', 'consumes': []}}, *args)
    assert result.returncode != 0
    assert 'record' in result.stderr
    assert not list(tmp_path.iterdir())


# Exercise errors after setup has begun creating directories and staging a file,
# rather than testing validation failures alone.
@pytest.mark.parametrize('existing,failure', [
    (existing, failure)
    for existing in (False, True)
    for failure in ('mkdir', 'temporary', 'write', 'validation', 'replace', 'chmod')
    if (failure != 'mkdir' or not existing) and (failure != 'chmod' or existing)
])
def test_precommit_failures_restore_original_filesystem(tmp_path, monkeypatch, failure, existing):
    profile = tmp_path / '.config/hippocampus/checklist-profile.md'
    if existing:
        profile.parent.mkdir(parents=True)
        profile.write_text('# Keep me\n```checklist-profile\n{"name":"user"}\n```\n')
    before = {p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
              for p in tmp_path.rglob('*')}
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('CHECKLIST_USER_PROFILE', raising=False)
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(WRITER), '--user-present', '--bindings', '{}'])
    namespace = runpy.run_path(str(WRITER))

    def fail(*args, **kwargs):
        raise OSError('injected ' + failure)

    if failure == 'mkdir':
        mkdir = Path.mkdir

        def interrupted_mkdir(path, *args, **kwargs):
            if path == profile.parent:
                raise OSError('injected mkdir')
            return mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, 'mkdir', interrupted_mkdir)
    elif failure == 'temporary':
        monkeypatch.setattr(namespace['tempfile'], 'NamedTemporaryFile', fail)
    elif failure == 'write':
        temporary = namespace['tempfile'].NamedTemporaryFile

        @contextlib.contextmanager
        def unwritable(*args, **kwargs):
            with temporary(*args, **kwargs) as handle:
                yield SimpleNamespace(name=handle.name, write=fail)

        monkeypatch.setattr(namespace['tempfile'], 'NamedTemporaryFile', unwritable)
    elif failure == 'validation':
        monkeypatch.setattr(namespace['checklist'], 'compose', fail)
    elif failure == 'replace':
        monkeypatch.setattr(namespace['os'], 'replace', fail)
    else:
        monkeypatch.setattr(Path, 'chmod', fail)
    with pytest.raises(OSError, match='injected ' + failure):
        namespace['main']()
    after = {p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
             for p in tmp_path.rglob('*')}
    assert after == before


def test_failed_setup_keeps_preexisting_ancestor_and_its_contents(tmp_path):
    ancestor = tmp_path / '.config'
    ancestor.mkdir()
    marker = ancestor / 'unrelated.txt'
    marker.write_text('Existing settings')
    result = write(tmp_path, {'record': {'command': '', 'consumes': []}})
    assert result.returncode != 0
    assert list(tmp_path.iterdir()) == [ancestor]
    assert list(ancestor.iterdir()) == [marker]
    assert marker.read_text() == 'Existing settings'


def test_rejected_setup_in_fresh_package_leaves_no_import_cache(tmp_path):
    package = tmp_path / 'package'
    shutil.copytree(ROOT / 'scripts/lib', package / 'scripts/lib',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    helper = package / 'skills/hippocampus-set-up/scripts/profile.py'
    helper.parent.mkdir(parents=True)
    shutil.copy2(WRITER, helper)
    before = set(tmp_path.rglob('*'))
    env = dict(os.environ)
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    result = subprocess.run([sys.executable, str(helper), '--bindings', '{}'],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'user present' in result.stderr
    assert set(tmp_path.rglob('*')) == before


@pytest.mark.parametrize('suffix', ['.json', '.md'])
def test_legacy_native_bindings_name_blocks_to_delete_and_preserve_profile(tmp_path, suffix):
    profile = tmp_path / ('profile' + suffix)
    data = {'name': 'legacy', 'bindings': {'knowledge': None,
            'lessons': {'command': '/old-lessons', 'consumes': ['lesson']}}}
    text = json.dumps(data, indent=2)
    if suffix == '.md':
        text = '# Keep notes; old example `"knowledge": null`\n```checklist-profile\n' + text + '\n```\n'
    profile.write_text(text)
    for result in [plan(profile), write(tmp_path, {'persist': None}, '--profile', str(profile))]:
        assert result.returncode == 1
        assert 'delete' in result.stderr.lower()
        for slot in ('knowledge', 'lessons'):
            assert 'bindings.' + slot in result.stderr
            line = next(i for i, row in enumerate(text.splitlines(), 1) if row.lstrip().startswith('"' + slot + '"'))
            assert 'line ' + str(line) in result.stderr
        assert profile.read_text() == text


def test_setup_can_configure_and_unbind_ask_separately_from_slots(tmp_path):
    profile = tmp_path / 'profile.json'
    result = write(tmp_path, {'persist': None}, '--profile', str(profile),
                   '--ask', '{"command":"/ask-step"}')
    assert result.returncode == 0, result.stderr
    output = json.loads(plan(profile).stdout)
    assert output['ask'] == {'command': '/ask-step'}
    before = profile.read_bytes()
    for ask in ['{}', '{"command":""}', '{"command":"/ask","consumes":[]}']:
        result = write(tmp_path, {}, '--profile', str(profile), '--ask', ask)
        assert result.returncode == 1
        assert profile.read_bytes() == before
    assert write(tmp_path, {}, '--profile', str(profile), '--ask', 'null').returncode == 0
    assert json.loads(plan(profile).stdout)['ask'] is None


@pytest.mark.parametrize('kind', ['tickets', 'projects', 'documents', 'scheduled_jobs'])
def test_setup_authors_each_record_write_and_preserves_read_and_other_kinds(tmp_path, kind):
    profile = tmp_path / 'profile.json'
    existing = {'name': 'user', 'record_read': {'command': '/read-work'},
                'record_writes': {'tickets': {'command': '/tickets'},
                                  'documents': {'command': '/documents'}}}
    profile.write_text(json.dumps(existing))
    result = write(tmp_path, {}, '--profile', str(profile), '--record-writes',
                   json.dumps({kind: {'command': ['/save', kind]}}))
    assert result.returncode == 0, result.stderr
    expected = {**existing['record_writes'], kind: {'command': ['/save', kind]}}
    updated = json.loads(profile.read_text())
    assert updated['record_writes'] == expected
    assert updated['record_read'] == existing['record_read']
    assert json.loads(plan(profile).stdout)['record_read'] == existing['record_read']
    assert write(tmp_path, {}, '--profile', str(profile), '--record-writes',
                 json.dumps({kind: None})).returncode == 0
    assert json.loads(profile.read_text())['record_writes'][kind] is None


@pytest.mark.parametrize('writes', ['null', '[]', '{"unknown":null}',
                                  '{"tickets":{"command":""}}',
                                  '{"tickets":{"command":"/save","consumes":[]}}'])
def test_invalid_record_writes_preserve_existing_profile(tmp_path, writes):
    profile = tmp_path / 'profile.json'
    profile.write_text('{"name":"user"}')
    before = profile.read_bytes()
    result = write(tmp_path, {}, '--profile', str(profile), '--record-writes', writes)
    assert result.returncode == 1
    assert 'record_writes' in result.stderr
    assert profile.read_bytes() == before


def test_setup_refuses_retired_record_even_when_replacing_it(tmp_path):
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'name': 'user', 'bindings': {'record': None}}))
    before = profile.read_bytes()
    result = write(tmp_path, {'record': None}, '--profile', str(profile))
    assert result.returncode == 1
    assert 'retired bindings.record' in result.stderr and 'record_writes' in result.stderr
    assert profile.read_bytes() == before
