"""Record writes exercised through the checklist CLI and real stub stores."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/lib/checklist.py'


def run(tmp_path, operation, profile, payload, rows):
    for name, value in [('profile', profile), ('input', payload), ('rows', rows)]:
        (tmp_path / (name + '.json')).write_text(json.dumps(value))
    return subprocess.run([sys.executable, str(CLI), operation, '--user-profile',
        str(tmp_path / 'profile.json'), '--handoff', str(tmp_path / 'input.json'),
        '--filing', str(tmp_path / 'rows.json')], capture_output=True, text=True,
        env=dict(os.environ, CLAUDE_CODE_ENTRYPOINT='cli', HANDOFF_LEDGER_DIR=str(tmp_path)))


def store(tmp_path, mode='ok'):
    script = tmp_path / 'store.py'
    script.write_text('''import json, sys
from pathlib import Path
p = Path(__file__).with_suffix('.json')
r = json.load(sys.stdin)
data = json.loads(p.read_text()) if p.exists() else []
if r['operation'] == 'lookup':
    if MODE == 'badlookup':
        print('{}'); sys.exit()
    found = next((x for x in data if x['identity'] == r['identity']), None)
    print(json.dumps({'status': 'found', 'receipt': found} if found else {'status': 'not_found'}))
else:
    if MODE == 'failed':
        print(json.dumps({'status': 'failed', 'error': 'store refused'})); sys.exit(1)
    receipt = {'identity': r['identity'], 'destination': r['kind'] + ':' + str(len(data))}
    data.append(receipt); p.write_text(json.dumps(data))
    if MODE == 'lost': sys.exit()
    print(json.dumps({'status': 'saved', 'receipt': receipt}))
'''.replace("MODE", repr(mode)))
    return {'command': [sys.executable, str(script)]}


def item(text='change', **extra):
    return dict(type='progress', context=text, session_id='producer',
                produced_at='2026-11-03T12:00:00Z', **extra)


def payload(items):
    return {'subject': {'session_id': 'successor'}, 'resume': {'session_summary': 'Reconciled the session items with the record stores.', 'open_loops': items}}


def row(index=0, rule='R2', **extra):
    return dict(index=index, rule=rule, status='pending', read_status='ok', **extra)


def test_routing_and_receipts_then_mid_session_wrap_writes_once(tmp_path):
    binding = store(tmp_path)
    profile = {'name': 'user', 'record_writes': {k: binding for k in
               ('tickets', 'projects', 'documents', 'scheduled_jobs')}}
    items = [item(k, record_kind=k) for k in ('tickets', 'projects', 'documents', 'scheduled_jobs')]
    rows = [row(i) for i in range(4)]
    first = run(tmp_path, 'record', profile, payload(items), rows)
    assert first.returncode == 0, first.stderr
    output = json.loads(first.stdout)
    assert output['resume']['open_loops'] == []
    assert [r['receipt']['destination'].split(':')[0] for r in output['filing']['items']] == list(profile['record_writes'])
    again = run(tmp_path, 'file', profile, payload(items), rows)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)['resume']['open_loops'] == []
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 4


def test_unbound_keeps_and_warns(tmp_path):
    result = run(tmp_path, 'file', {'name': 'user'}, payload([item()]), [row()])
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out['resume']['open_loops'] == [item()]
    assert 'tickets' in out['filing']['warnings'][0]


def test_lost_receipt_is_uncertain_then_lookup_reuses_it(tmp_path):
    binding = store(tmp_path, 'lost')
    profile = {'name': 'user', 'record_writes': {'tickets': binding}}
    first = run(tmp_path, 'record', profile, payload([item()]), [row()])
    assert first.returncode == 1
    out = json.loads(first.stdout)
    assert out['filing']['items'][0]['status'] == 'uncertain'
    assert out['resume']['open_loops'] == [item()]
    retry = run(tmp_path, 'file', profile, out, [row()])
    assert retry.returncode == 0, retry.stderr
    assert not json.loads(retry.stdout)['resume']['open_loops']
    assert len(json.loads((tmp_path / 'store.json').read_text())) == 1


def test_failed_or_malformed_lookup_never_writes(tmp_path):
    binding = store(tmp_path, 'badlookup')
    result = run(tmp_path, 'record', {'name': 'user', 'record_writes': {'tickets': binding}}, payload([item()]), [row()])
    assert result.returncode == 1
    assert json.loads(result.stdout)['resume']['open_loops'] == [item()]
    assert not (tmp_path / 'store.json').exists()


def test_explicit_write_failure_keeps_store_error(tmp_path):
    binding = store(tmp_path, 'failed')
    result = run(tmp_path, 'file', {'name': 'user', 'record_writes': {'tickets': binding}}, payload([item()]), [row()])
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert 'store refused' in str(out['filing']['failures'])
    assert out['resume']['open_loops'] == [item()]


def test_commitments_use_schedule_when_bound_otherwise_ticket(tmp_path):
    binding = store(tmp_path)
    commitment = dict(item(), type='commitment', recurrence='daily')
    for configured, expected in [(True, 'scheduled_jobs'), (False, 'tickets')]:
        profile = {'name': 'user', 'record_writes': {'tickets': binding}}
        if configured:
            profile['record_writes']['scheduled_jobs'] = binding
        result = run(tmp_path, 'record', profile, payload([commitment]), [row()])
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['filing']['items'][0]['binding'] == expected


def test_retired_record_binding_refused_by_plan(tmp_path):
    result = run(tmp_path, 'plan', {'name': 'user', 'bindings': {'record': None}}, {}, [])
    assert result.returncode == 1
    assert 'record_writes' in result.stderr


def test_wrap_rejects_filed_record_without_matching_receipt(tmp_path):
    binding = store(tmp_path)
    profile = {'name': 'user', 'record_writes': {'tickets': binding}}
    first = run(tmp_path, 'record', profile, payload([item()]), [row()])
    assert first.returncode == 0, first.stderr
    out = json.loads(first.stdout)
    del out['filing']['items'][0]['receipt']
    source = tmp_path / 'checkpoint.json'
    saved = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint',
        '--cwd', str(tmp_path), '--session-id', 'producer'], input=json.dumps(out),
        capture_output=True, text=True, env=dict(os.environ, CLAUDE_CODE_ENTRYPOINT='cli',
        HANDOFF_PATH=str(source), HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger')))
    assert saved.returncode == 0, saved.stderr
    checked = subprocess.run([sys.executable, str(CLI), 'wrap-check', '--user-profile',
        str(tmp_path / 'profile.json'), '--written-handoff', str(source),
        '--record-at', '2026-11-03T13:00:00Z'], capture_output=True, text=True,
        env=dict(os.environ, CLAUDE_CODE_ENTRYPOINT='cli', HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger')))
    assert checked.returncode == 1
    assert 'receipt' in checked.stderr


def test_lookup_failures_and_unusable_receipts_keep_original_identity(tmp_path):
    binding = store(tmp_path)
    profile = {'name': 'user', 'record_writes': {'tickets': binding}}
    script = tmp_path / 'store.py'
    cases = [
        ("print('{}')", 'failed'),
        ("print('{\"status\": \"failed\", \"error\": \"lookup unavailable\"}')", 'failed'),
        ("print('{\"status\": \"found\", \"receipt\": {\"identity\": {}, \"destination\": \"wrong item\"}}')", 'failed'),
        ("import json, sys\nr=json.load(sys.stdin)\nprint(json.dumps({'status':'not_found'} if r['operation']=='lookup' else {'status':'saved','receipt': {'identity': {}, 'destination':'wrong item'}}))", 'uncertain'),
    ]
    original = item('full original text')
    for program, expected in cases:
        script.write_text(program)
        result = run(tmp_path, 'record', profile, payload([original]), [row()])
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out['resume']['open_loops'] == [original]
        assert out['filing']['items'][0]['status'] == expected


def test_mid_session_then_checkpoint_and_wrap_in_both_tools(tmp_path):
    for tool in ('claude', 'codex'):
        home = tmp_path / tool
        home.mkdir()
        binding = store(home)
        profile = {'name': 'user', 'record_read': {'command': '/read-work'},
                   'record_writes': {'tickets': binding}}
        first = run(home, 'record', profile, payload([item()]), [row()])
        assert first.returncode == 0, first.stderr
        # Re-present the original item at wrap; its original identity is retained.
        final = run(home, 'file', profile, payload([item()]), [row()])
        assert final.returncode == 0, final.stderr
        target = home / 'handoff.json'
        environment = dict(os.environ, HANDOFF_PATH=str(target), HANDOFF_LEDGER_DIR=str(home / 'ledger'),
                           HANDOFF_STATE_DIR=str(home / 'state'), HIPPOCAMPUS_CONFIG=str(home / 'absent.json'))
        environment.pop('CODEX_THREAD_ID', None)
        environment.pop('HIPPOCAMPUS_HARNESS', None)
        if tool == 'claude':
            environment['CLAUDE_CODE_ENTRYPOINT'] = 'cli'
        else:
            environment['HIPPOCAMPUS_HARNESS'] = 'codex'
            environment['CODEX_THREAD_ID'] = 'producer'
            environment['CODEX_HOME'] = str(home / 'codex')
            sessions = home / 'codex/sessions'
            sessions.mkdir(parents=True)
            (sessions / 'producer.jsonl').write_text(json.dumps({
                'type': 'session_meta', 'payload': {'id': 'producer', 'source': 'cli'}}) + '\n')
        def invoke(script, *args, data=None):
            return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                                  input=data, capture_output=True, text=True, env=environment)
        planned = invoke('scripts/lib/checklist.py', 'plan', '--user-profile', home / 'profile.json', '--session-id', 'producer')
        assert planned.returncode == 0, planned.stderr
        assert json.loads(planned.stdout)['record_read'] == {'command': '/read-work'}
        saved = invoke('scripts/lib/handoff.py', 'checkpoint', '--cwd', home, '--session-id', 'producer',
                       '--trigger', 'wrap', data=final.stdout)
        assert saved.returncode == 0, saved.stderr
        checked = invoke('scripts/lib/checklist.py', 'wrap-check', '--user-profile', home / 'profile.json',
                         '--written-handoff', target, '--record-at', '2026-11-03T13:00:00Z')
        assert checked.returncode == 0, checked.stderr
        assert len(json.loads((home / 'store.json').read_text())) == 1
        written = json.loads(target.read_text())
        assert written['filing']['items'][0]['receipt']['identity'] == {
            'session_id': 'producer', 'produced_at': item()['produced_at'], 'text': item()['context']}


def test_record_skill_is_shipped_in_both_installations(tmp_path):
    skill = ROOT / 'skills/record/SKILL.md'
    assert skill.is_file()
    install = subprocess.run([sys.executable, str(ROOT / 'scripts/install-codex.py'),
        '--codex-home', str(tmp_path / 'codex')], capture_output=True, text=True,
        env=dict(os.environ, HOME=str(tmp_path), HIPPOCAMPUS_CONFIG=str(tmp_path / 'absent.json')))
    assert install.returncode == 0, install.stderr
    assert (tmp_path / 'codex/skills/record/SKILL.md').read_text() == skill.read_text()
    assert (ROOT / '.claude-plugin/plugin.json').is_file()
    assert 'record' in skill.read_text() and 'Codex' in skill.read_text()


def test_record_step_runs_even_with_no_writes_bound(tmp_path):
    result = run(tmp_path, 'plan', {'name': 'user'}, {}, [])
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)['steps'][0]
    assert record['id'] == 'record'
    assert record['package'] is True
    assert record['binding'] is not None
    assert record['binding']['command'] == '/hippocampus:record'
    assert 'slot' not in record


def test_wrap_cannot_pass_a_bound_project_item_without_filing(tmp_path):
    profile = {'name': 'user', 'record_writes': {'projects': store(tmp_path)}}
    source = payload([item(record_kind='projects', disposition='carry')])
    target = tmp_path / 'handoff.json'
    (tmp_path / 'profile.json').write_text(json.dumps(profile))
    env = dict(os.environ, CLAUDE_CODE_ENTRYPOINT='cli', HANDOFF_PATH=str(target),
               HANDOFF_LEDGER_DIR=str(tmp_path / 'ledger'))
    saved = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'checkpoint',
        '--cwd', str(tmp_path), '--session-id', 'producer'], input=json.dumps(source),
        capture_output=True, text=True, env=env)
    assert saved.returncode == 0, saved.stderr
    checked = subprocess.run([sys.executable, str(CLI), 'wrap-check', '--user-profile',
        str(tmp_path / 'profile.json'), '--written-handoff', str(target), '--record-at',
        '2026-11-03T13:00:00Z'], capture_output=True, text=True, env=env)
    assert checked.returncode == 1
    assert 'bound projects' in checked.stderr
