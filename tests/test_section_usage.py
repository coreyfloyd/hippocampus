"""Section evidence against scrubbed captured Claude and Codex tool records."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_slim_harness import helper

FIX = Path(__file__).parent / 'fixtures/usage'


def manifest(*tools):
    return {'sessions': [{'tool': tool, 'transcript': str(FIX / (tool + '.jsonl')),
                          'skills': [{'path': str(FIX / 'SKILL.md'),
                                      'recorded_path': '/redacted/skills/workflow/SKILL.md'}]}
                         for tool in tools]}


def test_both_captured_formats_and_section_sizes():
    report = helper().usage(manifest('claude', 'codex'))
    rows = {r['section']: r for r in report['sections']}
    assert all(r['sessions_loaded'] == 2 for r in rows.values())
    assert rows['Tracker commands']['sessions_with_evidence'] == 1
    assert rows['Repository commands']['sessions_with_evidence'] == 1
    assert rows['Boundary']['sessions_with_evidence'] == 0
    assert rows['Boundary']['status'] == 'no evidence of use'
    assert rows['Boundary']['size']['bytes'] > 0
    assert report['split_candidates'] == []
    assert 'unused' not in json.dumps(report)


def test_duplicate_transcript_does_not_meet_three_session_minimum():
    report = helper().usage(manifest('claude', 'claude', 'claude'))
    assert all(r['sessions_loaded'] == 1 for r in report['sections'])
    assert report['split_candidates'] == []


def test_three_distinct_sessions_gate_split_candidates(tmp_path):
    m = manifest('claude', 'codex', 'claude')
    # Distinct captured session identity, with the same recorded actions.
    copied = tmp_path / 'session.jsonl'
    copied.write_text((FIX / 'claude.jsonl').read_text().replace('captured-claude', 'captured-other'))
    m['sessions'][-1]['transcript'] = str(copied)
    report = helper().usage(m)
    assert all(r['sessions_loaded'] == 3 for r in report['sections'])
    assert report['split_candidates']
    assert all(r['sessions_loaded'] >= 3 for r in report['split_candidates'])
    assert not any(r['section'] == 'Boundary' for r in report['split_candidates'])


def test_no_load_from_listing_prose_or_failed_read(tmp_path):
    m = manifest('claude')
    p = tmp_path / 'failed.jsonl'
    p.write_text((FIX / 'claude.jsonl').read_text().replace('"is_error": false', '"is_error": true'))
    m['sessions'][0]['transcript'] = str(p)
    assert helper().usage(m)['sections'] == []


def test_cli_and_malformed_transcript(tmp_path):
    p = tmp_path / 'manifest.json'
    p.write_text(json.dumps(manifest('claude', 'codex')))
    cli = FIX.parents[2] / 'skills/slim-harness/scripts/harness.py'
    result = subprocess.run([sys.executable, str(cli), 'usage', str(p)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['sections']
    bad = tmp_path / 'bad.jsonl'; bad.write_text('{\n')
    m = manifest('claude'); m['sessions'][0]['transcript'] = str(bad)
    p.write_text(json.dumps(m))
    result = subprocess.run([sys.executable, str(cli), 'usage', str(p)], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'bad.jsonl:1' in result.stderr


def test_evidence_must_follow_completed_load_and_not_come_from_outputs(tmp_path):
    records = [json.loads(line) for line in (FIX / 'claude.jsonl').read_text().splitlines()]
    # The action was issued before the skill read returned, so cannot establish use.
    p = tmp_path / 'parallel.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in [records[0], records[2], records[1], records[3]]) + '\n')
    m = manifest('claude'); m['sessions'][0]['transcript'] = str(p)
    report = helper().usage(m)
    assert all(r['sessions_with_evidence'] == 0 for r in report['sections'])


def test_headings_in_fences_and_token_boundaries():
    m = helper()
    captured = (FIX / 'SKILL.md').read_text()
    # Use captured prose as the payload; fenced heading syntax is not a section.
    sections = m.skill_sections('## Wrapper\n```markdown\n' + captured + '\n```\n')
    assert len(sections) == 1
    assert sections[0][0] == 'Wrapper'
    # Sentence-ending punctuation and bare slashes are not paths or commands.
    assert m.usage_markers('Questions are not authorization. /') == []


def test_partial_reads_and_incomplete_tool_calls_do_not_count(tmp_path):
    original = [json.loads(line) for line in (FIX / 'claude.jsonl').read_text().splitlines()]
    for variant in ('partial', 'missing-result'):
        records = json.loads(json.dumps(original))
        if variant == 'partial':
            records[0]['message']['content'][0]['input']['limit'] = 10
        else:
            records.pop(1)
        p = tmp_path / (variant + '.jsonl')
        p.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        m = manifest('claude'); m['sessions'][0]['transcript'] = str(p)
        assert helper().usage(m)['sections'] == []


def test_shell_fence_commands_are_evidence_markers():
    m = helper()
    records = [json.loads(line) for line in (FIX / 'codex.jsonl').read_text().splitlines()]
    payload = records[2]['payload']['input']
    command = m.usage_commands('exec', payload)[0]
    assert 'git status' in m.usage_markers('```bash\n' + command + '\n```\n')


def test_piped_cat_and_truncated_results_are_not_full_loads(tmp_path):
    m = helper()
    assert m.usage_reads('Bash', {}, ['cat /redacted/skills/workflow/SKILL.md | head -10']) == []
    records = [json.loads(line) for line in (FIX / 'claude.jsonl').read_text().splitlines()]
    records[1]['message']['content'][0]['truncated'] = True
    p = tmp_path / 'truncated.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
    request = manifest('claude'); request['sessions'][0]['transcript'] = str(p)
    assert m.usage(request)['sections'] == []


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('body', ['exit_code: 1', '"isError": true', 'Warning: truncated output'])
def test_successful_reads_keep_failure_examples_as_content(tool, body, tmp_path):
    records = [json.loads(line) for line in (FIX / (tool + '.jsonl')).read_text().splitlines()]
    if tool == 'claude':
        records[1]['message']['content'][0]['content'] = body
    else:
        records[1]['payload']['output'][0]['text'] = body
    transcript = tmp_path / 'examples.jsonl'
    transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
    request = manifest(tool); request['sessions'][0]['transcript'] = str(transcript)
    report = helper().usage(request)
    assert report['sections'], 'a returned skill with failure-handling prose is still loaded'
    assert all(row['sessions_loaded'] == 1 for row in report['sections'])
    assert any(row['sessions_with_evidence'] == 1 for row in report['sections'])


@pytest.mark.parametrize('metadata', [{'is_error': True}, {'isError': True},
                                     {'truncated': True}, {'exit_code': 1}, {'status': 'failed'}])
@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_structured_failure_metadata_excludes_reads(tool, metadata, tmp_path):
    records = [json.loads(line) for line in (FIX / (tool + '.jsonl')).read_text().splitlines()]
    result = records[1]['message']['content'][0] if tool == 'claude' else records[1]['payload']
    result.update(metadata)
    transcript = tmp_path / 'status.jsonl'
    transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
    request = manifest(tool); request['sessions'][0]['transcript'] = str(transcript)
    assert helper().usage(request)['sections'] == []


@pytest.mark.parametrize('version', ['1.2.3', 'v1.2.3', '2.0.0'])
def test_version_prose_is_not_a_path_marker(version):
    assert helper().usage_markers('Version ' + version + '.') == []


@pytest.mark.parametrize('path', ['/redacted/skills/workflow/SKILL.md',
                                 './skills/workflow/SKILL.md', '../skills/workflow/SKILL.md',
                                 '~/skills/workflow/SKILL.md', 'skills/workflow/SKILL.md'])
def test_real_paths_remain_markers(path):
    assert helper().usage_markers(path) == [path]


def test_version_mentions_do_not_create_evidence_or_split_candidates(tmp_path):
    # Review-supplied version prose, inserted into the captured prose-only section.
    snapshot = tmp_path / 'SKILL.md'
    snapshot.write_text((FIX / 'SKILL.md').read_text().replace('Questions are not authorization.', 'Version 1.2.3'))
    request = manifest('claude', 'claude', 'claude')
    for index, session in enumerate(request['sessions']):
        records = [json.loads(line) for line in (FIX / 'claude.jsonl').read_text().splitlines()]
        for record in records:record['sessionId'] = 'captured-' + str(index)
        records[2]['message']['content'][0]['input']['command'] += ' 1.2.3'
        transcript = tmp_path / (str(index) + '.jsonl')
        transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
        session['transcript'] = str(transcript); session['skills'][0]['path'] = str(snapshot)
    report = helper().usage(request)
    boundary = next(row for row in report['sections'] if row['section'] == 'Boundary')
    assert boundary['sessions_loaded'] == 3
    assert boundary['markers'] == []
    assert boundary['sessions_with_evidence'] == 0
    assert boundary['status'] == 'no evidence of use'
    assert not any(row['section'] == 'Boundary' for row in report['split_candidates'])


@pytest.mark.parametrize('exit_code', [0, 1])
def test_codex_result_metadata_is_separate_from_command_output(exit_code, tmp_path):
    records = [json.loads(line) for line in (FIX / 'codex.jsonl').read_text().splitlines()]
    records[1]['payload']['output'] = {'exit_code': exit_code, 'output': 'exit_code: 1\nWarning: truncated output'}
    transcript = tmp_path / 'command-result.jsonl'
    transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
    request = manifest('codex'); request['sessions'][0]['transcript'] = str(transcript)
    assert bool(helper().usage(request)['sections']) == (exit_code == 0)
