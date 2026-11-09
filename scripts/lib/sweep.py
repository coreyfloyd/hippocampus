#!/usr/bin/env python3
"""Identity-bound sweep planning, open-session protection and safe act execution."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import socket
import shlex
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
handoff = load_module('sweep_handoff', HERE / 'handoff.py')
checklist = load_module('sweep_checklist', HERE / 'checklist.py')
pickup = load_module('sweep_pickup', HERE.parent.parent / 'skills/pickup/scripts/pickup.py')
SECTIONS = (
    ('asks_raised', 'Asks raised'),
    ('open_sessions', 'Open sessions with idle time'),
    ('new_tickets', 'New tickets with priority'),
    ('comments_added', 'Comments added'),
    ('documents_changed', 'Documents changed'),
    ('items_dropped', 'Items dropped with reasons'),
    ('worktrees_removed', 'Worktrees removed'),
    ('handoffs_archived', 'Handoffs archived'),
)
# Present only with the auto-apply setting on, so a report with it off is unchanged.
APPLY_SECTIONS = (
    ('would_apply', 'Would apply'),
    ('lessons_applied', 'Lessons applied'),
    ('lessons_not_pushed', 'Lesson commits not pushed'),
    ('knowledge_captured', 'Knowledge captured'),
    ('already_settled', 'Already settled'),
)
APPLY_OPERATIONS = {'lessons': 'apply_lesson', 'knowledge': 'apply_knowledge'}
ITEM_TYPES = {'lessons': 'lesson', 'knowledge': 'knowledge'}
DELIVERED = ('pushed', checklist.lessons.PULL_REQUEST)
OPEN_SESSION = 'session is open or active again'
LESSON_FIELDS = ('target', 'change', 'added', 'evidence', 'commit', 'checkout', 'branch', 'delivery', 'attempts',
                 'default_branch', 'note', 'lesson_branch', 'local_commit', 'pull_request', 'surfaces')


def settings():
    config = handoff.read_config().get('sweep', {})
    if not isinstance(config, dict):
        raise ValueError('sweep configuration must be an object')
    result = dict(mode='watch-only', idle_days=2, open_session_checks=[],
                  new_ticket_limit=10, report_location=str(Path(handoff.state_dir()).parent / 'sweep-reports'),
                  archive_retention_days=None, binding_timeout_seconds=30)
    result.update(config)
    if result['mode'] not in ('watch-only', 'act'):
        raise ValueError('sweep.mode must be watch-only or act')
    for key in ('idle_days', 'new_ticket_limit', 'archive_retention_days', 'binding_timeout_seconds'):
        value = result[key]
        if key == 'archive_retention_days' and value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f'sweep.{key} must be a non-negative finite number')
    if result['binding_timeout_seconds'] <= 0:
        raise ValueError('sweep.binding_timeout_seconds must be positive')
    if type(result['new_ticket_limit']) is not int:
        raise ValueError('sweep.new_ticket_limit must be an integer')
    checks = result['open_session_checks']
    if not isinstance(checks, list) or not all(isinstance(c, str) and c.strip() for c in checks):
        raise ValueError('sweep.open_session_checks must be a list of non-empty command strings')
    if not isinstance(result['report_location'], str) or not result['report_location'].strip():
        raise ValueError('sweep.report_location must be a non-empty directory path')
    return result


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be an ISO timestamp with timezone')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed.timestamp()


def item_identity(item, data, path):
    """Legacy provenance falls back to its source, never to its item position."""
    subject = data.get('subject', {})
    return {'session_id': item.get('session_id') or subject.get('session_id') or data.get('session_id') or path.stem,
            'produced_at': item.get('produced_at') or data.get('written_at') or
                           datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            'text': item.get('context', '')}


def identity_key(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def subjects(data):
    subject = data.get('subject', {})
    if not isinstance(subject, dict):
        raise ValueError('subject must be an object')
    directory = subject.get('working_directory') or data.get('working_directory') or data.get('cwd')
    if directory and not isinstance(directory, str):
        raise ValueError('working directory must be a string')
    return directory, subject.get('session_id') or data.get('session_id')


def transcript_index(home, codex_home):
    """Reuse pickup's store traversal and both providers' transcript locations."""
    found = {}
    root = pickup.claude_store(home)
    for name in sorted(pickup.list_store_dir(root, 'Claude projects directory') or []):
        project = Path(root) / name
        if project.is_symlink():
            raise ValueError(f'Claude project directory is a symbolic link: {project}')
        if not project.is_dir():
            continue
        for name in pickup.claude_project_transcripts(str(project)) or []:
            path = project / name
            found.setdefault(path.stem, []).append(path)
    for path, session in pickup.codex_rollouts(codex_home):
        found.setdefault(session, []).append(Path(path))
    return found


def read_handoff_source(path):
    """Capture bytes and file identity from one stable read, without rewriting."""
    if path.is_symlink():
        raise ValueError('handoff is a symbolic link; left in place')
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    with path.open('rb') as handle:
        before = os.fstat(handle.fileno())
        content = handle.read()
        after = os.fstat(handle.fileno())
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ValueError('handoff changed while reading; left in place')
    return content, {'sha256': hashlib.sha256(content).hexdigest(),
                     **{field: getattr(after, field) for field in fields}}


def check_handoff_source(candidate):
    """Equal JSON is insufficient: any byte or file-identity change keeps it."""
    _, current = read_handoff_source(Path(candidate['path']))
    if current != candidate['source_snapshot']:
        raise ValueError('handoff changed since discovery')


# Only these approved lint messages are non-blocking for sweep. Full matches
# deliberately keep any new lint rule blocking, even within the same field.
WARN_ONLY_LINT = (
    r'spawned_processes must be an array',
    r'spawned_processes\[\d+\] not an object',
    r'spawned_processes\[\d+\] missing pid\+started_at — identity reconcile \(F4\) is impossible without both; kill -0 alone can hit a stranger',
    r'open_loops\[\d+\]\.context is \d+ chars — that reads like durable progress; put it in the record and leave a pointer here',
    r'open_loops\[\d+\] has no anchor \(ticket\|project\) and no disposition — an un-anchored loop MUST say where it will be filed',
)


def discover(scope, config, now):
    store = Path(handoff.state_dir()).resolve()
    scoped = None if scope == 'all' else handoff.canonical_subject(scope)
    repo = handoff.repository_root(scoped) if scoped else None
    result = {'scope': scope if scoped is None else scoped, 'candidates': [], 'errors': []}
    try:
        transcripts = transcript_index(os.path.expanduser('~'),
                                       os.path.expanduser(os.environ.get('CODEX_HOME', '~/.codex')))
    except (OSError, ValueError, pickup.SourceError) as exc:
        result['errors'].append({'path': 'transcript stores', 'reason': str(exc), 'blocks_sweep': True})
        return result
    if not store.exists():
        return result
    for path in sorted(store.glob('*.json')):
        try:
            source_bytes, source_snapshot = read_handoff_source(path)
            data = json.loads(source_bytes)
            # Scope identifiable sources before lint so unrelated repositories'
            # contract failures do not leak into a directory-scoped report.
            if scoped and isinstance(data, dict):
                subject = data.get('subject')
                subject = subject if isinstance(subject, dict) else {}
                directory = subject.get('working_directory') or data.get('working_directory') or data.get('cwd')
                if isinstance(directory, str) and directory:
                    directory = handoff.canonical_subject(directory)
                    git = data.get('git')
                    git = git if isinstance(git, dict) else {}
                    stored_repo = git.get('repository_root')
                    actual_repo = handoff.repository_root(directory)
                    source_repo = actual_repo or (handoff.canonical_subject(stored_repo)
                        if isinstance(stored_repo, str) and stored_repo else None)
                    if not ((repo and source_repo == repo) or (not repo and directory == scoped)):
                        continue
            errors, warnings = handoff.lint_data(data)
            blocking = []
            for error in errors:
                if any(re.fullmatch(pattern, error) for pattern in WARN_ONLY_LINT):
                    warnings.append(error)
                else:
                    blocking.append(error)
            if blocking:
                raise ValueError('; '.join(blocking))
            directory, session = subjects(data)
            # v1 did not require a subject. Keep it decidable in all scope,
            # but never guess that an unidentified directory matches a scope.
            if scoped and not directory:
                raise ValueError('legacy handoff has no directory; cannot assign directory scope')
            if directory:
                directory = handoff.canonical_subject(directory)
            activity = path.stat().st_mtime
            if data.get('written_at'):
                activity = max(activity, timestamp(data['written_at']))
            for transcript in transcripts.get(session, []):
                activity = max(activity, transcript.stat().st_mtime)
            idle = max(0, now.timestamp() - activity)
            items = [{'item': item, 'identity': item_identity(item, data, path)}
                     for item in data.get('resume', {}).get('open_loops', [])]
            occurrences = Counter(identity_key(item['identity']) for item in items)
            for item in items:
                item['identity_occurrences'] = occurrences[identity_key(item['identity'])]
            result['candidates'].append({'path': str(path), 'directory': directory or 'unknown directory',
                'session_id': session or path.stem, 'activity_at': activity, 'idle_seconds': idle,
                'abandoned': idle > config['idle_days'] * 86400,
                'items': items, 'handoff': data, 'source_snapshot': source_snapshot, 'warnings': warnings})
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            result['errors'].append({'path': str(path), 'reason': str(exc)})
    return result


@contextmanager
def store_lock():
    """Lock a directory inode: no lock file or state directory is written.

    An absent store locks its nearest existing ancestor. This can conservatively
    serialize two empty stores but still changes nothing outside the report.
    """
    path = Path(handoff.state_dir()).resolve()
    while not path.exists():
        path = path.parent
    fd = os.open(path, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('a sweep is already running over this handoff store') from exc
        yield
    finally:
        os.close(fd)


def read_open_sessions(path):
    if path is None:
        return {'session_ids': [], 'method': 'idle threshold alone; no checks configured'}
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or not isinstance(data.get('session_ids'), list)
            or not all(isinstance(s, str) and s for s in data['session_ids'])
            or not isinstance(data.get('method'), str) or not data['method'].strip()):
        raise ValueError('open-session evidence requires session_ids and a non-empty method')
    return data


def open_session_checks(config, evidence):
    """Union successful checks; any failure protects the entire scope."""
    result = dict(evidence, results=[], failed=False)
    sessions = set(result['session_ids'])
    for command in config['open_session_checks']:
        row = {'command': command, 'session_ids': []}
        try:
            done = subprocess.run(shlex.split(command), capture_output=True, text=True,
                                  timeout=config['binding_timeout_seconds'])
            if done.returncode:
                raise ValueError(done.stderr.strip() or f'check exited {done.returncode}')
            row.update(outcome='ok', session_ids=done.stdout.split())
            sessions.update(row['session_ids'])
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            row.update(outcome='failed', error=str(exc))
            result['failed'] = True
        result['results'].append(row)
    result['session_ids'] = sorted(sessions)
    if config['open_session_checks']:
        result['method'] = 'configured commands' + (' and ' + evidence['method'] if evidence['method'] != 'idle threshold alone; no checks configured' else '')
    return result


def ask_history_path(config):
    return Path(config['report_location']).expanduser().resolve() / 'open-session-asks.json'


def read_ask_history(config):
    path = ask_history_path(config)
    if path.is_symlink():
        raise ValueError('open-session ask history is a symbolic link')
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not all(isinstance(v, (int, float)) for v in data.values()):
        raise ValueError('malformed open-session ask history')
    return data


def save_ask_history(config, history):
    path = ask_history_path(config)
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as handle:
            json.dump(history, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_decisions(path, discovery):
    rows = [] if path is None else json.loads(path.read_text())
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('decisions must be an array of objects')
    allowed = {(c['path'], identity_key(i['identity'])): i['identity_occurrences']
               for c in discovery['candidates'] for i in c['items']}
    result = {}
    for row in rows:
        key = (row.get('handoff'), identity_key(row.get('identity')))
        if key not in allowed:
            raise ValueError('stale or unknown decision identity; inspect again')
        if allowed[key] > 1:
            # No decision can select one copy without extending the identity.
            # Report every ambiguous copy, regardless of supplied judgments.
            continue
        if key in result:
            raise ValueError('duplicate decision for unique item identity; inspect again')
        result[key] = row
    return result


def plan_item(candidate, item, decision, plan, ask):
    base = dict(identity=item['identity'], source_handoff=candidate['path'], item=item['item'])
    occurrences = item['identity_occurrences']
    if occurrences > 1:
        return dict(base, rule=None, outcome='ambiguous identity', identity_occurrences=occurrences,
                    reason=f'Identity occurs {occurrences} times in this handoff; kept for manual judgment; '
                           'no filing decision applied')
    if decision is None:
        return dict(base, rule=None, outcome='pending judgment', reason='No agent filing decision supplied')
    row = {k: v for k, v in decision.items() if k not in ('handoff', 'identity')}
    rule = row.get('rule')
    row.update(index=0, status='dropped' if rule in ('R1', 'R6') else 'filed')
    validation_item = item['item']
    if rule == 'R4' and 'type' not in validation_item and row.get('destination') in ('lessons', 'knowledge'):
        # The agent's chosen slot classifies a legacy item for the shared
        # validator. Preserve the original item and identity in the report.
        validation_item = dict(validation_item, type='lesson' if row['destination'] == 'lessons' else 'knowledge')
    # Reuse the wrap's validation, binding resolution, read failure handling and
    # ask payload. It only does bookkeeping; no binding command is ever invoked.
    single = dict(candidate['handoff'], subject={'working_directory': candidate['directory'],
                  'session_id': candidate['session_id']}, resume={'open_loops': [validation_item]})
    checked = checklist.file_items(plan, single, [row], ask, execute_writes=False)['filing']['items'][0]
    if checked.get('binding') in checklist.record_write.KINDS:
        writes = next(step for step in plan if step['id'] == 'record')['record_writes']
        binding = writes.get(checked['binding'])
        if binding:
            # Keep the selected command with its receipt for user-started undo.
            checked['command'] = binding['command']
    checked.pop('index', None)
    if 'ask' in checked:
        checked['ask']['identity'] = item['identity']
    status = checked.pop('status')
    if checked.get('native_step') in checklist.NATIVE and checked.get('ask_status') == 'filed':
        # Validation used a hypothetical ask receipt; the driving agent must still deliver it.
        checked.update(ask_status='planned', reason='Native capture pending; deliver ask')
        status = 'filed'
    return dict(base, **{k: v for k, v in checked.items() if k != 'item'},
                outcome=('carried' if checked.get('binding') in checklist.NATIVE else 'dry run')
                if status in ('filed', 'dropped') else status)


def git_read(directory, *args):
    done = subprocess.run(['git', '-C', directory, *args], capture_output=True, text=True,
                          env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def worktree_protection(discovery, report, checks, act=False):
    """Gather every source's veto before planning any shared-path removal."""
    retained = {row['path'] for section in report['directories'].values()
                for row in section['handoffs_kept']} if not act else set()
    if act:
        for section in report['directories'].values():
            for row in section['filing_outcomes'] + section['asks_raised']:
                if row['outcome'] not in ('written', 'already_written', 'dropped'):
                    retained.add(row['source_handoff'])
    protected = {}
    for candidate in discovery['candidates']:
        reasons = protected.setdefault(candidate['directory'], set())
        if not candidate['abandoned'] or candidate['session_id'] in checks['session_ids']:
            reasons.add('another open or active session uses this worktree')
        if candidate['handoff'].get('uncommitted_files'):
            reasons.add('handoff lists uncommitted files: ' + candidate['path'])
        if candidate['path'] in retained:
            reasons.add('handoff is kept: ' + candidate['path'])
        if candidate.get('worktree_retention_reason'):
            reasons.add(candidate['worktree_retention_reason'])
    return {directory: '; '.join(sorted(reasons)) for directory, reasons in protected.items() if reasons}


def worktree_plan(candidate, protected):
    """Read-only eligibility checks, repeated immediately before plain removal."""
    # repository_root identifies the shared repository, not this checkout.
    # A subdirectory subject must resolve to its containing linked worktree.
    code, root, _ = git_read(candidate['directory'], 'rev-parse', '--show-toplevel')
    if code or not root:
        return None
    directory = handoff.canonical_subject(root)
    code, output, error = git_read(directory, 'worktree', 'list', '--porcelain')
    if code:
        return {'path': directory, 'outcome': 'kept', 'reason': error or 'worktree lookup failed'}
    entries = [dict(line.split(' ', 1) if ' ' in line else (line, '')
                    for line in block.splitlines()) for block in output.split('\n\n')]
    match = next((e for e in entries if e.get('worktree') == directory), None)
    if not match or directory == entries[0].get('worktree'):
        return None  # never propose removing the main checkout
    row = {'path': directory, 'branch': match.get('branch', '').removeprefix('refs/heads/'),
           'commit': match.get('HEAD'), 'outcome': 'dry run'}
    reason = None
    # Subjects are canonical directories, but an active subject may be below
    # this worktree root. Compare path components, not string prefixes.
    reasons = {why for active, why in protected.items()
               if Path(directory) == Path(active) or Path(directory) in Path(active).parents}
    if reasons:
        reason = '; '.join(sorted(reasons))
    status, dirty, error = git_read(directory, 'status', '--porcelain', '--untracked-files=all')
    if status or dirty:
        reason = error or 'uncommitted or untracked changes'
    code, trunk, _ = git_read(directory, 'symbolic-ref', 'refs/remotes/origin/HEAD')
    if code:
        # A bare origin may have no symbolic remote HEAD; require an existing
        # conventional remote trunk rather than guessing a local branch.
        trunk = next((ref for ref in ('refs/remotes/origin/main', 'refs/remotes/origin/master')
                      if git_read(directory, 'rev-parse', '--verify', ref)[0] == 0), '')
    merged = bool(trunk) and git_read(directory, 'merge-base', '--is-ancestor', row['commit'], trunk)[0] == 0
    if not merged:
        reason = 'branch not contained in the locally observed pushed trunk'
    if not row['branch']:
        reason = 'detached worktree has no local branch'
    if candidate['handoff'].get('uncommitted_files'):
        reason = 'handoff lists uncommitted files'
    if sum(e.get('branch') == match.get('branch') for e in entries) > 1:
        reason = 'local branch is used by another worktree'
    row['checks'] = {'clean': status == 0 and not dirty, 'contained_in_pushed_trunk': merged,
                     'plain_removal': 'not attempted in watch-only mode'}
    if reason:
        row.update(outcome='kept', reason=reason)
    return row


def archive_worktree_check(candidate):
    """Archive needs a clean repository even when no removal is proposed."""
    directory = candidate['directory']
    previous = candidate.get('archive_worktree_check') or {}
    root = (handoff.repository_root(directory) or previous.get('path') or
            candidate['handoff'].get('git', {}).get('repository_root'))
    if not root:
        return None
    code, output, error = git_read(directory, 'status', '--porcelain', '--untracked-files=all')
    return {'path': root, 'clean': code == 0 and not output,
            'reason': (error or 'worktree status read failed') if code else
                      ('uncommitted or untracked changes' if output else 'worktree is clean')}


def add_ask(section, candidate, text, choices, reason, ask):
    identity = {'session_id': candidate['session_id'],
                'produced_at': datetime.fromtimestamp(candidate['activity_at'], timezone.utc).isoformat(),
                'text': text}
    section['asks_raised'].append({'rule': 'R3', 'outcome': 'dry run' if ask else 'unbound', 'reason': reason,
        'source_handoff': candidate['path'], 'identity': identity, 'ask': {'text': text, 'identity': identity, 'session_id': candidate['session_id'],
        'directory': candidate['directory'], 'ticket': None, 'choices': choices}})


def build_report(discovery, decisions, plan, ask, checks, interactive, started, history=None, auto_apply=None):
    report = {'run_id': uuid.uuid4().hex, 'host': socket.gethostname(), 'started_at': started.isoformat(),
              'scope': discovery['scope'], 'mode': 'watch-only', 'interactive': interactive,
              'open_session_checks': [checks], 'errors': discovery['errors'], 'directories': {}}
    if auto_apply:
        report['auto_apply'] = auto_apply
    # Read once, in both modes, so watch-only lists what act mode would skip as already settled.
    indexes = ({binding: ledger_index(kind, report['errors']) for binding, kind in ITEM_TYPES.items()}
               if auto_apply else {})
    asked_sessions = set()
    for candidate in discovery['candidates']:
        is_open = candidate['session_id'] in checks['session_ids']
        if not candidate['abandoned'] and not is_open and not checks.get('failed'):
            continue
        section = report['directories'].setdefault(candidate['directory'],
            {**{key: [] for key, _ in SECTIONS}, **{key: [] for key, _ in APPLY_SECTIONS if auto_apply},
             'filing_outcomes': [], 'worktrees_kept': [], 'handoffs_kept': [], 'handoff_warnings': []})
        if candidate.get('warnings'):
            section['handoff_warnings'].append({'path': candidate['path'], 'warnings': candidate['warnings']})
        if is_open:
            section['open_sessions'].append({key: candidate[key] for key in
                                            ('session_id', 'idle_seconds', 'activity_at', 'path')})
            if (candidate['idle_seconds'] > discovery['idle_days'] * 86400
                    and (history or {}).get(candidate['session_id'], -1) < candidate['activity_at']
                    and candidate['session_id'] not in asked_sessions):
                add_ask(section, candidate, 'Open idle session: ' + candidate['session_id'],
                        ['wrap it', 'leave it', 'close it'],
                        'present directly to user' if interactive else 'would raise an ask; no ask sent in watch-only', ask)
                asked_sessions.add(candidate['session_id'])
                section['asks_raised'][-1].update(open_session=True, activity_at=candidate['activity_at'])
                section['asks_raised'][-1]['ask']['activity_at'] = candidate['activity_at']
            continue
        if not candidate['abandoned']:
            section['handoffs_kept'].append(dict(path=candidate['path'], outcome='kept',
                reason='open-session check failed; abandonment unknown'))
            continue
        outcomes = []
        for item in candidate['items']:
            decision = decisions.get((candidate['path'], identity_key(item['identity'])))
            try:
                row = plan_item(candidate, item, decision, plan, ask)
            except Exception as exc:
                # One item's validation or planning failure must not hide the
                # run. Keep its source and continue reporting the other items.
                row = dict(identity=item['identity'], source_handoff=candidate['path'], item=item['item'],
                           rule=decision.get('rule') if decision else None,
                           destination=decision.get('destination') if decision else None,
                           outcome='failed', error=f'{type(exc).__name__}: {exc}')
            outcomes.append(row)
            section['filing_outcomes'].append(row)
            binding = row.get('binding')
            if auto_apply and binding in APPLY_OPERATIONS and row['outcome'] == 'carried':
                if auto_apply[binding] == 'apply':
                    plan_apply(section, row, candidate['session_id'], indexes[binding])
                else:
                    row['reason'] = auto_apply['reason']
            if binding == 'ask':
                section['asks_raised'].append(row)
            elif row.get('rule') in ('R1', 'R6') and row['outcome'] == 'dry run':
                section['items_dropped'].append(row)
            elif row.get('rule') in ('R2', 'R5', 'R7') and row['outcome'] in ('dry run', 'unbound'):
                key = {'R2': 'comments_added', 'R5': 'new_tickets', 'R7': 'documents_changed'}[row['rule']]
                section[key].append(row)
        dirty = candidate['handoff'].get('uncommitted_files', [])
        if dirty:
            add_ask(section, candidate, 'Uncommitted files for session ' + candidate['session_id'] +
                    ' in ' + candidate['directory'] + ': ' + ', '.join(dirty),
                    ['keep work', 'review files'], 'handoff lists uncommitted files', ask)
        clean_check = archive_worktree_check(candidate)
        candidate['archive_worktree_check'] = clean_check
        archive = (not dirty and (clean_check is None or clean_check['clean']) and
                   not any(row.get('native_step') in checklist.NATIVE for row in outcomes) and
                   all(row['outcome'] == 'dry run' or
                       (row.get('already_settled') and row['outcome'] in ('already_written', 'dropped'))
                       for row in outcomes))
        key = 'handoffs_archived' if archive else 'handoffs_kept'
        section[key].append({'path': candidate['path'], 'outcome': 'dry run' if archive else 'kept',
            'worktree_check': clean_check,
            'destination': str(Path(candidate['path']).parent / 'archive' / Path(candidate['path']).name),
            'reason': 'all items would be filed or dropped' if archive else 'unfiled items, unbound ask, or uncommitted files'})
    protected = worktree_protection(discovery, report, checks)
    for candidate in discovery['candidates']:
        if not candidate['abandoned']:
            continue
        section = report['directories'][candidate['directory']]
        worktree = worktree_plan(candidate, protected)
        if worktree:
            if worktree['outcome'] == 'dry run':
                if worktree not in section['worktrees_removed']:
                    section['worktrees_removed'].append(worktree)
            else:
                section['worktrees_kept'].append(worktree)
                add_ask(section, candidate, 'Keep worktree ' + worktree['path'] + ': ' + worktree['reason'],
                        ['review worktree', 'leave it'], worktree['reason'], ask)
                section['asks_raised'][-1]['worktree'] = True
                if ask is None:
                    for row in list(section['handoffs_archived']):
                        if row['path'] == candidate['path']:
                            section['handoffs_archived'].remove(row)
                            row.update(outcome='kept', reason='unbound worktree ask')
                            section['handoffs_kept'].append(row)
    report['nothing_to_do'] = not report['directories'] and not report['errors']
    report['ended_at'] = datetime.now(timezone.utc).isoformat()
    return report


def pending_path():
    store = Path(handoff.state_dir()).resolve()
    return store.parent / ('.' + store.name + '.sweep-pending.json')


def require_idle():
    if pending_path().exists() or pending_path().is_symlink():
        raise RuntimeError('sweep already running: incomplete plan; complete the reserved run first')


def save_act(path, report):
    report['ended_at'] = datetime.now(timezone.utc).isoformat()
    save_operation(path, report)


def add_intent(report, row, directory, operation):
    row.update(directory=directory, operation=operation, outcome='intent',
               run_id=report['run_id'], session_id=row['identity']['session_id'],
               text=row['identity']['text'])
    row['write_id'] = hashlib.sha256((report['run_id'] + ':' + str(len(report['work'])) + ':' +
                                     identity_key(row['identity'])).encode()).hexdigest()
    if operation == 'ask':
        row.update(destination='ask', binding='ask')
        row.update({key: row['ask'].get(key) for key in ('choices', 'ticket')})
    elif operation == 'native_step':
        row.update(native_step=row['binding'], unattended=True,
                   command=checklist.NATIVE[row['binding']]['command'])
    elif operation in APPLY_OPERATIONS.values():
        row.update(native_step=row['binding'], command=checklist.NATIVE[row['binding']]['command'])
    report['work'].append(row)


def slot_ask(row, directory, bound):
    slot = row.get('slot') or row['binding']
    return dict(row, binding='ask', destination='ask',
                outcome='dry run' if bound else 'unbound',
                ask=dict(text=row['identity']['text'], identity=row['identity'],
                         session_id=row['identity']['session_id'], directory=directory,
                         ticket=(row['item'].get('anchor') or {}).get('ticket'),
                         choices=['save through ' + slot, 'leave it']))


def ledger_item(row):
    """The item as its ledger knows it: its own identity, or the source's for a legacy item."""
    item = {'disposition': 'apply through its native step', **row['item'], 'type': row['item_kind']}
    for field in ('session_id', 'produced_at'):
        item[field] = item.get(field) or row['identity'][field]
    return item


def single_item(row):
    """One item as the wrap's modules read a payload."""
    item = ledger_item(row)
    return item, {'subject': {'session_id': row['ledger_session']}, 'resume': {'open_loops': [item]}}


def outcome_for(item, outcomes):
    """This item's outcome among a module's rows, or None when none is recorded."""
    key = handoff.session_item_identity(item)
    return next((outcome for outcome in outcomes if tuple(outcome['identity']) == key), None)


def module_for(kind):
    return checklist.lessons if kind == 'lesson' else checklist.knowledge


# The terminal statuses a ledger row may carry; any other status is a malformed row.
STATUSES = {'lesson': ('applied', 'dropped', 'failed'), 'knowledge': ('captured', 'asked', 'failed')}


def is_settled(kind, outcome):
    """An outcome no later run repeats; a fact about the user settles when its ask is delivered."""
    if kind == 'lesson':
        return outcome['status'] in ('applied', 'dropped')
    return outcome['status'] == 'captured' or bool(outcome.get('ask_delivered'))


def ledger_outcomes(kind, session, errors=None, damaged=None):
    """The latest outcome per item in one session's ledger; a malformed row fails only itself.

    `damaged` collects the identity of each malformed row whose identity still reads, so the
    item it names is applied by nobody until the row is repaired.
    """
    path = handoff.ledger_path(session)
    latest = {}
    for number, row in enumerate(handoff._ledger_records(path), 1):
        if row.get('kind') != module_for(kind).OUTCOME:
            continue
        key = None
        try:
            outcome = row['outcome']
            key = tuple(outcome['identity'])
            if not key or not all(isinstance(part, str) for part in key):
                key = None
                raise ValueError('an outcome needs a string identity')
            if outcome.get('status') not in STATUSES[kind]:
                raise ValueError('unknown status ' + repr(outcome.get('status')))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            if errors is not None:
                errors.append({'path': path, 'reason': 'ledger row ' + str(number) + ' is malformed (' +
                               error_text(exc) + '); the other rows were searched'})
            if damaged is not None and key is not None:
                damaged.add(key)
            continue
        latest[key] = outcome
    return list(latest.values())


def ledger_index(kind, errors):
    """Every recorded outcome by identity, across every session's ledger, and the damaged identities.

    A wrap records under its own session, which may be neither the producer nor the handoff's.
    """
    found, damaged = {}, set()
    for session in handoff.ledger_sessions():
        for outcome in ledger_outcomes(kind, session, errors, damaged):
            found.setdefault(tuple(outcome['identity']), []).append((session, outcome))
    return {'found': found, 'damaged': damaged}


def recorded_outcome(row, session, index):
    """A settled outcome and the ledger holding it, else the producer's ledger and None.

    The producer's ledger is shared by every handoff carrying the item, so two handoffs never
    apply it twice.
    """
    item = ledger_item(row)
    producer = item['session_id']
    settled = [(ledger, outcome) for ledger, outcome in index['found'].get(handoff.session_item_identity(item), [])
               if is_settled(row['item_kind'], outcome)]
    settled.sort(key=lambda found: (found[0] != producer, found[0] != session))
    return settled[0] if settled else (producer, None)


def settle_lesson(row, outcome):
    """Copy a lesson's outcome onto its row. A commit stays `applied` until it is delivered."""
    row['applied_kind'] = 'lesson'
    if outcome['status'] == 'dropped':
        row.update(outcome='dropped', reason=outcome.get('reason'))
    elif outcome['status'] == 'failed':
        row.update(outcome='failed', error=outcome.get('error'))
    else:
        done = 'already_written' if row.get('already_settled') else 'written'
        row.update({key: outcome[key] for key in LESSON_FIELDS if outcome.get(key) not in (None, [])})
        row.update(receipt=outcome.get('commit') or outcome.get('target'), destination=outcome.get('target'),
                   ask_required=bool(outcome.get('ask')) and not outcome.get('ask_delivered'),
                   outcome='applied' if outcome.get('commit') and outcome.get('delivery') not in DELIVERED else done)


def settle_capture(row, outcome):
    row.update(applied_kind='knowledge', capture=outcome.get('capture'))
    if outcome.get('status') == 'asked':
        row.update(receipt=outcome.get('receipt') or 'ask delivered', destination='ask', outcome='already_written')
        return
    files = [*outcome.get('created', []), *outcome.get('updated', [])]
    row.update(created=outcome.get('created', []), updated=outcome.get('updated', []),
               receipt=', '.join(files) or outcome.get('capture'), destination=files[0] if files else None,
               outcome='already_written' if row.get('already_settled') else 'written')


def settle_prior(row, outcome):
    """An outcome this run found, not one it made: never its work, and never in its undo."""
    row['already_settled'] = True
    (settle_lesson if row['item_kind'] == 'lesson' else settle_capture)(row, outcome)
    if row['outcome'] != 'dropped':
        row['reason'] = 'Already settled; its ledger holds the receipt'


def plan_apply(section, row, session, index):
    """Mark what act mode would apply, unless a ledger already settles it."""
    row.update(item_kind=ITEM_TYPES[row['binding']], handoff_session=session)
    try:
        if handoff.session_item_identity(ledger_item(row)) in index['damaged']:
            row.update(outcome='carried', ledger_damaged=True,
                       reason='A ledger row for this item is malformed; nothing is applied until it is repaired')
            return
        row['ledger_session'], prior = recorded_outcome(row, session, index)
    except Exception as exc:
        row.update(outcome='failed', error=error_text(exc))
        return
    if prior:
        settle_prior(row, prior)
        if row['outcome'] == 'applied':
            row['reason'] = 'Committed, not pushed; act mode delivers it'
        section['already_settled'].append(row)
    else:
        row.update(outcome='would apply', reason='Auto-apply setting on; act mode applies this item')
        section['would_apply'].append(row)


def plan_act(report, discovery, ask, config, path, persist=None):
    """Journal intents only. The driving agent performs all profile bindings."""
    for candidate in discovery['candidates']:
        candidate['planned_source'] = True
    report.update(mode='act', phase='planned', work=[], undo_items=[],
                  discovery=discovery, ask_bound=ask is not None)
    if report.get('auto_apply'):
        report['persist_binding'] = persist
    created = 0
    tripwires = {}
    for directory, section in report['directories'].items():
        section['unfiled_items'] = []
        section['worktrees_removed'] = []
        section['worktrees_kept'] = []
        section['handoffs_archived'] = []
        section['handoffs_kept'] = []
        if report.get('auto_apply'):
            section['would_apply'] = []
        # These proposals depend on checks repeated after filing. Never expose
        # them as deliverable intents until completion has refreshed the premise.
        section['asks_raised'] = [row for row in section['asks_raised']
                                  if not row.get('worktree') and not row.get('open_session')]
        for index, row in enumerate(section['filing_outcomes']):
            row['directory'] = directory
            if row['rule'] == 'R4' and row['outcome'] == 'unbound' and row.get('binding') != 'ask':
                row = slot_ask(row, directory, ask is not None)
                section['filing_outcomes'][index] = row
                section['asks_raised'].append(row)
            if row['outcome'] == 'would apply':
                add_intent(report, row, directory, APPLY_OPERATIONS[row['binding']])
                continue
            if row['outcome'] != 'dry run' and not (row['outcome'] == 'carried' and row.get('binding') in checklist.NATIVE
                                                    and not row.get('ledger_damaged')):
                continue
            if row['rule'] in ('R1', 'R6'):
                row['outcome'] = 'dropped'
            elif row.get('binding') != 'ask':
                operation = {'R2': 'comment', 'R5': 'create_ticket', 'R7': 'edit_document',
                             'R4': 'native_step'}[row['rule']]
                if operation == 'create_ticket':
                    if created >= config['new_ticket_limit']:
                        row.update(outcome='tripwire', reason='new-ticket limit reached')
                        tripwires[directory] = row['source_handoff']
                        continue
                    created += 1
                add_intent(report, row, directory, operation)
        for row in section['asks_raised']:
            if row['outcome'] == 'dry run':
                add_intent(report, row, directory, 'ask')
    if tripwires:
        directory, source = next(iter(tripwires.items()))
        candidate = next(c for c in discovery['candidates'] if c['path'] == source)
        section = report['directories'][directory]
        add_ask(section, candidate, 'New-ticket limit reached in ' + ', '.join(sorted(tripwires)),
                ['review unfiled items', 'raise limit'], 'tripwire', ask)
        row = section['asks_raised'][-1]
        if ask:
            add_intent(report, row, directory, 'ask')
    for section in report['directories'].values():
        section['unfiled_items'] = [row for row in section['filing_outcomes'] if row['outcome'] != 'dropped']
    save_act(path, report)
    # The store-scoped reservation survives process exit and report-location changes.
    # Store lock serializes publication of the report and its reservation.
    reserve(path, report)


def reserve(path, report):
    with pending_path().open('x') as handle:
        json.dump(dict(run_id=report['run_id'], report=str(path), mode=report['mode']), handle)
        handle.flush()
        os.fsync(handle.fileno())


def load_results(path, work, statuses):
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('results must be an array of objects')
    known = {row['write_id']: row for row in work}
    applying = {row['write_id']: row['operation'] for row in work if row.get('operation') in APPLY_OPERATIONS.values()}
    native = {row['write_id'] for row in work if row.get('operation') == 'native_step'} | set(applying)
    result = {}
    for row in rows:
        key = row.get('write_id')
        if key not in known or key in result:
            raise ValueError('unknown or duplicate write id')
        if key in applying and row.get('status') in ('written', 'already_written'):
            raise ValueError('an applied item returns its assessment; the sweep records the receipt')
        if key in native and row.get('status') in ('written', 'already_written'):
            raise ValueError('an unattended native step carries items and applies nothing')
        if row.get('status') == 'assessed':
            field = 'lesson' if applying.get(key) == 'apply_lesson' else 'knowledge'
            if key not in applying or not isinstance(row.get(field), dict):
                raise ValueError('assessed requires an applied item and its ' + field + ' row')
        if key not in native and row.get('status') in ('carried', 'nothing', 'not configured', 'declined'):
            raise ValueError('native outcomes require a native step')
        if row.get('status') not in statuses:
            raise ValueError('unsupported result status')
        if row['status'] in ('written', 'already_written'):
            original = known[key]
            if original.get('binding') in checklist.record_write.KINDS:
                receipt = checklist.record_write.receipt(row, original['identity'])
                if row.get('destination') != receipt['destination']:
                    raise ValueError('confirmed write destination must match its receipt')
            elif not all(isinstance(row.get(k), str) and row[k].strip()
                         for k in ('receipt', 'destination')):
                raise ValueError('confirmed writes require receipt and destination')
        if row['status'] == 'failed' and not (row.get('error') or row.get('reason')):
            raise ValueError('failed results require an error')
        result[key] = row
    return result


def rehydrate(report):
    """Restore shared outcome rows after a JSON round trip."""
    work = {row['write_id']: row for row in report['work']}
    for section in report['directories'].values():
        for key, rows in section.items():
            section[key] = [work.get(row.get('write_id'), row) for row in rows]


def error_text(error):
    return str(error) or type(error).__name__


def required_outcome(item, outcomes):
    outcome = outcome_for(item, outcomes)
    if outcome is None:
        raise ValueError('the step recorded no outcome for this item')
    return outcome


def apply_lesson(row, assessment):
    """Write one assessed lesson through the wrap's module."""
    item, payload = single_item(row)
    done = checklist.lessons.apply(payload, [dict(assessment, index=0)], handoff, row['ledger_session'])
    settle_lesson(row, required_outcome(item, done['lesson_outcomes']))


def apply_knowledge(report, row, assessment, profile):
    """Check one capture through the wrap's module, measured from this run's start."""
    item, payload = single_item(row)
    done = checklist.knowledge.apply(payload, [dict(assessment, index=0)], handoff, row['ledger_session'],
                                     checklist.knowledge.profile_path(profile),
                                     datetime.fromisoformat(report['started_at']))
    outcome = required_outcome(item, done['knowledge_outcomes'])
    if outcome['status'] == 'failed':
        row.update(outcome='failed', error=outcome['error'])
    elif outcome['status'] == 'captured':
        settle_capture(row, outcome)
    else:
        raise_fact_ask(report, row, done['resume']['open_loops'][0])


def share_result(row, first):
    """Copy the one journaled ask's standing onto a row that shares it."""
    row['outcome'] = 'dry run' if first['outcome'] == 'intent' else first['outcome']
    for key in ('receipt', 'destination', 'error'):
        if key in first:
            row[key] = first[key]


def journal_ask(report, followup):
    """One ask per item in a run: a second handoff carrying the item shares the first ask's result."""
    if not report['ask_bound']:
        return
    key = handoff.session_item_identity(ledger_item(followup))
    first = next((row for row in report['work'] if row['operation'] == 'ask' and row.get('settles') == followup['settles']
                  and handoff.session_item_identity(ledger_item(row)) == key), None)
    if first is None:
        add_intent(report, followup, followup['directory'], 'ask')
        return
    followup.update(shares_ask=first['write_id'], reason='One ask per item: shares the ask raised for ' + first['source_handoff'])
    share_result(followup, first)


def settle_shared_asks(report, first):
    for section in report['directories'].values():
        for rows in section.values():
            for row in (rows if isinstance(rows, list) else []):
                if isinstance(row, dict) and row.get('shares_ask') == first['write_id']:
                    share_result(row, first)


def raise_fact_ask(report, row, item):
    """A fact about the user is an ordinary ask; delivering it is what settles the item here."""
    section = report['directories'][row['directory']]
    ask = checklist.ask_payload(item, {'session_id': row['ledger_session'], 'working_directory': row['directory']})
    followup = {key: value for key, value in row.items()
                if key not in ('write_id', 'native_step', 'command', 'operation')}
    followup.update(binding='ask', destination='ask', outcome='dry run' if report['ask_bound'] else 'unbound',
                    settles='knowledge',
                    reason='Fact about the user: never saved without the user',
                    ask=dict(ask, identity=row['identity']))
    row.update(outcome='asked')
    section['filing_outcomes'] = [followup if old is row else old for old in section['filing_outcomes']]
    section['asks_raised'].append(followup)
    journal_ask(report, followup)


def landed(row, error):
    """What an error left behind: work the ledger holds stands, and goes on to delivery."""
    kind = row['item_kind']
    try:
        outcome = outcome_for(ledger_item(row), ledger_outcomes(kind, row['ledger_session']))
    except Exception:
        outcome = None
    if outcome and outcome.get('status') == ('applied' if kind == 'lesson' else 'captured'):
        (settle_lesson if kind == 'lesson' else settle_capture)(row, outcome)
        row.pop('error', None)
        row['warning'] = 'Applied, then a later step failed: ' + error_text(error)
    else:
        row.update(outcome='failed', error=error_text(error))


def apply_assessed(report, row, result, profile):
    """Whatever one assessment raises fails only its own item; the others still apply."""
    try:
        recorded = outcome_for(ledger_item(row), ledger_outcomes(row['item_kind'], row['ledger_session']))
        if recorded and is_settled(row['item_kind'], recorded):
            # Another handoff in this run carried the item and got there first.
            settle_prior(row, recorded)
        elif row['operation'] == 'apply_lesson':
            apply_lesson(row, result['lesson'])
        else:
            apply_knowledge(report, row, result['knowledge'], profile)
    except SystemExit:
        # The profile validator exits after printing why; the item keeps its source.
        row.update(outcome='failed', error='the knowledge profile is invalid')
    except Exception as exc:
        landed(row, exc)


def record_delivered_ask(row):
    """Keep the delivery beside the outcome, so a later run never raises the same ask."""
    module = module_for(row['settles'])
    try:
        outcome = outcome_for(ledger_item(row), ledger_outcomes(row['settles'], row['ledger_session']))
        if outcome:
            handoff.append_ledger(row['ledger_session'], {'kind': module.OUTCOME, 'outcome': {
                **outcome, 'ask_delivered': True, 'receipt': row.get('receipt')}})
    except Exception as exc:
        row['warning'] = 'Ask delivered, but its ledger was not updated: ' + error_text(exc)


def lesson_rows(report, *outcomes):
    return [row for section in report['directories'].values() for row in section['filing_outcomes']
            if row.get('applied_kind') == 'lesson' and row['outcome'] in outcomes]


def not_pushed(rows, error):
    for row in rows:
        row.update(outcome='not pushed', delivery=checklist.lessons.NOT_PUSHED, error=error)


def deliver_lessons(report, rows):
    """Push through the wrap's delivery, once per ledger; only a delivered commit is a receipt."""
    bound = report['persist_binding'] is not None
    for session in sorted({row['ledger_session'] for row in rows}):
        group = [row for row in rows if row['ledger_session'] == session]
        try:
            delivered = checklist.lessons.deliver(handoff, session, bound, checklist.lessons.routing_rules())
        except Exception as exc:
            not_pushed(group, error_text(exc))
            continue
        for row in group:
            outcome = outcome_for(ledger_item(row), delivered)
            if outcome is None:
                not_pushed([row], 'delivery recorded no outcome for this commit')
                continue
            settle_lesson(row, outcome)
            if row['outcome'] == 'applied':
                not_pushed([row], outcome.get('error') or 'not pushed')
            else:
                row.pop('error', None)


def raise_lesson_ask(report, row):
    """An applied lesson's ask is text only, written once its delivered commit is known."""
    section = report['directories'][row['directory']]
    outcome = required_outcome(ledger_item(row), ledger_outcomes('lesson', row['ledger_session']))
    item = {key: value for key, value in row['item'].items() if key != 'choices'}
    item.update(applied=True, commit=outcome.get('commit'), ask_text=checklist.lessons.ask_text(outcome))
    ask = checklist.ask_payload(item, {'session_id': row['ledger_session'], 'working_directory': row['directory']})
    followup = dict(rule='R3', outcome='dry run' if report['ask_bound'] else 'unbound', binding='ask',
                    destination='ask', reason='Applied lesson for an always-loaded rules file',
                    source_handoff=row['source_handoff'], identity=row['identity'], directory=row['directory'],
                    item=row['item'], ask=dict(ask, identity=row['identity']), settles='lesson',
                    item_kind='lesson', ledger_session=row['ledger_session'])
    section['asks_raised'].append(followup)
    journal_ask(report, followup)


def advance_lessons(report, protected):
    """Move applied lessons toward delivery; true while new work awaits the driving agent.

    Worktree and archive checks wait for this, so they see delivered commits. A commit whose
    session is open again is held: not pushed now, delivered by a later sweep.
    """
    rows = lesson_rows(report, 'applied')
    held = [row for row in rows if protected(row)]
    not_pushed(held, OPEN_SESSION + '; delivery waits for a later sweep')
    rows = [row for row in rows if row not in held]
    if rows:
        persist = next((row for row in report['work'] if row['operation'] == 'persist'), None)
        if report['persist_binding'] and persist is None:
            directory = rows[0]['directory']
            row = dict(report['persist_binding'], binding='persist', rule=None, source_handoff=None, directory=directory,
                       checkouts=sorted({row['checkout'] for row in rows}),
                       surfaces=[surface for row in rows for surface in row.get('surfaces', [])],
                       identity={'session_id': report['run_id'], 'produced_at': report['started_at'],
                                 'text': 'Persist lesson commits'})
            add_intent(report, row, directory, 'persist')
            return True
        if persist and persist['outcome'] not in ('written', 'already_written'):
            not_pushed(rows, 'persist did not confirm (' + persist['outcome'] + '): ' + (persist.get('error') or 'no error given'))
        else:
            deliver_lessons(report, rows)
    # Only a delivered commit raises its ask; a commit not pushed keeps the handoff and asks later.
    for row in lesson_rows(report, 'written', 'already_written'):
        if row.get('ask_required') and not protected(row):
            row['ask_required'] = False
            try:
                raise_lesson_ask(report, row)
            except Exception as exc:
                # The ask stays owed: a failed row keeps the handoff, and the next run raises it.
                report['directories'][row['directory']]['asks_raised'].append(dict(
                    rule='R3', outcome='failed', error=error_text(exc), source_handoff=row['source_handoff'],
                    identity=row['identity'], directory=row['directory'], item=row['item']))
    return any(row['outcome'] == 'intent' for row in report['work'])


def complete_act(config, run_id, results_path, evidence=None, knowledge_profile=None):
    reservation = json.loads(pending_path().read_text())
    if reservation['run_id'] != run_id or reservation['mode'] != 'act':
        raise ValueError('run id does not own the incomplete act plan')
    path = Path(reservation['report'])
    report = read_report(path)
    if report['phase'] == 'completed':
        pending_path().unlink()
        return path, report
    rehydrate(report)
    # Before any early return: a later call may omit it, and a live session must stay protected.
    discovery = report['discovery']
    if evidence is not None:
        discovery['open_session_evidence'] = evidence
    # Evidence and current activity are read on this call, ahead of every write: a session
    # named open now is never applied to, committed or pushed for.
    checks = open_session_checks(config, discovery.get('open_session_evidence',
                                                       read_open_sessions(None)))
    report['open_session_checks'] = [checks]
    current = discover('all', config, datetime.now(timezone.utc))
    discovery_failed = any(error.get('blocks_sweep') for error in current['errors'])
    for error in current['errors']:
        if error not in report['errors']:
            report['errors'].append(error)
    originals = {c['path']: c for c in discovery['candidates']}
    for candidate in current['candidates']:
        if candidate['path'] not in originals:
            candidate['worktree_retention_reason'] = 'handoff was not in this run plan: ' + candidate['path']
            discovery['candidates'].append(candidate)
        elif not candidate['abandoned']:
            originals[candidate['path']]['abandoned'] = False
    for candidate in discovery['candidates']:
        if discovery_failed or checks['failed'] or candidate['session_id'] in checks['session_ids']:
            candidate['abandoned'] = False
    # Open producers and ledger owners may have no handoff in discovery.
    live = set(checks['session_ids']) | {candidate['session_id'] for candidate in discovery['candidates']
                                       if not candidate['abandoned']}

    def protected(row):
        """An item whose handoff's or producing session is open, or whose abandonment is unknown."""
        return (discovery_failed or checks['failed'] or row['identity']['session_id'] in live
                or row.get('handoff_session') in live or row.get('ledger_session') in live)

    results = load_results(results_path, report['work'],
                           ('written', 'already_written', 'failed', 'uncertain', 'carried', 'nothing', 'not configured', 'declined', 'assessed'))
    for row in list(report['work']):
        if row['outcome'] != 'intent':
            continue
        result = results.get(row['write_id'], dict(status='uncertain', error='missing result'))
        row.update(outcome=result['status'])
        for key in ('receipt', 'destination', 'error'):
            if key in result:
                row[key] = result[key]
        if (row['operation'] == 'ask' and row.get('native_step') in checklist.NATIVE
                and row['outcome'] in ('written', 'already_written')):
            row.update(ask_outcome=row['outcome'], ask_status='filed', outcome='carried',
                       reason='Ask delivered; native capture remains pending')
        if row['outcome'] == 'written' and row['operation'] not in ('ask', 'persist'):
            report['undo_items'].append(dict(row, kind='record',
                write_operation=row['operation'], write_outcome='written'))
        if row['outcome'] == 'assessed':
            if protected(row):
                row.update(outcome='carried', reason=OPEN_SESSION + '; the sweep applies nothing from it')
            else:
                apply_assessed(report, row, result, knowledge_profile)
        if row['operation'] == 'ask':
            settle_shared_asks(report, row)
        if row.get('settles') and row['outcome'] in ('written', 'already_written'):
            record_delivered_ask(row)
        if row['operation'] == 'file_slot' and row['outcome'] == 'failed' and result.get('pending') is True:
            section = report['directories'][row['directory']]
            followup = slot_ask(row, row['directory'], report['ask_bound'])
            followup.pop('write_id', None)
            section['filing_outcomes'] = [followup if old is row else old for old in section['filing_outcomes']]
            section['asks_raised'].append(followup)
            if report['ask_bound']:
                add_intent(report, followup, row['directory'], 'ask')
        save_act(path, report)
    if report.get('auto_apply') and advance_lessons(report, protected):
        save_act(path, report)
        return path, report
    history_config = dict(config, report_location=str(path.parent))
    history = read_ask_history(history_config)
    for section in report['directories'].values():
        for key in ('new_tickets', 'comments_added', 'documents_changed', 'items_dropped',
                    *(key for key, _ in APPLY_SECTIONS if report.get('auto_apply'))):
            section[key] = []
        section['unfiled_items'] = []
        section['handoffs_kept'] = []
        for row in section['filing_outcomes']:
            if row.get('already_settled') and row['outcome'] in ('already_written', 'dropped'):
                section['already_settled'].append(row)
                continue
            if row.get('applied_kind') and row['outcome'] in ('written', 'not pushed'):
                key = ('knowledge_captured' if row['applied_kind'] == 'knowledge' else
                       'lessons_applied' if row['outcome'] == 'written' else 'lessons_not_pushed')
                section[key].append(row)
            if row['outcome'] == 'dropped':
                section['items_dropped'].append(row)
            elif row['outcome'] == 'written' and row['rule'] in ('R2', 'R5', 'R7'):
                section[{'R2': 'comments_added', 'R5': 'new_tickets', 'R7': 'documents_changed'}[row['rule']]].append(row)
            elif row['outcome'] not in ('written', 'already_written'):
                section['unfiled_items'].append(row)
        for row in section['asks_raised']:
            if row.get('open_session') and row['outcome'] in ('written', 'already_written'):
                history[row['identity']['session_id']] = row['activity_at']
    if history:
        save_ask_history(history_config, history)
    for candidate in discovery['candidates']:
        if candidate.get('planned_source') and not candidate['abandoned']:
            section = report['directories'].get(candidate['directory'])
            if section is not None:
                section['handoffs_kept'].append(dict(path=candidate['path'], outcome='kept',
                    reason='session became active, open, or abandonment check failed'))
    for check in checks['results']:
        if check['outcome'] == 'failed' and check not in report['errors']:
            report['errors'].append(dict(check, reason='open-session check failed; no session counts as abandoned'))
    ask = True if report['ask_bound'] else None

    def save():
        save_act(path, report)

    def send_ask(row):
        previous = next((old for old in report['work'] if old['operation'] == 'ask'
                         and old['source_handoff'] == row['source_handoff']
                         and old['identity'] == row['identity']), None)
        if previous is not None:
            section = report['directories'][row['directory']]
            section['asks_raised'].remove(row)
            return
        direct = row.get('open_session') and report['interactive']
        if ask or direct:
            add_intent(report, row, row['directory'], 'ask')
            if direct:
                row.update(delivery='direct', binding='direct')
        else:
            row.update(outcome='unbound', binding='ask', destination='ask')

    # Open-idle asks, like worktree-retention asks, use post-filing evidence.
    # Seed configured checks from agent evidence, never their previous results.
    for section in report['directories'].values():
        section['open_sessions'] = []
    asked_sessions = set()
    for candidate in current['candidates']:
        original = originals.get(candidate['path'])
        if not original or not original.get('planned_source') or candidate['session_id'] not in checks['session_ids']:
            continue
        section = report['directories'].get(candidate['directory'])
        if section is None:
            continue
        section['open_sessions'].append({key: candidate[key] for key in
                                        ('session_id', 'idle_seconds', 'activity_at', 'path')})
        if (not checks['failed'] and candidate['idle_seconds'] > config['idle_days'] * 86400
                and history.get(candidate['session_id'], -1) < candidate['activity_at']
                and candidate['session_id'] not in asked_sessions):
            add_ask(section, candidate, 'Open idle session: ' + candidate['session_id'],
                    ['wrap it', 'leave it', 'close it'], 'open session remains idle after filing', ask)
            row = section['asks_raised'][-1]
            row.update(open_session=True, activity_at=candidate['activity_at'], directory=candidate['directory'])
            row['ask']['activity_at'] = candidate['activity_at']
            send_ask(row)
            asked_sessions.add(candidate['session_id'])
    finish_act(report, discovery, ask, path, save, send_ask)
    if report['phase'] == 'completed':
        pending_path().unlink()
    return path, report


def finish_act(report, discovery, ask, path, save, send_ask):
    # All sections finish filing before a worktree can be removed. Include
    # sibling sources below the worktree root, not just exact directory peers.
    checks = report['open_session_checks'][0]
    for candidate in discovery['candidates']:
        if any(Path(candidate['directory']) == Path(root) or Path(root) in Path(candidate['directory']).parents for root in report.get('removed_paths', [])):
            continue
        try:
            check_handoff_source(candidate)
            initial = candidate.get('archive_worktree_check')
            current = archive_worktree_check(candidate)
            if any(check is not None and not check['clean'] for check in (initial, current)):
                candidate['worktree_retention_reason'] = 'related handoff has unconfirmed clean worktree: ' + candidate['path']
        except (ValueError, OSError) as exc:
            candidate['worktree_retention_reason'] = 'related handoff changed or unreadable: ' + candidate['path'] + ': ' + str(exc)
            section = report['directories'].get(candidate['directory'])
            if section is not None:
                for row in section['handoffs_kept']:
                    if row['path'] == candidate['path']:
                        row['error'] = str(exc)
    protected = worktree_protection(discovery, report, checks, act=True)
    removed_paths = set(report.get('removed_paths', []))
    attempted_paths = set(report.get('attempted_paths', []))
    for directory, section in report['directories'].items():
        for candidate in discovery['candidates']:
            if (candidate['directory'] != directory or not candidate['abandoned']
                    or not candidate.get('planned_source')):
                continue
            if any(Path(directory) == Path(root) or Path(root) in Path(directory).parents
                   for root in attempted_paths):
                continue
            proposed = worktree_plan(candidate, protected)
            if not proposed:
                continue
            worktree = proposed['path']
            attempted_paths.add(worktree)
            report['attempted_paths'] = sorted(attempted_paths)
            if proposed['outcome'] != 'dry run':
                if not any(r['path'] == proposed['path'] for r in section['worktrees_kept']):
                    section['worktrees_kept'].append(proposed)
                    temporary = {'asks_raised': []}
                    add_ask(temporary, candidate, 'Keep worktree ' + worktree + ': ' + proposed['reason'],
                            ['review worktree', 'leave it'], proposed['reason'], ask)
                    failure = temporary['asks_raised'][0]
                    failure['directory'] = directory
                    section['asks_raised'].append(failure)
                    send_ask(failure)
                    save()
                continue
            row = proposed
            try:
                related = [c for c in discovery['candidates']
                           if Path(worktree) == Path(c['directory']) or Path(worktree) in Path(c['directory']).parents]
                for source in related:
                    check_handoff_source(source)
                # Resolve the main checkout before removing this linked checkout.
                _, output, _ = git_read(worktree, 'worktree', 'list', '--porcelain')
                main = output.splitlines()[0].removeprefix('worktree ')
                row.update(outcome='uncertain', reason='plain worktree removal pending')
                section['worktrees_removed'].append(row)
                save()
                for source in related:
                    check_handoff_source(source)
                code, _, error = git_read(main, 'worktree', 'remove', worktree)
                row['checks']['plain_removal'] = code == 0
                if code:
                    raise ValueError(error or 'plain worktree removal failed')
                removed_paths.add(worktree)
                report['removed_paths'] = sorted(removed_paths)
                row.update(outcome='removed', reason='clean branch contained in pushed trunk')
                # Compare-and-delete preserves a concurrently moved branch.
                code, _, error = git_read(main, 'update-ref', '-d',
                    'refs/heads/' + row['branch'], row['commit'])
                row['branch_deleted'] = code == 0
                if code:
                    row['branch_error'] = error or 'local branch deletion failed'
                save()
            except (ValueError, OSError) as exc:
                row.update(outcome='kept', reason=str(exc))
                if row in section['worktrees_removed']:
                    section['worktrees_removed'].remove(row)
                section['worktrees_kept'].append(row)
                temporary = {'asks_raised': []}
                add_ask(temporary, candidate, 'Keep worktree ' + worktree + ': ' + str(exc),
                        ['review worktree', 'leave it'], str(exc), ask)
                failure = temporary['asks_raised'][0]
                failure['directory'] = directory
                section['asks_raised'].append(failure)
                send_ask(failure)
                save()
    if any(row['outcome'] == 'intent' for row in report['work']):
        save()
        return
    for directory, section in report['directories'].items():
        for candidate in discovery['candidates']:
            if (candidate['directory'] != directory or not candidate['abandoned']
                    or not candidate.get('planned_source')):
                continue
            if candidate['session_id'] in report['open_session_checks'][0]['session_ids']:
                continue
            source = candidate['path']
            outcomes = [r for r in section['filing_outcomes'] if r['source_handoff'] == source]
            asks = [r for r in section['asks_raised'] if r['source_handoff'] == source]
            initial_check = candidate.get('archive_worktree_check')
            live_check = (initial_check if any(Path(directory) == Path(root) or Path(root) in Path(directory).parents
                                              for root in removed_paths) else archive_worktree_check(candidate))
            clean = all(check is None or check['clean'] for check in (initial_check, live_check))
            archived = (clean and not candidate['handoff'].get('uncommitted_files') and
                        all(r['outcome'] in ('written', 'already_written', 'dropped') for r in outcomes) and
                        all(r['outcome'] in ('written', 'already_written') for r in asks))
            row = dict(path=source, outcome='kept', worktree_check=live_check,
                       reason='unfiled items, asks, or uncommitted files')
            unpushed = [r for r in outcomes if r['outcome'] == 'not pushed']
            if unpushed:
                row['reason'] = 'lesson commits not pushed: ' + '; '.join(
                    r['commit'] + ': ' + r['error'] for r in unpushed)
            if not clean:
                failed_check = next(check for check in (initial_check, live_check)
                                    if check is not None and not check['clean'])
                row['reason'] = 'worktree is not confirmed clean: ' + failed_check['reason']
            if archived:
                try:
                    original = Path(source)
                    check_handoff_source(candidate)
                    target = original.parent / 'archive'
                    if target.is_symlink():
                        raise ValueError('archive is a symbolic link')
                    target.mkdir(exist_ok=True)
                    target = target / original.name
                    if target.exists() or target.is_symlink():
                        target = target.with_name(report['run_id'] + '-' + original.name)
                    row.update(destination=str(target), outcome='uncertain', reason='archive move pending')
                    report['undo_items'].append(dict(kind='handoff', path=source,
                        archive=str(target), snapshot=candidate['source_snapshot']))
                    section['handoffs_archived'].append(row)
                    save()
                    check_handoff_source(candidate)
                    original.rename(target)
                    row.update(outcome='archived', reason='every item filed or dropped')
                except (ValueError, OSError) as exc:
                    row.update(outcome='kept', error=str(exc))
                    if row in section['handoffs_archived']:
                        section['handoffs_archived'].remove(row)
                    section['handoffs_kept'].append(row)
            else:
                section['handoffs_kept'].append(row)
            save()
    report['phase'] = 'completed'
    save()


def report_fields(value, label=''):
    """Render nested report facts as labeled text, without JSON or repr syntax."""
    if isinstance(value, dict):
        return '; '.join(report_fields(child, (label + ' ' + key.replace('_', ' ')).strip())
                         for key, child in value.items()) or (label.capitalize() + ': none')
    if isinstance(value, list):
        return '; '.join(report_fields(child, label + (f' {index}' if len(value) > 1 else ''))
                         for index, child in enumerate(value, 1)) or (label.capitalize() + ': none')
    text = 'not assigned' if value is None else str(value).lower() if isinstance(value, bool) else str(value)
    text = ' '.join(text.splitlines())
    return (label.capitalize() + ': ' if label else '') + text


def report_row(row):
    # Put the filing decision first; retain all remaining facts as labeled text.
    keys = ('item', 'path', 'session_id', 'rule', 'destination', 'outcome', 'reason')
    ordered = {key: row[key] for key in keys if key in row}
    ordered.update({key: value for key, value in row.items() if key not in ordered})
    return '- ' + report_fields(ordered)


def render_operation_report(report):
    lines = ['# Sweep ' + report['mode'] + ' report', '', report.get('note', '')]
    for key, value in report.items():
        if key not in ('mode', 'note', 'items'):
            lines.extend(['', report_fields(value, key.replace('_', ' '))])
    lines.extend(['', '## Items', ''])
    lines.extend([report_row(row) for row in report['items']] or ['None.'])
    lines.extend(['', '## Structured data', '', '```json', json.dumps(report, indent=2), '```', ''])
    return '\n'.join(lines)


def render_report(report):
    lines = ['# Sweep report', '', ('Watch-only: every action below is proposed; no action executed.' if report['mode'] == 'watch-only'
              else 'Act: outcomes and receipts describe executed actions. New this run lists created tickets.'), '',
             *[report_fields(report[key], key.replace('_', ' ')) for key in ('run_id', 'host', 'started_at', 'ended_at', 'scope', 'mode', 'interactive', 'open_session_checks',
                                                                         *(('auto_apply',) if report.get('auto_apply') else ()))]]
    if report['nothing_to_do']:
        lines.extend(['', 'Nothing to do.'])
    for directory, section in sorted(report['directories'].items()):
        lines.extend(['', '## ' + directory])
        for key, title in (*SECTIONS, *(APPLY_SECTIONS if report.get('auto_apply') else ()),
                           ('handoff_warnings', 'Handoff lint warnings'), ('filing_outcomes', 'Every filing outcome'),
                           ('worktrees_kept', 'Worktrees kept'), ('handoffs_kept', 'Handoffs kept'),
                           *((('unfiled_items', 'Unfiled items'),) if report['mode'] == 'act' else ())):
            lines.extend(['', '### ' + title])
            lines.extend([report_row(row) for row in section.get(key, [])] or ['None.'])
    persists = [row for row in report.get('work', []) if row['operation'] == 'persist']
    if persists:
        lines.extend(['', '## Persist for lesson commits', *[report_row(row) for row in persists]])
    if report['errors']:
        lines.extend(['', '## Errors; sources left in place', *[report_row(e) for e in report['errors']]])
    lines.extend(['', '## Structured data', '', '```json', json.dumps(report, indent=2, ensure_ascii=False), '```', ''])
    return '\n'.join(lines)


def save_operation(path, report):
    """Atomically replace the durable operation journal after every outcome."""
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as handle:
            handle.write(render_report(report) if report['mode'] == 'act' else
                         render_operation_report(report))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_report(path):
    if path.is_symlink():
        raise ValueError('report is a symbolic link')
    return json.loads(path.read_text().split('```json\n', 1)[1].rsplit('\n```', 1)[0])


def auto_apply_for(discovery):
    """The setting's state; an unreadable input stops only what it governs, and is reported."""
    try:
        return checklist.auto_apply_state()
    except (OSError, ValueError) as exc:
        reason = 'auto-apply: ' + str(exc)
    discovery['errors'].append({'path': 'auto-apply', 'reason': reason})
    try:
        # The routing file governs lessons only, so a readable setting still captures knowledge.
        knowledge = 'apply' if checklist.lessons.enabled(handoff.read_config()) else 'failed'
    except (OSError, ValueError):
        knowledge = 'failed'
    return {'lessons': 'failed', 'reason': reason, 'knowledge': knowledge}


def report_directory(config):
    destination = Path(config['report_location']).expanduser().resolve()
    store = Path(handoff.state_dir()).resolve()
    if destination == store or store in destination.parents:
        raise ValueError('report location must be outside the handoff store')
    return destination


def run_path(config, run_id, suffix='.md'):
    if not run_id or any(c not in '0123456789abcdef' for c in run_id):
        raise ValueError('run id must be a hexadecimal sweep run id')
    return report_directory(config) / (run_id + suffix)


def left_in_place(original):
    """What undo keeps: an applied lesson is undone by reverting its commit, not by the sweep."""
    fields = ('applied_kind', 'target', 'change', 'commit', 'delivery', 'pull_request', 'capture', 'created', 'updated')
    return [{key: row[key] for key in fields if key in row}
            for section in original['directories'].values()
            for key in ('lessons_applied', 'lessons_not_pushed', 'knowledge_captured')
            for row in section.get(key, []) if not row.get('already_settled')]


def plan_undo(config, run_id):
    if pending_path().exists():
        reservation = json.loads(pending_path().read_text())
        if reservation['run_id'] == run_id and reservation['mode'] == 'undo':
            path = Path(reservation['report'])
            return path, read_report(path)
    require_idle()
    original = read_report(run_path(config, run_id))
    if original.get('mode') != 'act' or original.get('phase') != 'completed':
        raise ValueError('undo requires a completed act run')
    path = run_path(config, run_id, '.undo.md')
    report = read_report(path) if path.exists() else dict(
        mode='undo', run_id=run_id, items=[dict(row, outcome='failed')
            for row in original['undo_items']],
        note='Worktree removal and local branch deletion cannot be reversed. '
             'Asks remain delivered. Check each target immediately before reversal; '
             'changes between the check and reversal are not detected. Only failed items retry.')
    applied = left_in_place(original)
    if applied:
        report.update(applied_left_in_place=applied, applied_note='Applied lessons and captures stay in place; '
                      'revert a lesson commit through the repository\'s normal delivery.')
    report.update(phase='planned', work=[], archive_restorations=[])
    for index, row in enumerate(report['items']):
        row.setdefault('write_id', hashlib.sha256((run_id + ':undo:' + str(index)).encode()).hexdigest())
        if row['outcome'] == 'failed':
            if row['kind'] == 'handoff':
                report['archive_restorations'].append(row)
            else:
                report['work'].append(dict(row, operation='reverse'))
    save_operation(path, report)
    reserve(path, report)
    return path, report


def complete_undo(config, run_id, results_path):
    reservation = json.loads(pending_path().read_text())
    if reservation['run_id'] != run_id or reservation['mode'] != 'undo':
        raise ValueError('run id does not own the incomplete undo plan')
    path = Path(reservation['report'])
    report = read_report(path)
    if report.get('phase') == 'completed':
        pending_path().unlink()
        return path, report
    if report.get('phase') != 'planned':
        raise ValueError('undo needs a plan before completion')
    results = load_results(results_path, report['work'], ('reversed', 'conflict', 'failed'))
    ids = {row['write_id'] for row in report['work']}
    for row in report['items']:
        if row['write_id'] not in ids or row['outcome'] != 'failed':
            continue
        result = results.get(row['write_id'], dict(status='failed', error='missing reversal result'))
        row.update(outcome=result['status'], reason=result.get('reason') or result.get('error') or result['status'])
        save_operation(path, report)
    store = Path(handoff.state_dir()).resolve()
    archive = store / 'archive'
    for row in report['items']:
        if row['kind'] != 'handoff' or row['outcome'] != 'failed':
            continue
        try:
            source, target = Path(row['archive']), Path(row['path'])
            if (archive.is_symlink() or source.parent != archive or target.parent != store
                    or source.is_symlink() or target.is_symlink()):
                raise ValueError('restore paths must be regular handoffs in this store and archive')
            if target.exists():
                # Recover a crash between the non-overwriting link and unlink.
                restored = False
                if not source.exists():
                    _, current = read_handoff_source(target)
                    restored = all(current[k] == v for k, v in row['snapshot'].items()
                                   if k != 'st_ctime_ns')
                if restored:
                    row.update(outcome='reversed')
                elif source.exists() and os.path.samefile(source, target):
                    source.unlink()
                    row.update(outcome='reversed')
                else:
                    row.update(outcome='conflict', reason='original path is occupied; archived handoff preserved')
            elif not source.exists():
                raise ValueError('archived handoff is missing (possibly removed by retention)')
            else:
                _, current = read_handoff_source(source)
                if any(current[k] != v for k, v in row['snapshot'].items() if k != 'st_ctime_ns'):
                    row.update(outcome='conflict', reason='archived handoff changed')
                else:
                    # link is exclusive: a newly written handoff is never overwritten.
                    os.link(source, target, follow_symlinks=False)
                    source.unlink()
                    row.update(outcome='reversed')
        except FileExistsError:
            row.update(outcome='conflict', reason='original path is occupied')
        except (OSError, ValueError) as exc:
            row.update(outcome='failed', reason=str(exc))
        save_operation(path, report)
    report['phase'] = 'completed'
    save_operation(path, report)
    pending_path().unlink()
    return path, report


def execute_retention(config, now, save=None):
    report = dict(mode='retention', started_at=now.isoformat(),
                  archive_retention_days=config['archive_retention_days'], items=[])
    archive = Path(handoff.state_dir()).resolve() / 'archive'
    days = config['archive_retention_days']
    if days is None or not archive.exists():
        if save:
            save(report)
        return report
    if archive.is_symlink():
        raise ValueError('archive is a symbolic link')
    for path in sorted(archive.glob('*.json')):
        if path.is_symlink() or not path.is_file():
            continue
        row = dict(path=str(path), outcome='kept')
        report['items'].append(row)
        try:
            _, snapshot = read_handoff_source(path)
            row['modified_at'] = snapshot['st_mtime_ns'] / 1e9
            if now.timestamp() - row['modified_at'] > days * 86400:
                row.update(outcome='failed', reason='deletion pending')
                if save:
                    save(report)
                _, current = read_handoff_source(path)
                if current != snapshot:
                    raise ValueError('archived handoff changed during retention')
                path.unlink()
                row.update(outcome='deleted', reason='strictly older than configured age')
            else:
                row['reason'] = 'at or newer than age boundary'
        except (OSError, ValueError) as exc:
            row.update(outcome='failed', reason=str(exc))
        if save:
            save(report)
    if save:
        save(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'run', 'complete', 'undo', 'complete-undo', 'retention'))
    parser.add_argument('--scope', help='all or a directory')
    parser.add_argument('--decisions', type=Path)
    parser.add_argument('--user-profile', type=Path)
    parser.add_argument('--open-sessions', type=Path, help='agent-supplied session_ids and method JSON')
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--results', type=Path)
    parser.add_argument('--user-started', action='store_true')
    parser.add_argument('--knowledge-profile', type=Path,
                        help='complete: the knowledge profile (default ~/.config/hippocampus/profile.md)')
    args = parser.parse_args(argv)
    try:
        config = settings()
        if args.command in ('complete', 'undo', 'complete-undo', 'retention'):
            with store_lock():
                if args.command in ('complete', 'complete-undo'):
                    if args.results is None:
                        raise ValueError('completion requires --results')
                    if args.command == 'complete':
                        evidence = read_open_sessions(args.open_sessions) if args.open_sessions else None
                        path, report = complete_act(config, args.run_id, args.results, evidence,
                                                    args.knowledge_profile)
                    else:
                        path, report = complete_undo(config, args.run_id, args.results)
                elif args.command == 'undo':
                    if not args.user_started:
                        raise ValueError('undo must be explicitly user-started with --user-started')
                    path, report = plan_undo(config, args.run_id)
                else:
                    require_idle()
                    destination = report_directory(config)
                    destination.mkdir(parents=True, exist_ok=True)
                    path = destination / (uuid.uuid4().hex + '.retention.md')
                    execute_retention(config, datetime.now(timezone.utc),
                                      lambda report: save_operation(path, report))
                    print(path)
                    return 0
                output = dict(report=str(path), run_id=report['run_id'], work=report.get('work', []),
                              phase=report['phase'], archive_restorations=report.get('archive_restorations', []))
                if report.get('applied_left_in_place'):
                    output['applied_left_in_place'] = report['applied_left_in_place']
                print(json.dumps(output))
            return 0
        if args.scope is None:
            raise ValueError('inspect and run require --scope')
        evidence = read_open_sessions(args.open_sessions)
        if args.interactive and args.open_sessions is None and not config['open_session_checks']:
            raise ValueError('interactive sweep requires open-session inspection evidence, including an empty result')
        with store_lock():
            if args.command == 'run':
                require_idle()
            started = datetime.now(timezone.utc)
            checks = open_session_checks(config, evidence)
            history = read_ask_history(config)
            discovery = discover(args.scope, config, started)
            discovery['idle_days'] = config['idle_days']
            discovery['open_session_checks'] = checks
            discovery['open_session_evidence'] = evidence
            for check in checks['results']:
                if check['outcome'] == 'failed':
                    discovery['errors'].append(dict(check, reason='open-session check failed; no session counts as abandoned'))
            for candidate in discovery['candidates']:
                if checks['failed'] or candidate['session_id'] in checks['session_ids']:
                    candidate['abandoned'] = False
            if args.command == 'inspect':
                print(json.dumps(discovery, indent=2))
                return 0
            rows = read_decisions(args.decisions, discovery)
            profile_path = args.user_profile
            if profile_path is None:
                profile_path = Path(os.environ.get('CHECKLIST_USER_PROFILE') or
                    str(Path(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))) / 'hippocampus/checklist-profile.md'))
                if not profile_path.exists():
                    profile_path = None
            profiles = [checklist.load_profile(profile_path)] if profile_path else []
            plan = checklist.compose(profiles)
            ask = checklist.ask_binding(profiles[0]) if profiles else None
            auto_apply = auto_apply_for(discovery)
            report = build_report(discovery, rows, plan, ask, checks, args.interactive, started, history, auto_apply)
            destination = Path(config['report_location']).expanduser().resolve()
            store = Path(handoff.state_dir()).resolve()
            if destination == store or store in destination.parents:
                raise ValueError('report location must be outside the handoff store')
            destination.mkdir(parents=True, exist_ok=True)
            path = destination / (report['run_id'] + '.md')
            with path.open('x') as handle:
                handle.write(render_report(report))
            if config['mode'] == 'act' and args.decisions is not None:
                plan_act(report, discovery, ask, config, path,
                         next(step for step in plan if step['id'] == 'persist').get('binding'))
                print(json.dumps(dict(report=str(path), run_id=report['run_id'], work=report['work'], phase=report['phase'])))
            else:
                print(path)
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('sweep: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
