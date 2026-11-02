#!/usr/bin/env python3
"""Build the Codex rollout fixtures for pickup.py (#1453).

Same rule as redact_pickup_transcript.py: never hand-author a rollout.
This starts from a REAL Codex rollout (``$CODEX_HOME/sessions/YYYY/MM/DD/
rollout-<ts>-<thread>.jsonl``) and keeps only the records pickup.py's
Codex normalizer reads, with free-text prose replaced by placeholders:

- session_meta: identity and location only (id, session_id,
  parent_thread_id, cwd, git, timestamp, cli_version, originator, source,
  model_provider, history_mode, history_base). base_instructions (the whole
  rulebook) and every other field are dropped.
- turn_context: cwd and turn_id only.
- response_item message, role user/assistant: text parts redacted, phase
  kept. developer-role messages are dropped. A text that begins with "<"
  (injected <environment_context> and similar) keeps only its opening tag,
  so its structural meaning (is_prompt_noise keys on the leading "<")
  survives without its content. The injected "# AGENTS.md instructions"
  block keeps only its first line for the same reason.
- event_msg item_completed: UserMessage/AgentMessage text redacted;
  CommandExecution keeps id, command, cwd, exit_code, status and a
  truncated aggregated_output (stdout/stderr/formatted_output/parsed_cmd
  are duplicates of it); FileChange keeps each changed path and its change
  type, not the diff or content.
- event_msg task_started (turn_id) and task_complete (turn_id,
  last_agent_message redacted).

Dropped entirely: reasoning, token rows, world_state, custom/function tool
calls and outputs (CommandExecution is the version-stable command source),
thread settings and compaction records.

Command strings pass through untouched, as tool_use input does in the Claude
fixture: ticket-op and file-path extraction read the command text itself.

Usage:
  redact_pickup_codex_rollout.py [--first-turn] [--redact-commands] [--neutral-names] <source.jsonl> <out.jsonl>

--first-turn keeps records only through the first task_complete (a real
prefix of the rollout), used to cut the paginated base/window pair down to
one turn each.

--redact-commands replaces every command string and aggregated_output with a
placeholder, every command cwd with "/redacted", and every FileChange path
with a numbered placeholder path. The
only real paginated thread on the source box is a client-work session, so
its pair keeps structure (identity, ordering, roles, phases, exit codes)
and no command or file content.

--neutral-names replaces each worktree and branch name (a ticket number and a
work title) with a stand-in, as redact_pickup_transcript.py's flag does:
session_meta git.branch and the directory after ``/.worktrees/`` in every kept
cwd. Each distinct name maps to feature-a, feature-b, ... in first-seen order;
trunk names are kept.
"""
import json
import sys

MAX_RESULT_CHARS = 600
AGENTS_PREFIX = "# AGENTS.md instructions"
META_KEYS = ("id", "session_id", "parent_thread_id", "cwd", "git", "timestamp",
             "cli_version", "originator", "source", "model_provider",
             "history_mode", "history_base")
COMMAND_KEYS = ("type", "id", "command", "cwd", "exit_code", "status")


TRUNKS = ("main", "master")


class Counter(object):
    def __init__(self, redact_commands=False, neutral_names=False):
        self.n = 0
        self.redact_commands = redact_commands
        self.neutral_names = neutral_names
        self.names = {}

    def placeholder(self):
        self.n += 1
        return "[REDACTED TEXT #%d]" % self.n


def neutral_name(real, counter):
    if not counter.neutral_names or not isinstance(real, str) or not real or real in TRUNKS:
        return real
    if real not in counter.names:
        n, suffix = len(counter.names), ""
        while True:
            suffix = chr(ord("a") + n % 26) + suffix
            n = n // 26 - 1
            if n < 0:
                break
        counter.names[real] = "feature-" + suffix
    return counter.names[real]


def neutral_path(path, counter):
    if not counter.neutral_names or not isinstance(path, str):
        return path
    head, sep, rest = path.partition("/.worktrees/")
    if not sep:
        return path
    leaf, slash, tail = rest.partition("/")
    return head + sep + neutral_name(leaf, counter) + slash + tail


def _truncate(s):
    return s if len(s) <= MAX_RESULT_CHARS else s[:MAX_RESULT_CHARS] + " ...[TRUNCATED]"


def redact_text(t, counter):
    if not isinstance(t, str) or not t.strip():
        return t
    stripped = t.lstrip()
    if stripped.startswith("<"):
        tag = stripped.split(">", 1)[0] + ">"
        return tag + "[REDACTED]"
    if stripped.startswith(AGENTS_PREFIX):
        return AGENTS_PREFIX + " [REDACTED]"
    return counter.placeholder()


def _redact_parts(parts, counter):
    out = []
    for part in parts or []:
        if isinstance(part, dict) and "text" in part:
            part = {"type": part.get("type"), "text": redact_text(part.get("text"), counter)}
        out.append(part)
    return out


def redact_row(row, counter):
    """Return the redacted row, or None to drop it."""
    kind = row.get("type")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    head = {k: row[k] for k in ("timestamp", "type", "ordinal") if k in row}
    if kind == "session_meta":
        kept = {k: payload[k] for k in META_KEYS if k in payload}
        if "cwd" in kept:
            kept["cwd"] = neutral_path(kept["cwd"], counter)
        if isinstance(kept.get("git"), dict) and "branch" in kept["git"]:
            kept["git"] = dict(kept["git"], branch=neutral_name(kept["git"]["branch"], counter))
        if isinstance(kept.get("git"), dict) and "commit_hash" in kept["git"]:
            kept["git"] = dict(kept["git"], commit_hash="[REDACTED COMMIT HASH]")
        head["payload"] = kept
        return head
    if kind == "turn_context":
        kept = {k: payload[k] for k in ("cwd", "turn_id") if k in payload}
        if "cwd" in kept:
            kept["cwd"] = neutral_path(kept["cwd"], counter)
        head["payload"] = kept
        return head
    if kind == "response_item":
        if payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
            return None
        kept = {k: payload[k] for k in ("type", "role", "phase", "id") if k in payload}
        kept["content"] = _redact_parts(payload.get("content"), counter)
        head["payload"] = kept
        return head
    if kind != "event_msg":
        return None
    etype = payload.get("type")
    if etype == "task_started":
        head["payload"] = {k: payload[k] for k in ("type", "turn_id") if k in payload}
        return head
    if etype == "task_complete":
        kept = {k: payload[k] for k in ("type", "turn_id") if k in payload}
        kept["last_agent_message"] = redact_text(payload.get("last_agent_message"), counter)
        head["payload"] = kept
        return head
    if etype == "user_message":
        head["payload"] = {"type": etype, "message": redact_text(payload.get("message"), counter)}
        return head
    if etype != "item_completed" or not isinstance(payload.get("item"), dict):
        return None
    item = payload["item"]
    itype = item.get("type")
    if itype in ("UserMessage", "AgentMessage"):
        kept = {k: item[k] for k in ("type", "id", "phase") if k in item}
        kept["content"] = _redact_parts(item.get("content"), counter)
    elif itype == "CommandExecution":
        kept = {k: item[k] for k in COMMAND_KEYS if k in item}
        kept["aggregated_output"] = _truncate(item.get("aggregated_output") or "")
        if counter.redact_commands:
            command = list(kept.get("command") or [])
            if command:
                command[-1] = counter.placeholder()
            kept["command"] = command
            kept["aggregated_output"] = counter.placeholder()
            if "cwd" in kept:
                kept["cwd"] = "/redacted"
        elif "cwd" in kept:
            kept["cwd"] = neutral_path(kept["cwd"], counter)
    elif itype == "FileChange":
        changes = {}
        for path, change in (item.get("changes") or {}).items():
            if counter.redact_commands:
                path = "/redacted/%s" % counter.placeholder()
            changes[path] = {"type": (change or {}).get("type")}
        kept = {"type": itype, "id": item.get("id"), "changes": changes}
    else:
        return None
    head["payload"] = {"type": etype, "item": kept}
    return head


def main(argv):
    first_turn = "--first-turn" in argv
    redact_commands = "--redact-commands" in argv
    flags = ("--first-turn", "--redact-commands", "--neutral-names")
    src, dst = [a for a in argv if a not in flags]
    counter = Counter(redact_commands, "--neutral-names" in argv)
    kept = 0
    with open(src) as f, open(dst, "w") as g:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out = redact_row(row, counter)
            if out is not None:
                g.write(json.dumps(out) + "\n")
                kept += 1
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if first_turn and row.get("type") == "event_msg" and payload.get("type") == "task_complete":
                break
    print("kept %d rows, redacted %d text blocks" % (kept, counter.n), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
