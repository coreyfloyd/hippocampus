"""Install and replay the captured Codex hook contracts in an isolated home."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures/codex-continuity'
INSTALL = ROOT / 'scripts/install-codex.py'
ADAPTER = ROOT / 'scripts/codex-hook.py'


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for key in ('CODEX_THREAD_ID', 'CLAUDE_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_ENTRYPOINT', 'CONTINUITY_HARNESS'):
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / 'home'; home.mkdir()
    work = tmp_path / 'work'; work.mkdir()
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    subprocess.run(['git', '-C', str(work), '-c', 'user.name=Example', '-c', 'user.email=example@example.org',
                    'commit', '--allow-empty', '-qm', 'Initial'], check=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('CODEX_HOME', str(home / '.codex'))
    monkeypatch.setenv('HANDOFF_STATE_DIR', str(home / 'state/handoffs'))
    monkeypatch.setenv('HANDOFF_LEDGER_DIR', str(home / 'state/ledger'))
    monkeypatch.setenv('HANDOFF_COMPACT_STATE_DIR', str(home / 'state/compact'))
    monkeypatch.setenv('CHECKLIST_STATE_DIR', str(home / 'state/checklist'))
    monkeypatch.setenv('CONTINUITY_CONFIG', str(home / 'config.json'))
    return home, work


def cli(path, *args, data=None, cwd=None, env=None):
    return subprocess.run([sys.executable, str(path), *map(str,args)], input=json.dumps(data) if data is not None else '',
                          text=True, capture_output=True, cwd=cwd, env=env)


def payload(moment, sandbox, source='interactive', **changes):
    home, work = sandbox
    value = json.loads((FIX / (moment + '.json')).read_text())
    transcript = home / '.codex/sessions/rollout-captured-session.jsonl'
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text((FIX / (source + '.jsonl')).read_text())
    value.update(cwd=str(work), transcript_path=str(transcript), **changes)
    return value


def checkpoint(work, sid='captured-session'):
    result = cli(ROOT/'scripts/lib/handoff.py', 'checkpoint', '--cwd', work, '--session-id', sid,
                 data={'resume': {'headline': 'Continue here', 'next_action': 'Read the record', 'open_loops': []},
                       'spawned_processes': []})
    assert result.returncode == 0, result.stderr
    return next(Path(os.environ['HANDOFF_STATE_DIR']).glob('*.json'))


def test_derived_fixtures_keep_the_probe_hashes():
    manifest = json.loads((FIX/'manifest.json').read_text())
    assert len(manifest['source_payload_sha256']) == 5
    for name, digest in manifest['derived_payload_sha256'].items():
        assert hashlib.sha256((FIX/name).read_bytes()).hexdigest() == digest


# Byte hashes of the five raw payloads the live CLI 0.160.0 probe recorded on
# 2026-10-02. The raw payloads carry a real session id and host paths, so they
# stay private; only their hashes are published here.
PROBE_PAYLOAD_SHA256 = {
    'PostToolUse.json': 'f405ef6ef1299cc23644c8071bfb4233782774059ede34d1533ecb416d4fa882',
    'PreCompact.json': 'e868263077338748c617f39a84b7d5bb8721b64b81f01bde84100220c2c13504',
    'SessionStart.json': '42ab6875c94bc3dd19d807669ab22a8353b4eefc081b28ae343facbd3ef60012',
    'Stop.json': '421ef1620e610615f64b5d2ba5b3e7127be6db1cc7d143661f7f92faa2332b07',
    'UserPromptSubmit.json': 'c66ace59ff47d240694c0936aac7f411f1917e21c2ccd7dadda12cd853f413bf',
}


def test_each_derived_payload_traces_to_its_recorded_probe_payload():
    manifest = json.loads((FIX/'manifest.json').read_text())
    assert manifest['source_payload_sha256'] == PROBE_PAYLOAD_SHA256
    assert sorted(manifest['derived_payload_sha256']) == sorted(PROBE_PAYLOAD_SHA256)
    assert all((FIX/name).is_file() for name in PROBE_PAYLOAD_SHA256)


def test_one_install_registers_six_hooks_and_guard_preserves_other_entries_and_uninstalls(sandbox):
    home, work = sandbox
    codex = home/'.codex';codex.mkdir()
    (codex/'config.toml').write_text('model = "custom"\n')
    foreign={'hooks': {'Stop': [{'hooks':[{'type':'command','command':'echo foreign','timeout':1}]}]}}
    (codex/'hooks.json').write_text(json.dumps(foreign))
    handoff = checkpoint(work)
    result=cli(INSTALL, '--codex-home', codex)
    assert result.returncode == 0, result.stderr
    hooks=json.loads((codex/'hooks.json').read_text())['hooks']
    assert sum(len(g['hooks']) for groups in hooks.values() for g in groups)==8
    assert {p.name for p in (codex/'skills').iterdir() if p.name != '.system'} == {
        'checklist','pickup','checkpoint','wip','handoff-prompt','improve-harness','slim-harness','setup','sweep'}
    before=(codex/'hooks.json').read_text()
    assert cli(INSTALL,'--codex-home',codex).returncode==0
    assert (codex/'hooks.json').read_text()==before
    # The installed commands point at a durable package copy, including paths with spaces.
    for groups in hooks.values():
        for group in groups:
            for hook in group['hooks']:
                if 'codex-hook.py' in hook['command']:
                    moment='Stop' if ' guard-decide' in hook['command'] else 'SessionStart'
                    p=payload(moment,sandbox)
                    run=subprocess.run(hook['command'],shell=True,input=json.dumps(p),text=True,capture_output=True)
                    assert run.returncode==0,run.stderr
    assert cli(INSTALL,'--codex-home',codex,'--uninstall').returncode==0
    assert json.loads((codex/'hooks.json').read_text()) == foreign
    # Trust removal retains blank separators while removing all owned settings.
    assert [line for line in (codex/'config.toml').read_text().splitlines() if line.strip()] == ['model = "custom"']
    assert handoff.exists()
    assert not [p for p in (codex/'skills').iterdir() if p.name != '.system']


@pytest.fixture
def trust_then_foreign_block():
    # Derived from a trust table immediately preceding another tool's markers.
    key = '/example/config/hooks.json:user_prompt_submit:3:0'
    block = ('# >>> example-tool codex agents >>>\n'
             '[agents.example]\n'
             'description = "Example agent"\n'
             'config_file = "/example/config/agents/example.toml"\n'
             '# <<< example-tool codex agents <<<\n')
    table = f'[hooks.state.{json.dumps(key)}]\ntrusted_hash = "sha256:example"\n'
    return key, table, block


@pytest.fixture
def codex_installer():
    import importlib.util
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        spec = importlib.util.spec_from_file_location('install_codex_test', INSTALL)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
    finally:
        sys.path.pop(0)
    return installer


def test_remove_trust_preserves_adjacent_comments_and_blank_lines(codex_installer, trust_then_foreign_block):
    installer = codex_installer
    key, table, block = trust_then_foreign_block
    text = 'model = "custom"\n\n' + table + block + '\n\n'
    assert installer.remove_trust(text, {key}) == 'model = "custom"\n\n' + block + '\n\n'
    # Comments and spacing within the owned table also survive removal.
    annotated = table.replace('trusted_hash', '# retained note\n\ntrusted_hash')
    assert installer.remove_trust(annotated, {key}) == '# retained note\n\n'
    assert installer.remove_trust(text, set()) == text


@pytest.mark.parametrize('assignment', [
    'trusted_hash = "sha256:example" # retained inline note\n',
    "trusted_hash = 'sha256:#value' # retained inline note\n",
    'trusted_hash = "sha256:#value" # retained inline note\n',
])
def test_remove_trust_preserves_inline_assignment_comments(
        codex_installer, trust_then_foreign_block, assignment):
    key, table, block = trust_then_foreign_block
    text = table.splitlines(keepends=True)[0] + assignment + block
    assert codex_installer.remove_trust(text, {key}) == '# retained inline note\n' + block


@pytest.mark.parametrize('assignment,preserved', [
    ('extra = [\n  "value",\n]\n', ''),
    ('extra = [ # array start\n  "#value", # element\n] # array end\n',
     '# array start\n  # element\n# array end\n'),
    ('extra = """\n# string content\n""" # string end\n', '# string end\n'),
    ('extra = [\n  # retained array comment\n\n  ["value"],\n]\n', '  # retained array comment\n\n'),
    ('extra = [\n  [\n    "value",\n  ],\n]\n', ''),
    ('extra = """\n# string content\n[agents.decoy]\n"""\n', ''),
    ("extra = '''\n# string content\n[agents.decoy]\n'''\n", ''),
    ('extra = """\nvalue with \\"quote\\" and # text\n"""\n', ''),
    ('extra = """value"""""\n', ''),
])
def test_remove_trust_removes_complete_multiline_assignments(
        codex_installer, trust_then_foreign_block, assignment, preserved):
    key, table, block = trust_then_foreign_block
    text = table + assignment + '# retained separator\n\n' + block
    cleaned = codex_installer.remove_trust(text, {key})
    assert cleaned == preserved + '# retained separator\n\n' + block
    if sys.version_info >= (3, 11):
        import tomllib
        tomllib.loads(text)
        assert tomllib.loads(cleaned) == tomllib.loads(block)


def test_two_reinstalls_preserve_adjacent_foreign_agent_block(
        sandbox, trust_then_foreign_block, codex_installer, monkeypatch):
    home, _ = sandbox
    codex = home / '.codex'
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex), '--codex', 'codex'])
    # The external app-server trust check is independent of config preservation.
    monkeypatch.setattr(codex_installer.trust, 'verify_with_hooks_list', lambda *args: None)
    assert codex_installer.main() == 0
    _, _, block = trust_then_foreign_block
    config = codex / 'config.toml'
    # The installed config ends with an owned trust table, as in the reproduction.
    config.write_text(config.read_text() + block)
    for _ in range(2):
        assert codex_installer.main() == 0
        text = config.read_text()
        assert text.count(block) == 1


@pytest.mark.parametrize('with_foreign_block', [False, True])
def test_reinstalls_leave_whole_config_stable(
        sandbox, trust_then_foreign_block, codex_installer, monkeypatch, with_foreign_block):
    home, _ = sandbox
    codex = home / '.codex'
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex), '--codex', 'codex'])
    monkeypatch.setattr(codex_installer.trust, 'verify_with_hooks_list', lambda *args: None)
    assert codex_installer.main() == 0
    config = codex / 'config.toml'
    _, _, block = trust_then_foreign_block
    original = config.read_text().replace('trusted_hash =', '# retained note\n\n\ntrusted_hash =', 1)
    if with_foreign_block:
        original += block
    lines = original.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith('trusted_hash ='))
    lines[index] = lines[index].rstrip('\n') + ' # retained inline note\n'
    original = ''.join(lines)
    config.write_text(original)
    snapshots = []
    for _ in range(4):
        assert codex_installer.main() == 0
        snapshots.append(config.read_text())
        assert snapshots[-1].count('# retained inline note\n') == 1
    assert snapshots == [snapshots[0]] * 4
    keys = set(json.loads((codex / 'continuity-install.json').read_text())['trust_keys'])
    assert codex_installer.remove_trust(snapshots[0], keys) == codex_installer.remove_trust(original, keys)
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex), '--uninstall'])
    assert codex_installer.main() == 0
    assert config.read_text() == codex_installer.remove_trust(original, keys)


@pytest.mark.parametrize('hash_key', [
    'trusted_hash', '"trusted_hash"', "'trusted_hash'",
    r'"trusted\u005fhash"', r'"trusted\U0000005fhash"',
])
def test_reinstalls_preserve_all_user_trust_settings(sandbox, codex_installer, monkeypatch, hash_key):
    home, _ = sandbox
    codex = home / '.codex'
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex),
                                    '--codex', shutil.which('codex')])
    # Exercise native hooks/list trust verification, including disabled hooks.
    assert codex_installer.main() == 0
    config = codex / 'config.toml'
    original = config.read_text()
    expected = codex_installer.trust.managed_state(
        codex_installer.registrations(codex / 'continuity'),
        codex_installer.read_hooks(codex / 'hooks.json'), codex / 'hooks.json')
    captured = json.loads((FIX / 'PostToolUse.json').read_text())
    # enabled=false is the ticket's captured reproduction; other value shapes
    # reuse data from the recorded hook payload rather than fabricated records.
    settings = ('enabled = false\n'
                'tool_name = ' + json.dumps(captured['tool_name']) + '\n'
                'tool_input = { command = ' + json.dumps(captured['tool_input']['command']) + ' }\n'
                'tool_response = """\n' + captured['tool_response'] + '"""\n'
                'events = [\n  ' + json.dumps(captured['hook_event_name']) + ',\n]\n')
    modified = []
    for line in original.splitlines(keepends=True):
        if line.startswith('trusted_hash ='):
            # A stale persisted hash must still be refreshed by the installer.
            modified.append(hash_key + ' = "" # retained hash comment\n' + settings)
        else:
            modified.append(line)
    config.write_text(''.join(modified))
    snapshots = []
    for _ in range(3):
        assert codex_installer.main() == 0
        text = config.read_text()
        for key, digest in expected.items():
            assert f'[hooks.state.{json.dumps(key)}]\ntrusted_hash = {json.dumps(digest)}\n' in text
        assert text.count(settings) == len(expected)
        assert text.count('# retained hash comment') == len(expected)
        snapshots.append(text)
    assert snapshots == [snapshots[0]] * 3


@pytest.mark.parametrize('quote', ['"' * 3, "'" * 3])
@pytest.mark.parametrize('content_kind', ['table', 'assignment'])
def test_reinstalls_preserve_config_syntax_inside_user_strings(
        sandbox, codex_installer, monkeypatch, quote, content_kind):
    home, _ = sandbox
    codex = home / '.codex'
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex),
                                    '--codex', shutil.which('codex')])
    assert codex_installer.main() == 0
    config = codex / 'config.toml'
    original = config.read_text()
    lines = original.splitlines(keepends=True)
    # Capture the installed table and assignment, reproducing the evaluator's
    # multiline value with actual generated configuration rather than fake keys.
    header_index = next(i for i, line in enumerate(lines) if line.startswith('[hooks.state.'))
    content = lines[header_index if content_kind == 'table' else header_index + 1]
    settings = 'enabled = false\nnotes = ' + quote + '\n' + content + quote + '\n'
    lines.insert(header_index + 2, settings)
    configured = ''.join(lines)
    config.write_text(configured)
    for _ in range(3):
        assert codex_installer.main() == 0
        assert config.read_text() == configured


@pytest.mark.parametrize('first_install', [True, False])
@pytest.mark.parametrize('final_newline', [True, False])
@pytest.mark.parametrize('before_agent_block', [True, False])
def test_install_inserts_trust_with_config_crlf(
        sandbox, codex_installer, monkeypatch, trust_then_foreign_block,
        first_install, final_newline, before_agent_block):
    home, _ = sandbox
    codex = home / '.codex'
    codex.mkdir()
    config = codex / 'config.toml'
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex),
                                    '--codex', shutil.which('codex')])
    original = ''
    if not first_install:
        assert codex_installer.main() == 0
        original = config.read_text()
        keys = json.loads((codex / 'continuity-install.json').read_text())['trust_keys']
        original = codex_installer.remove_trust(original, {keys[0]})
    _, _, block = trust_then_foreign_block
    if before_agent_block:
        block = codex_installer.trust.AGENT_BLOCK_START + '\n' + block
    original += block
    configured = original.replace('\n', '\r\n').encode('utf-8')
    if not final_newline:
        configured = configured.removesuffix(b'\r\n')
    config.write_bytes(configured)
    assert codex_installer.main() == 0
    installed = config.read_bytes()
    assert b'\n' not in installed.replace(b'\r\n', b'')
    assert block.rstrip('\n').replace('\n', '\r\n').encode('utf-8') in installed
    # The newly generated CRLF table must stay stable through another reinstall.
    assert codex_installer.main() == 0
    assert config.read_bytes() == installed


@pytest.mark.parametrize('separator', ['\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'])
@pytest.mark.parametrize('ending', ['\n', '\r\n', ''])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_config_writer_preserves_unowned_bytes(
        codex_installer, trust_then_foreign_block, separator, ending, newline):
    key, table, block = trust_then_foreign_block
    # Mutate the existing redacted table/block with the reported boundary cases.
    block = block.replace('Example agent', 'Example' + separator + 'agent')
    original = (table + block).replace('\n', newline) + '  \t' + ending
    updated = codex_installer.trust.update_config_text(original, {key: 'sha256:example'})
    assert updated.encode('utf-8') == original.encode('utf-8')


@pytest.mark.parametrize('separator', ['\x85', '\u2028', '\u2029'])
@pytest.mark.parametrize('quote', ['"', '"""', "'''"])
@pytest.mark.parametrize('location', ['owned', 'foreign'])
def test_reinstalls_preserve_unicode_config_values(
        sandbox, codex_installer, monkeypatch, trust_then_foreign_block,
        separator, quote, location):
    home, _ = sandbox
    codex = home / '.codex'
    monkeypatch.setattr(sys, 'argv', [str(INSTALL), '--codex-home', str(codex),
                                    '--codex', shutil.which('codex')])
    assert codex_installer.main() == 0
    config = codex / 'config.toml'
    original = config.read_text()
    captured = json.loads((FIX / 'PostToolUse.json').read_text())
    # The recorded response supplies the value; replace its physical newline
    # with the separator from the reported corruption, without inventing records.
    value = captured['tool_response'].replace('\n', separator)
    padding = '\n' if len(quote) == 3 else ''
    settings = 'tool_response = ' + quote + padding + value + padding + quote + '\n'
    if location == 'owned':
        index = original.index('\n', original.index('trusted_hash =')) + 1
        original = original[:index] + settings + original[index:]
    else:
        _, _, block = trust_then_foreign_block
        original += block.replace('# <<<', settings + '# <<<', 1)
    # Reinstall must also retain physical CRLF, trailing whitespace and EOF.
    configured = original.replace('\n', '\r\n').encode('utf-8') + b'  \t'
    config.write_bytes(configured)
    for _ in range(2):
        assert codex_installer.main() == 0
        assert config.read_bytes() == configured


def test_install_collision_and_verification_failure_do_not_change_user_files(sandbox):
    home,_=sandbox;codex=home/'.codex';(codex/'skills/checklist').mkdir(parents=True)
    result=cli(INSTALL,'--codex-home',codex)
    assert result.returncode != 0
    assert 'existing skill' in result.stderr
    assert not (codex/'hooks.json').exists()
    (codex/'skills/checklist').rmdir()
    fake=home/'codex-fail';fake.write_text('#!/bin/sh\nexit 1\n');fake.chmod(0o755)
    result=cli(INSTALL,'--codex-home',codex,'--codex',fake)
    assert result.returncode != 0
    assert not (codex/'hooks.json').exists()
    assert not (codex/'config.toml').exists()
    assert not [p for p in (codex/'skills').iterdir() if p.name != '.system']


def test_restore_precompact_and_context_half_window(sandbox):
    _,work=sandbox;checkpoint(work)
    start=payload('SessionStart',sandbox)
    assert 'handoff exists' in cli(ADAPTER,'post-compact',data=start).stdout
    start['source']='compact'
    assert 'Continue here' in cli(ADAPTER,'post-compact',data=start).stdout
    p=payload('PreCompact',sandbox)
    assert 'COMPACTION IMMINENT' in cli(ADAPTER,'pre-compact',data=p).stdout
    assert len(list(Path(os.environ['HANDOFF_COMPACT_STATE_DIR']).glob('*.json')))==1
    p=payload('UserPromptSubmit',sandbox);transcript=Path(p['transcript_path'])
    row=json.loads((FIX/'usage.jsonl').read_text());info=row['payload']['info']
    info['last_token_usage']['input_tokens']=info['model_context_window']//2
    transcript.write_text(transcript.read_text()+json.dumps(row)+'\n')
    assert '50%' in cli(ADAPTER,'context-guard',data=p).stdout
    info['last_token_usage']['input_tokens']-=1
    transcript.write_text((FIX/'interactive.jsonl').read_text()+json.dumps(row)+'\n')
    assert cli(ADAPTER,'context-guard',data=p).stdout==''


@pytest.mark.parametrize('source', ['headless','subagent'])
def test_headless_cli_and_guard_refuse_wrap(sandbox,source):
    home,_=sandbox;p=payload('PostToolUse',sandbox,source, tool_input={'command':'python3 scripts/lib/checklist.py plan'})
    env=dict(os.environ,CODEX_THREAD_ID='captured-session')
    for operation in ('plan','settle','report','wrap-check'):
        result=cli(ROOT/'scripts/lib/checklist.py',operation,env=env)
        assert result.returncode!=0 and 'never runs' in result.stderr
    result=cli(ADAPTER,'actor-guard',data=p,env=env)
    assert json.loads(result.stdout)['hookSpecificOutput']['permissionDecision']=='deny'
    assert cli(ADAPTER,'checklist-nudge',data=p,env=env).stdout==''


def test_interactive_codex_ignores_headless_claude_parent(sandbox):
    p=payload('PostToolUse',sandbox,tool_input={'command':'python3 scripts/lib/checklist.py plan'})
    env=dict(os.environ,CODEX_THREAD_ID='captured-session',CLAUDE_CODE_ENTRYPOINT='sdk-cli')
    assert cli(ROOT/'scripts/lib/checklist.py','plan',env=env).returncode==0
    assert cli(ADAPTER,'actor-guard',data=p,env=env).stdout==''


@pytest.mark.parametrize('command,output', [('git commit -m work','committed'),('git push','pushed'),
                                          ('pytest -q','8 passed'),('pytest -q','1 failed, 8 passed')])
def test_nudge_once_and_no_failed_tests(sandbox,command,output):
    p=payload('PostToolUse',sandbox,tool_input={'command':command},tool_response=output)
    first=cli(ADAPTER,'checklist-nudge',data=p)
    assert first.returncode==0
    if 'failed' in output:
        assert first.stdout==''
    else:
        assert '$checklist' in first.stdout
        assert cli(ADAPTER,'checklist-nudge',data=p).stdout==''


def test_ledger_commit_makes_handoff_stale(sandbox):
    _,work=sandbox;checkpoint(work)
    p=payload('PostToolUse',sandbox)
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    commit=subprocess.run(['git','-C',str(work),'-c','user.name=Example','-c','user.email=example@example.org',
                    'commit','--allow-empty','-m','Work'],check=True,text=True,capture_output=True)
    p['tool_input']['command']='git commit --allow-empty -m Work';p['tool_response']=commit.stdout
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    stop=payload('Stop',sandbox)
    result=cli(ADAPTER,'guard-decide',data=stop)
    assert json.loads(result.stdout)['decision']=='block'
    stop['stop_hook_active']=True
    assert cli(ADAPTER,'guard-decide',data=stop).stdout==''


def test_unattended_completion_marks_wrap_until_success(sandbox):
    home,work=sandbox;handoff=checkpoint(work)
    module=ROOT/'tests/support/unattended_state.py'
    modefile=home/'mode.json'
    modefile.write_text(json.dumps({'session_id':'captured-session','mode':'afk','updated_by':'operator','updated_at':'2026-01-01T00:00:00Z'}))
    # The support module uses UNATTENDED_STATE_DIR, one record per session.
    modes=home/'modes';modes.mkdir();(modes/'captured-session').write_text(modefile.read_text())
    os.environ['UNATTENDED_STATE_DIR']=str(modes)
    config={'unattended':{'state_module':str(module),'completion_command':'finish-work','completed_by':['complete']}}
    Path(os.environ['CONTINUITY_CONFIG']).write_text(json.dumps(config))
    p=payload('PostToolUse',sandbox,tool_input={'command':'git commit -m work'},tool_response='committed')
    reminder = cli(ADAPTER,'checklist-nudge',data=p).stdout
    assert 'checkpoint' in reminder.lower()
    assert '$checklist' in reminder
    (modes/'captured-session').write_text(json.dumps({'session_id':'captured-session','mode':'hitl','updated_by':'complete','updated_at':'2026-01-02T00:00:00Z'}))
    p['tool_input']['command']='finish-work'
    reminder = cli(ADAPTER,'checklist-nudge',data=p).stdout
    assert '--unattended' in reminder
    assert '$checklist' in reminder
    check=ROOT/'scripts/lib/checklist.py'
    assert cli(check,'wrap-check','--written-handoff',handoff).returncode==1
    assert cli(check,'wrap-check','--written-handoff',handoff,'--unattended').returncode==0
    assert not list(Path(os.environ['CHECKLIST_STATE_DIR']).glob('*.unattended-wrap'))


def test_broken_advisory_payload_fails_open(sandbox):
    for operation in ('post-compact','pre-compact','context-guard','ledger-record','guard-decide','checklist-nudge'):
        result=subprocess.run([sys.executable,str(ADAPTER),operation],input='invalid',text=True,capture_output=True)
        assert result.returncode==0 and result.stdout==''


def test_codex_cli_uses_child_identity_instead_of_inherited_claude_identity(sandbox):
    _,work=sandbox
    payload('SessionStart',sandbox)
    env=dict(os.environ,CODEX_THREAD_ID='captured-session',CLAUDE_SESSION_ID='parent-session',
             CLAUDE_CODE_SESSION_ID='parent-session',CLAUDE_CODE_ENTRYPOINT='sdk-cli')
    result=cli(ROOT/'scripts/lib/checklist.py','plan',env=env)
    assert result.returncode==0, result.stderr
    assert (Path(os.environ['HANDOFF_LEDGER_DIR'])/'session-touched-paths.captured-session.jsonl').exists()
    assert not (Path(os.environ['HANDOFF_LEDGER_DIR'])/'session-touched-paths.parent-session.jsonl').exists()


def test_uninstall_preserves_trust_for_a_user_hook_added_after_install(sandbox):
    import importlib.util
    spec=importlib.util.spec_from_file_location('codex_trust_test',ROOT/'scripts/lib/codex_trust.py')
    trust=importlib.util.module_from_spec(spec);spec.loader.exec_module(trust)
    home,_=sandbox;codex=home/'.codex'
    result=cli(INSTALL,'--codex-home',codex)
    assert result.returncode==0,result.stderr
    target=codex/'hooks.json';config=codex/'config.toml'
    value=json.loads(target.read_text())
    later={'hooks':[{'type':'command','command':'echo user-later','timeout':2}]}
    value['hooks']['Stop'].append(later)
    target.write_text(json.dumps(value))
    oldkey=str(target.resolve())+':stop:1:0'
    digest=trust.hook_hash('Stop',later,later['hooks'][0])
    config.write_text(trust.update_config_text(config.read_text(),{oldkey:digest}))
    trust.verify_with_hooks_list(shutil.which('codex'),codex,codex,{oldkey:digest})
    result=cli(INSTALL,'--codex-home',codex,'--uninstall')
    assert result.returncode==0,result.stderr
    newkey=str(target.resolve())+':stop:0:0'
    trust.verify_with_hooks_list(shutil.which('codex'),codex,codex,{newkey:digest})


def test_quiet_commit_uses_the_captured_transcript_completion_exit_code(sandbox):
    _,work=sandbox;checkpoint(work)
    p=payload('PostToolUse',sandbox)
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    subprocess.run(['git','-C',str(work),'-c','user.name=Example','-c','user.email=example@example.org',
                    'commit','--allow-empty','-qm','Quiet work'],check=True)
    p['tool_input']['command']='git commit --allow-empty -qm "Quiet work"'
    p['tool_response']=''
    row=json.loads((FIX/'completion.jsonl').read_text())
    item=row['payload']['item'];item['id']=p['tool_use_id']
    item['command'][-1]=p['tool_input']['command'];item['aggregated_output']=''
    with Path(p['transcript_path']).open('a') as handle:handle.write(json.dumps(row)+'\n')
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    stop=payload('Stop',sandbox)
    result=cli(ADAPTER,'guard-decide',data=stop)
    assert result.stdout, 'a quiet owned commit still makes the handoff stale'
    assert json.loads(result.stdout)['decision']=='block'


def test_owned_commit_without_any_handoff_writes_skeleton_and_allows_stop(sandbox):
    _,work=sandbox
    p=payload('PostToolUse',sandbox)
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    commit=subprocess.run(['git','-C',str(work),'-c','user.name=Example','-c','user.email=example@example.org',
                    'commit','--allow-empty','-m','Work'],check=True,text=True,capture_output=True)
    p['tool_input']['command']='git commit --allow-empty -m Work';p['tool_response']=commit.stdout
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    assert not list(Path(os.environ['HANDOFF_STATE_DIR']).glob('*.json'))
    result=cli(ADAPTER,'guard-decide',data=payload('Stop',sandbox))
    assert result.stdout == ''
    path = next(Path(os.environ['HANDOFF_STATE_DIR']).glob('*.json'))
    data = json.loads(path.read_text())
    assert data['resume']['headline'] == ''
    assert data['resume']['open_loops'] == []


def test_read_only_session_without_any_handoff_allows_stop(sandbox):
    p=payload('PostToolUse',sandbox,tool_input={'command':'git status'},tool_response='Process exited with code 0')
    assert cli(ADAPTER,'ledger-record',data=p).returncode==0
    assert cli(ADAPTER,'guard-decide',data=payload('Stop',sandbox)).stdout==''


@pytest.mark.parametrize('source,changes', [('interactive', {}), ('headless', {}), ('interactive', {'agent_id': 'child'}), ('interactive', {'stop_hook_active': True})])
def test_codex_stop_skeleton_gate(sandbox, source, changes):
    stop = payload('Stop', sandbox, source=source, **changes)
    result = cli(ADAPTER, 'guard-decide', data=stop)
    assert result.returncode == 0 and result.stdout == ''
    paths = list(Path(os.environ['HANDOFF_STATE_DIR']).glob('*.json'))
    assert bool(paths) == (source == 'interactive' and not changes)


def test_codex_stop_ignores_another_sessions_newer_dirty_file(sandbox):
    _, work = sandbox
    path = checkpoint(work)
    p = payload('PostToolUse', sandbox, tool_input={'command': 'git status'}, tool_response='Process exited with code 0')
    assert cli(ADAPTER, 'ledger-record', data=p).returncode == 0
    edited = work / 'other.txt'; edited.write_text('x')
    stamp = path.stat().st_mtime + 10; os.utime(edited, (stamp, stamp))
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert cli(ADAPTER, 'guard-decide', data=payload('Stop', sandbox)).stdout == ''
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_codex_session_file_edit_blocks_and_active_stop_does_not_loop(sandbox):
    _, work = sandbox
    path = checkpoint(work)
    edited = work / 'own.txt'; edited.write_text('x')
    event = payload('PostToolUse', sandbox, tool_input={'file_path': str(edited)}, tool_response={'exit_code': 0})
    assert cli(ADAPTER, 'ledger-record', data=event).returncode == 0
    stamp = path.stat().st_mtime + 10; os.utime(edited, (stamp, stamp))
    stop = payload('Stop', sandbox)
    result = cli(ADAPTER, 'guard-decide', data=stop)
    assert json.loads(result.stdout)['decision'] == 'block'
    stop['stop_hook_active'] = True
    assert cli(ADAPTER, 'guard-decide', data=stop).stdout == ''


@pytest.mark.parametrize("owned,newer,expected", [(True, True, "block"), (False, True, "allow"), (True, False, "allow")])
def test_codex_stop_retains_renamed_file_ownership(sandbox, owned, newer, expected):
    _, work = sandbox
    source = work / 'original.txt'; destination = work / 'renamed.txt'
    source.write_text('unchanged line\n' * 100)
    subprocess.run(['git', '-C', str(work), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(work), '-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-qm', 'tracked file'], check=True)
    path = checkpoint(work)
    source.write_text(source.read_text() + 'session edit\n')
    if owned:
        event = payload('PostToolUse', sandbox, tool_input={'file_path': str(source)}, tool_response={'exit_code': 0})
        assert cli(ADAPTER, 'ledger-record', data=event).returncode == 0
    subprocess.run(['git', '-C', str(work), 'mv', source.name, destination.name], check=True)
    status = subprocess.run(['git', '-C', str(work), 'status', '--porcelain=v1', '-z'], capture_output=True, check=True).stdout
    assert status.split(b'\0')[:2] == [b'RM renamed.txt', b'original.txt']
    stamp = path.stat().st_mtime + (10 if newer else -10); os.utime(destination, (stamp, stamp))
    result = cli(ADAPTER, 'guard-decide', data=payload('Stop', sandbox))
    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)['decision'] if result.stdout else 'allow'
    assert decision == expected


def test_uninstall_finishes_when_runtime_copy_is_already_gone(sandbox):
    home, work = sandbox
    codex = home / '.codex'
    codex.mkdir()
    foreign = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'echo foreign', 'timeout': 1}]}]}}
    (codex / 'hooks.json').write_text(json.dumps(foreign))
    (codex / 'config.toml').write_text('model = "custom"\n')
    handoff = checkpoint(work)
    result = cli(INSTALL, '--codex-home', codex)
    assert result.returncode == 0, result.stderr
    shutil.rmtree(codex / 'continuity')
    result = cli(INSTALL, '--codex-home', codex, '--uninstall')
    assert result.returncode == 0, result.stderr
    assert not (codex / 'continuity-install.json').exists()
    assert json.loads((codex / 'hooks.json').read_text()) == foreign
    assert [line for line in (codex / 'config.toml').read_text().splitlines() if line.strip()] == ['model = "custom"']
    assert not [p for p in (codex / 'skills').iterdir() if p.name != '.system']
    assert handoff.exists()
    assert cli(INSTALL, '--codex-home', codex, '--uninstall').returncode == 0
