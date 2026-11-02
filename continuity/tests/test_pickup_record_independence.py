"""Pickup reconstructs the handoff without consulting an external record."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/pickup/scripts'))
import pickup


@pytest.mark.parametrize('tool_present', [False, True])
def test_selected_handoff_preserves_pointers_and_carried_commitments_without_tools(tmp_path, monkeypatch, tool_present):
    payload = {
        'schema_version': 2,
        'subject': {'working_directory': str(tmp_path), 'session_id': 'previous'},
        'git': {'repository_root': '', 'branch': ''},
        'uncommitted_files': [],
        'resume': {
            'headline': 'Continue the work', 'next_action': 'Verify the result',
            'open_loops': [{'type': 'commitment', 'context': 'Check the deployment',
                            'anchor': {'ticket': 'example/project#12'},
                            'session_id': 'previous', 'produced_at': '2026-10-18T12:00:00Z',
                            'disposition': 'verify'}],
        },
    }
    path = tmp_path / 'handoff.json'
    path.write_text(json.dumps(payload))
    marker = tmp_path / 'called'
    if tool_present:
        tool = tmp_path / ('g' + 'h')
        tool.write_text('#!/bin/sh\nprintf called > "' + str(marker) + '"\nexit 99\n')
        tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path))
    report = pickup.handoff_briefing(str(path))
    assert not marker.exists()
    assert report['resume'] == payload['resume']
    lines = [row['line'] for row in report['briefing']]
    assert lines.count('No record read is bound.') == 1
    assert 'Check the deployment' in '\n'.join(lines)
    assert 'example/project#12' in '\n'.join(lines)
    assert not {'ticket', 'tickets', 'commitments', 'commitments_reason'} & report.keys()


def test_removed_view_is_an_unknown_flag():
    result = subprocess.run(['bash', str(ROOT / 'scripts/pickup.sh'), '--machine'],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert 'unrecognized option: --machine' in json.loads(result.stdout)['message']


def test_external_record_tool_is_never_called(tmp_path, monkeypatch):
    tool = tmp_path / ('g' + 'h')
    marker = tmp_path / 'called'
    tool.write_text('#!/bin/sh\nprintf called > "' + str(marker) + '"\nexit 99\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path))
    # The recorded source still contains command text; reconstructing it must
    # never execute it or consult an external record.
    report = pickup.build_report([str(ROOT / 'tests/fixtures/pickup-session.jsonl')])
    assert 'error' not in report
    assert not {'ticket_refs', 'tickets', 'commitments'} & report.keys()
    assert not marker.exists()
