#!/usr/bin/env python3
"""Codex hook adapter. Reach the shared engines through commands, never imports."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MOMENTS = {'post-compact':'SessionStart', 'pre-compact':'PreCompact', 'context-guard':'UserPromptSubmit',
           'ledger-record':'PostToolUse', 'guard-decide':'Stop', 'checklist-nudge':'PostToolUse',
           'actor-guard':'PreToolUse'}


def command(engine, operation, payload):
    return subprocess.run([sys.executable, str(ROOT/'scripts/lib'/engine), operation],
                          input=json.dumps(payload), text=True, capture_output=True)


def emit(event, text):
    print(json.dumps({'hookSpecificOutput': {'hookEventName':event, 'additionalContext':text}}))


def completion_exit_code(payload):
    """Use the real completion for this tool id and command, when recorded.

    Some shell responses contain only stdout. An empty stdout is not proof of
    success; the recorded CommandExecution supplies its actual exit status.
    """
    path = payload.get('transcript_path')
    tool_id = payload.get('tool_use_id')
    cmd = payload.get('tool_input', {}).get('command')
    if not isinstance(path, str) or not tool_id or not isinstance(cmd, str):
        return None
    try:
        with open(path, 'rb') as handle:
            size = os.path.getsize(path)
            if size > 512 * 1024:
                handle.seek(size - 512 * 1024)
                handle.readline()
            lines = handle.read().decode('utf-8', 'replace').splitlines()
        for line in reversed(lines):
            try:
                row = json.loads(line)
                event = row.get('payload', {})
                item = event.get('item', {})
                argv = item.get('command')
                code = item.get('exit_code')
                if (row.get('type') == 'event_msg' and event.get('type') == 'item_completed'
                        and item.get('type') == 'CommandExecution' and item.get('id') == tool_id
                        and isinstance(argv, list) and argv and argv[-1] == cmd
                        and isinstance(code, int) and not isinstance(code, bool)):
                    return code
            except (ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return None


def nudge(payload):
    cmd = payload.get('tool_input', {}).get('command', '')
    response = payload.get('tool_response', {})
    if not isinstance(cmd, str) or not isinstance(response, dict):
        return
    out = response.get('stdout', '') + '\n' + response.get('stderr', '')
    if response.get('interrupted') or response.get('exit_code', 0) != 0:
        return
    signal = ''
    if re.search(r'(^|[^\w])git(?:\s+-[^\s]+\s+[^\s]+)*\s+(commit|push)\b',cmd):
        if not re.search(r'(?im)^(fatal:|error:)|nothing to commit|failed to push', out):
            signal = 'git completion'
    elif re.search(r'pytest|swift\s+test|xcodebuild.*test|(?:npm|yarn|pnpm|bun).*test|jest|vitest|go\s+test|cargo\s+test|rspec|make\s+test|dotnet\s+test|(?:gradle|mvn).*test',cmd):
        passing = re.search(r'(?im)\*\* TEST SUCCEEDED \*\*|\d+ passed|Test Suite.*passed|\bok\b|All tests passed|tests? passed|OK \(',out)
        failing = re.search(r'(?im)\*\* TEST FAILED \*\*|[1-9]\d* failed|Test Suite.*failed|\bFAIL\b|FAILED|✗|❌',out)
        if passing and not failing:
            signal = 'passing tests'
    if not signal and command('checklist.py','is-completion-command',payload).returncode == 0:
        signal = 'slate completion'
    if not signal:
        return
    cadence = command('checklist.py','wrap-cadence',payload)
    if cadence.returncode != 0:
        return
    value = cadence.stdout.strip()
    if value == 'none':
        return
    if value == 'checkpoint':
        if signal == 'git completion':
            emit('PostToolUse','Git completed in an unattended session. Checkpoint now if this finishes a unit of work. Run $checklist once, unattended, after the slate completion command succeeds.')
        return
    if value == 'unattended-checklist':
        text = 'The unattended slate is complete. Run $checklist now, once, unattended: pass --unattended to plan, report, and wrap-check. A step needing an answer reports pending, writes nothing, and the checklist continues.'
    elif signal != 'slate completion':
        text = signal + ' — if this wraps a unit of work, run $checklist before moving on. Reminder fires once per session.'
    else:
        return
    # State stays outside the tool's uninstall area and the git checkout.
    state = Path(os.environ.get('CHECKLIST_STATE_DIR') or os.path.expanduser('~/.local/state/continuity/checklist'))
    state.mkdir(parents=True, exist_ok=True)
    sid = re.sub(r'[^A-Za-z0-9_.-]','_',str(payload.get('session_id') or 'unknown'))
    flag = state/(sid + ('.unattended-nudge' if value == 'unattended-checklist' else '.nudge'))
    try:
        with flag.open('x') as handle:
            handle.write(value+'\n')
    except FileExistsError:
        return
    emit('PostToolUse',text)


def main():
    operation = sys.argv[1]
    if operation not in MOMENTS:
        raise ValueError('unknown hook operation')
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise ValueError('hook payload must be an object')
    os.environ['CONTINUITY_HARNESS'] = 'codex'
    # A hook's session identity wins over an inherited parent thread id.
    os.environ['CODEX_THREAD_ID'] = str(payload.get('session_id') or '')
    if operation == 'actor-guard':
        result = command('checklist.py','actor-guard',payload)
    else:
        if command('handoff.py','is-interactive',payload).returncode != 0:
            return
        response = payload.get('tool_response')
        if isinstance(response, str):
            normalized = {'stdout':response, 'stderr':''}
            observed = completion_exit_code(payload)
            code = re.search(r'Process exited with code (\d+)',response)
            if observed is not None:
                normalized['exit_code'] = observed
            elif code:
                normalized['exit_code'] = int(code.group(1))
            elif re.search(r'(?m)^\[[^\]\n]+ [0-9a-f]{7,40}\]',response):
                # Actual git commit stdout: no success invented for arbitrary output.
                normalized['exit_code'] = 0
            payload['tool_response'] = normalized
        if operation == 'checklist-nudge':
            nudge(payload)
            return
        result = command('handoff.py',operation,payload)
    if result.returncode == 0 and result.stdout.strip():
        output = result.stdout.strip()
        if output.startswith('{'):
            print(output)
        else:
            emit(MOMENTS[operation],output)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, subprocess.SubprocessError) as error:
        print('continuity Codex hook: '+str(error),file=sys.stderr)
    # Advisory failures must never make the harness reject a session.
    sys.exit(0)
