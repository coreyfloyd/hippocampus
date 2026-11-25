"""Package-executed binding commands expand `$VAR`, `${VAR}` and a leading `~`, without a shell."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from test_durable_checkpoint import invoke as checkpoint
from test_record_writes import item, payload, row, run, store

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import record_write


def wrapper(home, name, target):
    """``home/bin/<name>`` runs the stub store, so a binding can name it through the home directory."""
    path = home / 'bin' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$0.args"\nexec ' +
                    ' '.join(f"'{part}'" for part in target['command']) + '\n')
    path.chmod(0o755)
    return path


def arguments(path):
    return Path(str(path) + '.args').read_text().splitlines()


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / 'home'
    path.mkdir()
    monkeypatch.setenv('HOME', str(path))
    monkeypatch.delenv('UNSET_322', raising=False)
    return path


def ask_item():
    return {**item('Approve the fixture change?'), 'type': 'decision', 'owner_agent': 'agent'}


def test_home_variable_ask_binding_files_through_record_write(tmp_path, home):
    script = wrapper(home, 'ask.sh', store(tmp_path))
    result = record_write.execute({'command': '"$HOME/bin/ask.sh" --x', 'owner_agent': 'agent'},
                                  'asks', ask_item(), {'index': 0})
    assert result['status'] == 'filed', result
    assert result['destination'] == 'asks:0'
    assert arguments(script) == ['--x']


@pytest.mark.parametrize('command', ['~/bin/ask.sh', '${HOME}/bin/ask.sh', ['$HOME/bin/ask.sh']])
def test_tilde_braced_variable_and_argv_list_reach_the_command(tmp_path, home, command):
    wrapper(home, 'ask.sh', store(tmp_path))
    response = record_write.invoke({'command': command}, {'operation': 'lookup'})
    assert response == {'status': 'not_found'}


def test_unset_variable_stays_literal_and_the_error_names_it(home):
    with pytest.raises(ValueError, match=r'\$UNSET_322/x'):
        record_write.invoke({'command': '"$UNSET_322/x"'}, {'operation': 'lookup'})


def test_no_shell_semantics_reach_the_process(home):
    script = home / 'bin' / 'echo-args.sh'
    script.parent.mkdir(parents=True)
    script.write_text(f'#!{sys.executable}\nimport json, sys\nprint(json.dumps({{"status": "found", "argv": sys.argv[1:]}}))\n')
    script.chmod(0o755)
    response = record_write.invoke({'command': "\"$HOME/bin/echo-args.sh\" 'a|b' '*'"}, {'operation': 'lookup'})
    assert response['argv'] == ['a|b', '*']


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_durable_checkpoint_delivers_a_requested_ask_through_a_home_binding(tmp_path, provider):
    home = tmp_path / 'home'

    def profile(binding):
        wrapper(home, 'ask.sh', binding)
        return {'name': 'fixture', 'ask': {'command': '"$HOME/bin/ask.sh" --x', 'owner_agent': 'fixture-owner'}}

    items = [{**item('Approve the fixture schedule?'), 'type': 'commitment', 'session_id': 'fixture',
              'disposition': 'File through fixture approval route', 'choices': ['approve', 'defer']}]
    rows = [{'index': 0, 'rule': 'R3', 'status': 'pending', 'ask_delivery': 'requested',
             'choices': ['approve', 'defer']}]
    result = checkpoint(tmp_path, provider, items=items, rows=rows, profile=profile)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert 'ask write failed' not in json.dumps(report['errors'])
    [entry] = report['items']
    assert entry['status'] == 'filed', entry
    assert entry['receipt']['owner_agent'] == 'fixture-owner'


def test_record_writes_kind_with_home_files_at_wrap(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    wrapper(home, 'tickets.sh', store(tmp_path))
    monkeypatch.setenv('HOME', str(home))
    profile = {'name': 'user', 'record_writes': {'tickets': {'command': '"$HOME/bin/tickets.sh"'}}}
    rows = [row(rule='R5', priority='p2', priority_reason='fixture follow-up')]
    result = run(tmp_path, 'file', profile, payload([item()]), rows)
    assert result.returncode == 0, result.stderr
    [filed] = json.loads(result.stdout)['filing']['items']
    assert filed['status'] == 'filed', filed


def test_sweep_open_session_checks_expand_home(home):
    spec = importlib.util.spec_from_file_location('expansion_sweep', ROOT / 'scripts/lib/sweep.py')
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    script = home / 'bin' / 'sessions.sh'
    script.parent.mkdir(parents=True)
    script.write_text('#!/bin/sh\necho abc\n')
    script.chmod(0o755)
    config = {'open_session_checks': ['"$HOME/bin/sessions.sh"'], 'binding_timeout_seconds': 10}
    result = sweep.open_session_checks(config, {'session_ids': [], 'method': 'fixture'})
    assert result['failed'] is False, result
    assert 'abc' in result['session_ids']
