"""Duplicate detection over test-authored instruction files."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_slim_harness import SKILL, entry, helper

# Test-owned input shared by the instruction-parsing cases.
RULE = ('Never scan a catalog or independently review unrelated files.')


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.md'
    path.write_text(RULE + '\n\nDo not commit.\n')
    return path


def span_text(span):
    lines = Path(span['path']).read_text().splitlines()
    return '\n'.join(lines[span['start_line'] - 1:span['end_line']])


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_exact_and_near_real_instruction_spans(tool, tmp_path, source):
    copied = tmp_path / 'rules.md'
    copied.write_text(RULE + '\n\n' + RULE.replace('catalog', 'loaded catalog') + '\n')
    manifest = dict(tool=tool, files=[entry(source, 'skill'), entry(copied)])
    before = {p: p.read_bytes() for p in (source, copied)}
    script = SKILL / 'scripts/harness.py'
    named = tmp_path / 'manifest.json'; named.write_text(json.dumps(manifest))
    run = subprocess.run([sys.executable, str(script), 'duplicates', str(named)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert {row['match'] for row in result['duplicates']} == {'exact', 'near'}
    assert len(result['duplicates']) == 2
    for row in result['duplicates']:
        assert row['type'] == 'duplicate-rule'
        assert len(row['spans']) == 2
        assert {span['source'] for span in row['spans']} == {str(source.resolve()), str(copied)}
        for span in row['spans']:
            assert span['text'].replace('\n', ' ') in span_text(span).replace('\n', ' ')
        assert '/hippocampus:slim-harness' in row['action']
        assert 'does not own' in row['action']
    assert {p: p.read_bytes() for p in before} == before
    assert helper().duplicates(manifest) == result


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_loaded_scope_roles_aliases_and_unresolved(tool, tmp_path, source):
    copied = tmp_path / 'rules.md'; copied.write_text(RULE + '\n')
    alias = tmp_path / 'alias.md'; alias.symlink_to(copied)
    missing = tmp_path / 'missing.md'
    files = [entry(source, 'skill', 'listed'), entry(copied), entry(alias),
             entry(missing), entry(source, 'skill', 'other')]
    assert helper().duplicates(dict(tool=tool, files=files)) == {
        'duplicates': [], 'unresolved': [str(missing)]}
    # Parent-attested roles are loaded even when the agent itself lacks a copy.
    agent = tmp_path / 'agent.md'
    agent.write_text('Report parser failures clearly.\n')
    files.append(entry(agent, 'agent', role_paths=[str(source)]))
    rows = helper().duplicates(dict(tool=tool, files=files))['duplicates']
    assert len(rows) == 1
    assert len({s['source'] for s in rows[0]['spans']}) == 2


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_output_style_scope_and_no_self_duplicates(tool, tmp_path, source):
    copied = tmp_path / 'style.md'; copied.write_text(RULE + '\n\n' + RULE)
    files = [entry(source, 'skill'), entry(copied, 'output-style')]
    rows = helper().duplicates(dict(tool=tool, files=files))['duplicates']
    assert len(rows) == (2 if tool == 'claude' else 0)
    assert helper().duplicates(dict(tool=tool, files=[entry(copied)]))['duplicates'] == []


def test_markdown_boundaries_metadata_and_line_ranges(tmp_path, source):
    text = source.read_text()
    # Wrap the input differently and put extra copies in non-prose surfaces.
    copied = tmp_path / 'rules.md'
    copied.write_text('---\ndescription: ' + RULE + '\n---\n# ' + RULE +
                      '\n\n```text\n' + RULE + '\n```\n\n- **' +
                      RULE.replace('catalog or independently', 'catalog\n  or independently') + '**\n')
    rows = helper().duplicates(dict(tool='codex', files=[entry(source, 'skill'), entry(copied)]))['duplicates']
    assert len(rows) == 1
    span = next(s for s in rows[0]['spans'] if s['path'] == str(copied))
    assert (span['start_line'], span['end_line']) == (10, 11)
    assert source.read_text() == text


def test_unrelated_and_opposite_rules_are_not_near_duplicates(tmp_path, source):
    copied = tmp_path / 'rules.md'
    copied.write_text(RULE.replace('Never', 'Always') + '\n\n' +
                      'Use stable identifiers for pending reviews.\n')
    rows = helper().duplicates(dict(tool='codex', files=[entry(source, 'skill'), entry(copied)]))['duplicates']
    assert not any(any('Always scan a catalog' in s['text'] for s in r['spans']) for r in rows)


def test_invalid_tool_is_rejected():
    with pytest.raises(ValueError, match='tool'):
        helper().duplicates(dict(tool='unknown', files=[]))


def test_short_exact_instruction_is_not_lost_to_near_match_noise_filter(tmp_path, source):
    # A short instruction still requires an exact report.
    copied = tmp_path / 'rules.md'; copied.write_text('Do not commit.\n')
    rows = helper().duplicates(dict(tool='codex', files=[entry(source, 'skill'), entry(copied)]))['duplicates']
    assert len(rows) == 1
    assert rows[0]['match'] == 'exact'
    assert all(span['text'] == 'Do not commit.' for span in rows[0]['spans'])


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('header,separator', [
    ('A lesson is… | It goes to.', '--- | ---'),
    ('| A lesson is… | It goes to. |', '|---|---|'),
    ('| A lesson is… | It goes to.', '--- | --- |'),
    ('A lesson is… | It goes to. |', '| :--- | ---: |'),
    ('A lesson is… | It goes to.', ':---: | ---:'),
    (r'A lesson is… \| context | It goes to.', '--- | ---'),
    (r'A lesson is…\\| It goes to.', '--- | ---'),
    ('|| It goes to. |', '|---|---|'),
    ('It goes to. |', '---'),
])
def test_table_blocks_excluded_with_optional_outer_pipes(tool, header, separator, tmp_path, source):
    # Markdown table cells must be excluded from instruction matches.
    copied = tmp_path / 'rules.md'
    lines = [header, separator, RULE + ' | **That skill** (its steps or gotchas)',
             'Do not commit.', '', RULE]
    copied.write_text('\n'.join(lines) + '\n')
    before = copied.read_bytes()
    rows = helper().duplicates(dict(tool=tool, files=[entry(source, 'skill'), entry(copied)]))['duplicates']
    assert len(rows) == 1, rows
    span = next(s for s in rows[0]['spans'] if s['path'] == str(copied))
    assert span['text'] == RULE
    assert (span['start_line'], span['end_line']) == (6, 6)
    assert copied.read_bytes() == before


@pytest.mark.parametrize('boundary', ['# Review', '- ' + RULE, '> ' + RULE,
                                      '```\n' + RULE + '\n```', '<!-- table ends -->'])
def test_table_stops_at_new_markdown_blocks(boundary, tmp_path, source):
    copied = tmp_path / 'rules.md'
    copied.write_text('A lesson is… | It goes to.\n--- | ---\n' + RULE + ' | **That skill**\n' +
                      boundary + '\n\n' + RULE + '\n')
    rows = helper().duplicates(dict(tool='codex', files=[entry(source, 'skill'), entry(copied)]))['duplicates']
    # A list/quote holds real prose; headings, comments, and code do not.
    assert len(rows) == (2 if boundary.startswith(('- ', '> ')) else 1), rows


def test_pipe_prose_without_a_valid_table_separator_remains_visible(tmp_path, source):
    copied = tmp_path / 'rules.md'
    copied.write_text(RULE + ' | **That skill**\n')
    rows = helper().duplicates(dict(tool='codex', files=[entry(source, 'skill'), entry(copied)]))['duplicates']
    assert len(rows) == 1
