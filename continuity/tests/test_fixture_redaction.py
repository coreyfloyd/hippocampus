"""The shipped Claude session fixture carries structure, not session content.

tests/fixtures/pickup-session.jsonl is cut from a private session. The
redactor's --redact-commands mode removes every command, tool result, thinking
block, and claude.ai session URL; these tests pin that the shipped copy has
none, and that running the redactor over it again changes nothing.

Run with: uv run --with pytest pytest tests/test_fixture_redaction.py -q
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "pickup-session.jsonl")
REDACTOR = os.path.join(HERE, "fixtures", "redact_pickup_transcript.py")
SESSION_URL = re.compile(r"claude\.ai/(code/)?session_")


def _rows():
    with open(FIXTURE, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _blocks(rows):
    for row in rows:
        content = row.get("message", {}).get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    yield row, block


def test_fixture_has_no_thinking_block_or_raw_tool_output():
    rows = _rows()
    assert not any(b.get("type") == "thinking" for _, b in _blocks(rows))
    assert not any("toolUseResult" in r for r in rows)


def test_fixture_has_no_session_url():
    assert not SESSION_URL.search(open(FIXTURE, encoding="utf-8").read())


def test_fixture_tool_results_are_placeholders():
    results = [b for _, b in _blocks(_rows()) if b.get("type") == "tool_result"]
    assert results
    for block in results:
        content = block["content"]
        texts = [content] if isinstance(content, str) else [p.get("text", "") for p in content
                                                              if isinstance(p, dict)]
        assert all(not t.strip() or t.startswith("[REDACTED") for t in texts), texts


def test_fixture_commands_and_free_text_inputs_are_placeholders():
    uses = [b for _, b in _blocks(_rows()) if b.get("type") == "tool_use"]
    assert uses
    for block in uses:
        for key in ("command", "description", "prompt", "content", "message", "summary", "query"):
            if key in block["input"]:
                assert block["input"][key].startswith("[REDACTED"), (block["name"], key)
        if "file_path" in block["input"]:
            assert block["input"]["file_path"].startswith("/redacted/")


def test_fixture_keeps_the_record_structure():
    rows = _rows()
    assert len(rows) == 699
    assert {"user", "assistant"} == {r["type"] for r in rows}
    assert {b["type"] for _, b in _blocks(rows)} == {"text", "tool_use", "tool_result"}
    assert {"tool_use", "end_turn"} <= {r["message"].get("stop_reason") for r in rows
                                         if r["type"] == "assistant"}


def test_redactor_drops_non_text_tool_result_payloads(tmp_path):
    payload = "iVBORw0KGgoPRIVATE"
    row = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": payload}},
            {"type": "tool_reference", "tool_name": "SendMessage"}]}]}}
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    src.write_text(json.dumps(row) + "\n")
    done = subprocess.run([sys.executable, "-I", REDACTOR, "--redact-commands", str(src), str(out)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    blocks = json.loads(out.read_text())["message"]["content"][0]["content"]
    assert blocks == [{"type": "image"}, {"type": "tool_reference", "tool_name": "SendMessage"}]


def test_redactor_leaves_the_shipped_fixture_unchanged(tmp_path):
    out = tmp_path / "again.jsonl"
    result = subprocess.run([sys.executable, "-I", REDACTOR, "--redact-commands", "--neutral-names",
                             FIXTURE, str(out)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == open(FIXTURE, "rb").read()


NEUTRAL_NAME = re.compile(r"^(main|feature-[a-z]+)$")


def test_no_fixture_keeps_a_worktree_or_branch_name():
    """Worktree and branch names carry ticket numbers and work titles; --neutral-names
    maps them to stand-ins in every fixture (gitBranch, Codex git.branch, every cwd)."""
    names = set()
    for name in sorted(os.listdir(os.path.join(HERE, "fixtures"))):
        if not name.endswith(".jsonl"):
            continue
        text = open(os.path.join(HERE, "fixtures", name), encoding="utf-8").read()
        names |= {(name, m) for m in re.findall(r'"(?:gitBranch|branch)": "([^"]*)"', text)}
        names |= {(name, m) for m in re.findall(r'/\.worktrees/([^"/]*)', text)}
    assert names
    assert not [n for n in names if not NEUTRAL_NAME.match(n[1])], sorted(names)


COMMIT_HASH = re.compile(r'"commit_hash"\s*:\s*"[0-9a-fA-F]{40}"')
CODEX_REDACTOR = os.path.join(HERE, "fixtures", "redact_pickup_codex_rollout.py")
CODEX_FIXTURES = sorted(Path(HERE, "fixtures").glob("pickup-codex-*.jsonl"))


def test_no_fixture_keeps_a_commit_hash():
    fixtures = Path(HERE, "fixtures")
    leaked = [str(path.relative_to(fixtures)) for path in sorted(fixtures.rglob("*"))
              if path.suffix in (".json", ".jsonl")
              and COMMIT_HASH.search(path.read_text(encoding="utf-8"))]
    assert not leaked, leaked


@pytest.mark.parametrize("fixture", CODEX_FIXTURES, ids=lambda path: path.name)
def test_codex_redactor_replaces_commit_hash(fixture, tmp_path):
    # Use the captured metadata record; no rollout records are invented.
    first_line = fixture.read_text(encoding="utf-8").splitlines()[0]
    row = json.loads(first_line)
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    row["payload"]["git"]["commit_hash"] = "a" * 40
    src.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", CODEX_REDACTOR, str(src), str(out)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    redacted = json.loads(out.read_text(encoding="utf-8"))
    assert redacted["payload"]["git"] == dict(row["payload"]["git"],
                                             commit_hash="[REDACTED COMMIT HASH]")


def test_sweep_handoff_contains_only_redacted_contract_values():
    data = json.loads((Path(HERE) / 'fixtures/sweep-handoff.json').read_text())
    assert data['subject'] == {'working_directory': '/redacted/repository', 'session_id': 'redacted-session'}
    assert data['git']['branch'] == 'main'
    assert data['git']['head'] == '[REDACTED COMMIT HASH]'
    assert data['uncommitted_files'] == data['spawned_processes'] == []
    for item in data['resume']['open_loops']:
        assert re.fullmatch(r'\[REDACTED ITEM [1-9][0-9]*\]', item['context'])
        assert item.get('session_id', 'redacted-session') == 'redacted-session'
        assert item.get('produced_at', '2026-10-01T00:00:00Z') == '2026-10-01T00:00:00Z'
        assert item.get('anchor', {'ticket': 'https://example.test/ticket'}) == {'ticket': 'https://example.test/ticket'}
