"""Exercise the production trust reader using a controlled JSON-lines process."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def trust():
    path = Path(__file__).resolve().parents[1] / 'scripts/lib/codex_trust.py'
    spec = importlib.util.spec_from_file_location('trust_reader_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def server_stub(tmp_path, chunks):
    """Each chunk is one OS write; stay alive so EOF cannot wake the reader."""
    stub = tmp_path / 'stub-server'
    stub.write_text(
        f'#!{sys.executable}\n'
        'import json, os, sys, time\n'
        'for line in sys.stdin:\n'
        '    request = json.loads(line)\n'
        '    if request.get("id") == 1:\n'
        '        os.write(1, b\'{"id":1,"result":{}}\\n\')\n'
        '    elif request.get("id") == 2:\n'
        f'        for chunk in {chunks!r}:\n'
        '            os.write(1, chunk)\n'
        '            time.sleep(0.01)\n'
    )
    stub.chmod(0o700)
    return stub


def test_reads_response_coalesced_with_notification(trust, tmp_path):
    payload = (b'{"method":"fixture/notification"}\n'
               b'{"id":2,"result":{"data":[]}}\n')
    stub = server_stub(tmp_path, [payload])
    trust.verify_with_hooks_list(str(stub), tmp_path, tmp_path, {})


@pytest.mark.parametrize('chunks', [
    [b'{"id":2,', b'"result":{"data":[]}}\n'],
    [b'{"method":"fixture/notification"}\n{"id":2,',
     b'"result":{"data":[]}}\n'],
    [b'{"method":"fixture/one"}\n{"method":"fixture/two"}\n'
     b'{"id":2,"result":{"data":[]}}\n'],
])
def test_reads_partial_frames_and_multiple_notifications(trust, tmp_path, chunks):
    stub = server_stub(tmp_path, chunks)
    trust.verify_with_hooks_list(str(stub), tmp_path, tmp_path, {})


def test_rejects_eof_before_matching_response(trust, tmp_path):
    stub = server_stub(tmp_path, [])
    # Close after receiving the second request instead of leaving the pipe open.
    stub.write_text(stub.read_text().replace('for chunk in []:', 'sys.exit(0)\n        for chunk in []:'))
    with pytest.raises(RuntimeError, match='no response for request 2'):
        trust.verify_with_hooks_list(str(stub), tmp_path, tmp_path, {})


def test_still_rejects_untrusted_matching_hook(trust, tmp_path):
    response = {'id': 2, 'result': {'data': [{'hooks': [
        {'key': 'fixture-key', 'currentHash': 'fixture-hash', 'trustStatus': 'untrusted'},
    ]}]}}
    stub = server_stub(tmp_path, [(json.dumps(response) + '\n').encode()])
    with pytest.raises(RuntimeError, match='fixture-key: untrusted'):
        trust.verify_with_hooks_list(str(stub), tmp_path, tmp_path, {'fixture-key': 'fixture-hash'})
