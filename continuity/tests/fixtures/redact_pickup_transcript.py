#!/usr/bin/env python3
"""Build tests/fixtures/pickup-session.jsonl for #910's pytest suite.

example-config#910 / repo rule: never hand-author a .jsonl with invented
field shapes. This starts from a REAL Claude Code transcript and redacts
only the free-text prose (user/assistant "text" content blocks) that isn't
needed to exercise pickup.py's logic. Everything the extraction code
actually reads is left INTACT:

- stop_reason, isSidechain, isMeta, cwd, gitBranch, timestamp — every
  structural field the message-capture and branch-scan logic keys on.
- tool_use blocks in full, including `input` (Bash commands, file_path
  fields) — A5a (ticket ops) and A6 (transcript-scraped file paths) read
  the command strings themselves, not the surrounding prose.
- tool_result content, up to a length cap — A5a's created-ticket-number
  recovery greps a `record-cli issue create` result for its issue URL, which is
  always near the start of a short stdout. Long results (file dumps, `record-cli
  issue view --comments`) are truncated; nothing that recovery logic reads
  is in the truncated tail.

Row types irrelevant to the directory lens (attachment/mode/atis-latch/
bridge-session/last-prompt/ai-title/system/file-history-*/queue-operation)
are dropped entirely — pickup.py never reads them, and cutting them
took this fixture from ~2.9MB to a fraction of that.

Usage: redact_pickup_transcript.py [--redact-commands] [--neutral-names] <source.jsonl> <out.jsonl>

--redact-commands (the shipped package's fixture) additionally removes every
command, tool result, and thinking block, the way the Codex rollout script's
flag does. The source is a private session, so the copy keeps structure
(identity, ordering, roles, stop reasons, tool names and ids, error flags) and
no command, output, or file content:

- thinking blocks are dropped; a row left with no content keeps an empty list.
- tool_use input: Bash/Monitor ``command`` and every other free-text value is a
  placeholder; ``file_path`` becomes a numbered placeholder path.
- tool_result content is a placeholder, and the row's ``toolUseResult`` (the
  raw stdout/stderr duplicate of it) is dropped.
- injected ``<...>`` markup keeps its opening tag only, as in the Codex script.
- a claude.ai session URL anywhere in the row is a placeholder.

--neutral-names (also the shipped package's fixture) replaces each worktree and
branch name, which carries a ticket number and a work title, with a stand-in:
``gitBranch`` and the directory after ``/.worktrees/`` in ``cwd``. Each distinct
name maps to feature-a, feature-b, ... in first-seen order through one table, so
a worktree and its branch keep sharing a name. Trunk names are kept. A second run
over the output maps every stand-in to itself.
"""
import json
import re
import sys

MAX_RESULT_CHARS = 600
KEEP_TYPES = ("user", "assistant")


def _redact_text_part(part, counter):
    t = part.get("text", "")
    if t.strip():
        counter[0] += 1
        part = dict(part)
        part["text"] = "[REDACTED TEXT #%d]" % counter[0]
    return part


SESSION_URL = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9]+")
PATH_KEYS = ("file_path", "path", "notebook_path")
KEEP_INPUT_KEYS = ("type", "subagent_type", "model", "run_in_background", "persistent", "timeout_ms",
                   "max_results")


def _placeholder(counter):
    """Numbered apart from the prose placeholders, whose numbers the tests pin."""
    counter[1] += 1
    return "[REDACTED CONTENT #%d]" % counter[1]


def _redact_input(value, counter):
    """tool_use ``input`` with no command or content text left in it."""
    out = {}
    for key, val in value.items():
        if key in PATH_KEYS and isinstance(val, str):
            out[key] = "/redacted/%s" % _placeholder(counter)
        elif key in KEEP_INPUT_KEYS and not isinstance(val, (dict, list)):
            out[key] = val
        elif isinstance(val, str):
            out[key] = _placeholder(counter) if val.strip() else val
        elif isinstance(val, (dict, list)):
            out[key] = _placeholder(counter)
        else:
            out[key] = val
    return out


def _redact_result_command(part, counter):
    part = dict(part)
    c = part.get("content")
    if isinstance(c, str):
        part["content"] = _placeholder(counter) if c.strip() else c
    elif isinstance(c, list):
        new_c = []
        for cp in c:
            if isinstance(cp, dict) and "text" in cp:
                cp = dict(cp)
                cp["text"] = _placeholder(counter)
            elif isinstance(cp, dict):
                # image, document, or any other block: its payload can be a
                # base64 screenshot or file. Keep the type and tool name only.
                cp = {k: v for k, v in cp.items() if k in ("type", "tool_name")}
            else:
                cp = _placeholder(counter)
            new_c.append(cp)
        part["content"] = new_c
    return part


def _strip_session_urls(value, counter):
    if isinstance(value, str):
        return SESSION_URL.sub(lambda m: _placeholder(counter), value)
    if isinstance(value, list):
        return [_strip_session_urls(v, counter) for v in value]
    if isinstance(value, dict):
        return {k: _strip_session_urls(v, counter) for k, v in value.items()}
    return value


TRUNKS = ("main", "master")


class NeutralNames(object):
    def __init__(self):
        self.names = {}

    def name(self, real):
        if not isinstance(real, str) or not real or real in TRUNKS:
            return real
        if real not in self.names:
            n, suffix = len(self.names), ""
            while True:
                suffix = chr(ord("a") + n % 26) + suffix
                n = n // 26 - 1
                if n < 0:
                    break
            self.names[real] = "feature-" + suffix
        return self.names[real]

    def path(self, path):
        if not isinstance(path, str):
            return path
        head, sep, rest = path.partition("/.worktrees/")
        if not sep:
            return path
        leaf, slash, tail = rest.partition("/")
        return head + sep + self.name(leaf) + slash + tail


def _truncate(s):
    return s if len(s) <= MAX_RESULT_CHARS else s[:MAX_RESULT_CHARS] + " ...[TRUNCATED]"


def _redact_tool_result(part):
    part = dict(part)
    c = part.get("content")
    if isinstance(c, str):
        part["content"] = _truncate(c)
    elif isinstance(c, list):
        new_c = []
        for cp in c:
            if isinstance(cp, dict) and cp.get("type") == "text":
                cp = dict(cp)
                cp["text"] = _truncate(cp.get("text", ""))
            new_c.append(cp)
        part["content"] = new_c
    return part


def redact_content(content, counter, redact_commands=False):
    if isinstance(content, str):
        # command-name/system markers ("<command-name>...") and empty
        # strings carry no prose to leak and are structurally meaningful
        # (is_prompt_noise() keys on the leading "<") — leave them as-is.
        if not content.strip():
            return content
        if content.lstrip().startswith("<"):
            if not redact_commands:
                return content
            # Injected markup (task notifications carry tool output): keep the
            # opening tag, which is_prompt_noise() keys on, and nothing inside.
            return content.lstrip().split(">", 1)[0] + ">[REDACTED]"
        counter[0] += 1
        return "[REDACTED TEXT #%d]" % counter[0]
    if isinstance(content, list):
        out = []
        for p in content:
            if not isinstance(p, dict):
                out.append(p)
                continue
            ptype = p.get("type")
            if redact_commands and ptype == "thinking":
                continue
            if redact_commands and ptype == "tool_use":
                p = dict(p)
                p["input"] = _redact_input(p.get("input") or {}, counter)
                out.append(p)
            elif redact_commands and ptype == "tool_result":
                out.append(_redact_result_command(p, counter))
            elif ptype == "text":
                out.append(_redact_text_part(p, counter))
            elif ptype == "tool_result":
                out.append(_redact_tool_result(p))
            else:
                # tool_use (and anything else) passes through untouched.
                out.append(p)
        return out
    return content


def main(argv):
    redact_commands = "--redact-commands" in argv
    names = NeutralNames() if "--neutral-names" in argv else None
    src, dst = [a for a in argv if a not in ("--redact-commands", "--neutral-names")]
    counter = [0, 0]
    kept = 0
    with open(src) as f, open(dst, "w") as g:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("type") not in KEEP_TYPES:
                continue
            msg = row.get("message")
            if isinstance(msg, dict) and "content" in msg:
                row = dict(row)
                msg = dict(msg)
                msg["content"] = redact_content(msg["content"], counter, redact_commands)
                row["message"] = msg
            if redact_commands:
                row = {k: v for k, v in row.items() if k != "toolUseResult"}
                row = _strip_session_urls(row, counter)
            if names is not None:
                row = dict(row)
                if "cwd" in row:
                    row["cwd"] = names.path(row["cwd"])
                if "gitBranch" in row:
                    row["gitBranch"] = names.name(row["gitBranch"])
            g.write(json.dumps(row) + "\n")
            kept += 1
    print("kept %d rows, redacted %d text blocks, %d other values" % (kept, counter[0], counter[1]),
          file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
