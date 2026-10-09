#!/usr/bin/env python3
"""Deterministic capture, distribution receipts, and retention mechanics.

Synthesis and approvals belong to the invoking skills. External effects belong
only to explicitly supplied local workflows; this helper has no built-in task,
writing, document, or compiler integration.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
from typing import Any, Callable

PACKAGE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PACKAGE / 'scripts'))
import validate_profile as profile_schema

BLOCK = re.compile(r'^```hippocampus\n(.*?)\n```[ \t]*$', re.M | re.S)
KINDS = {'wiki', 'document', 'action', 'writing', 'retain', 'discard'}
VOLATILE = {'state', 'authorization', 'receipt', 'inflight', 'error', 'scope'}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def within(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError('path escapes knowledge_root') from None
    return path


@contextmanager
def locked(path: Path):
    # A stable sibling lock survives atomic record replacement. No process state
    # is needed to resume; all effect state is in the Markdown record.
    with path.with_name('.' + path.name + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def atomic_write(path: Path, content: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_record(path: Path) -> dict:
    matches = list(BLOCK.finditer(path.read_text(encoding='utf-8')))
    if len(matches) != 1:
        raise ValueError('record requires exactly one fenced hippocampus JSON block')
    value = json.loads(matches[0].group(1))
    if value.get('version') != 1 or value.get('kind') not in {'meeting', 'research'}:
        raise ValueError('unsupported distribution record')
    return value


def save(path: Path, state: dict) -> None:
    text = path.read_text(encoding='utf-8')
    block = '```hippocampus\n' + json.dumps(state, indent=2, ensure_ascii=False) + '\n```'
    matches = list(BLOCK.finditer(text))
    if len(matches) > 1:
        raise ValueError('multiple distribution blocks')
    if matches:
        match = matches[0]
        text = text[:match.start()] + block + text[match.end():]
    else:
        text = text.rstrip() + '\n\n' + block + '\n'
    atomic_write(path, text)


def sources_for(root: Path, sources: list[dict]) -> list[dict]:
    result = []
    identities = set()
    for source in sources:
        source = dict(source)
        identity = source.get('id')
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('sources require unique stable identities')
        identities.add(identity)
        if not source.get('path') and not source.get('url'):
            raise ValueError('source requires a path or original URL')
        if source.get('path'):
            path = within(root, source['path'])
            if not path.is_file():
                raise ValueError('selected source is not an existing file')
            source['path'] = path.relative_to(root).as_posix()
            source['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        if source.get('coverage') not in {'complete', 'partial', 'unavailable'}:
            raise ValueError('source coverage must be explicit')
        result.append(source)
    return result


def initial(kind: str, identity: str, sources: list[dict]) -> dict:
    return dict(version=1, kind=kind, record_id=identity, sources=sources,
                decisions=[], rows=[], history=[], status='captured',
                writing_result='not yet assessed')


def capture(profile: Path, identity: str, meeting_date: str, title: str,
            sources: list[dict], template: str | None = None,
            event_url: str | None = None) -> Path:
    root, values = profile_schema.validate(profile)
    if not identity.strip():
        raise ValueError('meeting source identity is required')
    date.fromisoformat(meeting_date)
    folder, selected_template, text = profile_schema.meeting_settings(root, values, template)
    sources = sources_for(root, sources)
    # Find by identity across root-contained Markdown records, even when the
    # configured folder or the user's filename changed. Do not parse prose.
    existing = []
    for candidate in root.rglob('*.md'):
        if candidate.is_symlink():
            continue
        if '```hippocampus\n' not in candidate.read_text(encoding='utf-8', errors='replace'):
            continue
        try:
            state = read_record(candidate)
        except (ValueError, UnicodeError):
            continue
        if state['kind'] == 'meeting' and state['record_id'] == identity:
            existing.append(candidate)
    if len(existing) > 1:
        raise ValueError('multiple records have this identity; reconcile before capture')
    if existing:
        # Recapture is deliberately read-only: prose, prior receipts, coverage,
        # and source versions remain available for the agent's comparison.
        return existing[0]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{meeting_date}-{digest(identity)[:16]}.md'
    state = initial('meeting', identity, sources)
    state.update(date=meeting_date, title=title, event_url=event_url,
                 template=str(selected_template), coverage=[s['coverage'] for s in sources])
    substitutions = dict(title=title, date=meeting_date, record_id=identity,
        event_url=event_url or 'Unavailable: no provider-returned event URL',
        sources='\n'.join(f"- {s['id']}: {s.get('path') or s.get('url')}" for s in sources),
        coverage='\n'.join(f"- {s['id']}: {s['coverage']}" for s in sources))
    for token, replacement in substitutions.items():
        text = text.replace('{{' + token + '}}', replacement)
    with locked(path):
        if path.exists():
            prior = read_record(path)
            if prior['record_id'] != identity:
                raise ValueError('record filename collision')
            return path
        path.write_text(text, encoding='utf-8')
        save(path, state)
    return path


def initialize_research(path: Path, sources: list[dict]) -> None:
    # Explicit preparation by the producer/absorber, after it has validated the
    # legacy prose plan. Existing artifacts need no heading migration.
    with locked(path):
        if BLOCK.search(path.read_text()):
            read_record(path)
            return
        save(path, initial('research', digest(path.name), sources))


def validate_rows(state: dict) -> None:
    sources = {s['id']: s for s in state['sources']}
    identities = set()
    for row in state['rows']:
        if not row.get('id') or row['id'] in identities:
            raise ValueError('rows require unique stable identities')
        identities.add(row['id'])
        if row.get('decision') not in state['decisions']:
            raise ValueError('row has no parent decision')
        if row.get('kind') not in KINDS or not row.get('change'):
            raise ValueError('row requires a supported kind and concrete change')
        if row.get('authorization') not in {'approved', 'pending', 'declined'}:
            raise ValueError('row authorization must be explicit')
        evidence = row.get('evidence')
        if not isinstance(evidence, list) or not evidence or any(s not in sources for s in evidence):
            raise ValueError('row requires selected source evidence')
        if row['kind'] == 'wiki' and any(sources[s].get('primary') is not True for s in evidence):
            raise ValueError('wiki compilation requires primary evidence')
        if row['kind'] == 'action' and not row.get('owner'):
            raise ValueError('action requires an owner')
        if row['kind'] == 'writing':
            if row.get('opportunity') not in {'new', 'enrich', 'published-followup'}:
                raise ValueError('unsupported writing opportunity')
            if any(not row.get(k) for k in ('author', 'angle', 'addition', 'privacy')):
                raise ValueError('writing requires attribution, angle, addition, and reuse limits')
            coverage = row.get('coverage', {})
            if any(coverage.get(k) not in {'searched', 'unavailable'} for k in ('ideas', 'drafts', 'published')):
                raise ValueError('writing requires ideas/drafts/publication search coverage')
        if not isinstance(row.get('preconditions', []), list):
            raise ValueError('preconditions must be a list of unresolved confirmations')


def row_scope(row: dict) -> str:
    return digest({k: v for k, v in row.items() if k not in VOLATILE})


def set_plan(path: Path, decisions: list[str], rows: list[dict],
             writing_result: str | None = None,
             legacy_results: dict[str, dict] | None = None) -> None:
    with locked(path):
        state = read_record(path)
        proposed = dict(state, decisions=decisions, rows=rows)
        validate_rows(proposed)
        legacy_results = legacy_results or {}
        if legacy_results and (state['kind'] != 'research' or set(legacy_results) - {r['id'] for r in rows}):
            raise ValueError('legacy receipts must belong to normalized research rows')
        previous = {r['id']: r for r in state['rows']}
        new_rows = []
        for raw in rows:
            row = {k: v for k, v in raw.items() if k not in VOLATILE}
            row.update(authorization=raw['authorization'], state='pending', scope=row_scope(raw))
            old = previous.pop(row['id'], None)
            if old and row_scope(old) == row_scope(row):
                for key in VOLATILE - {'authorization', 'scope'}:
                    if key in old:
                        row[key] = old[key]
                if old.get('authorization') == 'declined':
                    row['authorization'] = 'declined'
            elif old:
                if old.get('inflight'):
                    raise ValueError('reconcile uncertain effects before changing scope')
                state['history'].append(old)
                row['authorization'] = 'pending'
            if row['authorization'] == 'declined':
                if row.get('inflight'):
                    raise ValueError('reconcile uncertain effects before declining a row')
                row['state'] = 'declined'
            if row['id'] in legacy_results:
                result = legacy_results[row['id']]
                if row['authorization'] != 'approved' or row.get('inflight') or result.get('confirmed') is not True or not result.get('receipt') or result.get('target') != row.get('target'):
                    raise ValueError('legacy result requires authorized unchanged scope and verified target read-back')
                if row.get('receipt') and row['receipt'].get('receipt') != result['receipt']:
                    raise ValueError('legacy receipt conflicts with saved execution history')
                row.update(state='complete', receipt=dict(result, confirmed_at=now()))
            new_rows.append(row)
        # Removing work must not erase pending effects or confirmed history.
        if any(r.get('inflight') or r.get('state') == 'pending' for r in previous.values()):
            raise ValueError('explicitly decline removed pending rows before replacing the plan')
        state['history'].extend(previous.values())
        state.update(decisions=decisions, rows=new_rows, status='pending')
        if writing_result is not None:
            state['writing_result'] = writing_result
        save(path, state)


def execute(profile: Path, path: Path, workflows: dict[str, Callable[[dict], dict]]) -> dict:
    root, values = profile_schema.validate(profile)
    path = within(root, path)
    with locked(path):
        state = read_record(path)
        validate_rows(state)
        for row in state['rows']:
            if row.get('scope') != row_scope(row):
                state['history'].append(dict(row))
                row.update(authorization='pending', state='pending', receipt=None,
                           scope=row_scope(row), error='scope changed; renewed approval required')
                save(path, state)
                continue
            if row.get('state') in {'complete', 'declined'}:
                continue
            row['error'] = None
            if row['authorization'] != 'approved' or row.get('preconditions'):
                row['error'] = 'approval or target-required confirmation pending'
                continue
            if row.get('inflight'):
                row['error'] = 'external effect uncertain: reconcile by read-back before retry'
                continue
            if row['kind'] == 'wiki' and values.get('wiki_enabled') == 'false':
                row['error'] = 'wiki disabled; route requires a new approved destination'
                continue
            if row['kind'] == 'writing' and (not row.get('target') or not row.get('workflow')):
                row['error'] = 'no configured writable writing destination/workflow'
                continue
            workflow = workflows.get(row['kind'])
            if workflow is None:
                row['error'] = 'configured destination workflow unavailable'
                continue
            evidence = [s for s in state['sources'] if s['id'] in row['evidence']]
            if row['kind'] == 'wiki':
                invalid_primary = False
                for source in evidence:
                    if not source.get('path'):
                        invalid_primary = True
                        continue
                    selected = within(root, source['path'])
                    try:
                        selected.relative_to(root / 'raw')
                    except ValueError:
                        invalid_primary = True
                    if selected.is_file():
                        text = selected.read_text(encoding='utf-8')
                        head = text[4:].split('\n---', 1)[0] if text.startswith('---\n') else ''
                        if re.search(r'^(?:use: artifact|compile_mode: (?:exclude|update)|compile_exclude: true)\s*$', head, re.M):
                            invalid_primary = True
                    if selected == path:
                        invalid_primary = True
                if invalid_primary:
                    row['error'] = 'compiler requires selected primary raw evidence, not an artifact or excluded source'
                    continue
            changed = False
            for source in evidence:
                if source.get('path') and source.get('sha256'):
                    selected = within(root, source['path'])
                    if not selected.is_file() or hashlib.sha256(selected.read_bytes()).hexdigest() != source['sha256']:
                        changed = True
            if changed:
                row['error'] = 'selected evidence changed; compare and renew authorization'
                continue
            key = digest([state['record_id'], row['id'], row_scope(row)])
            row['inflight'] = key
            save(path, state)  # Persist before an external write can occur.
            request = dict(idempotency_key=key, row=dict(row), sources=evidence,
                           record=str(path), knowledge_root=str(root),
                           task_route=values['artifact_followup_destination'])
            try:
                result = workflow(request)
            except Exception as exc:
                row['error'] = f'workflow failed; read-back required: {exc}'
                save(path, state)
                continue
            if isinstance(result, dict) and result.get('confirmed') is True and result.get('receipt') and result.get('target') == row.get('target'):
                row.update(state='complete', receipt=dict(result, confirmed_at=now()), inflight=None)
            else:
                row['error'] = 'unconfirmed workflow result; read-back required'
            save(path, state)
        save(path, state)
        return state


def reconcile(path: Path, row_id: str, result: dict) -> None:
    with locked(path):
        state = read_record(path)
        row = next(r for r in state['rows'] if r['id'] == row_id)
        if not row.get('inflight'):
            raise ValueError('row has no uncertain effect to reconcile')
        if result.get('confirmed') is True and result.get('receipt') and result.get('target') == row.get('target'):
            row.update(state='complete', receipt=dict(result, confirmed_at=now()), inflight=None, error=None)
        elif result.get('absent') is True and result.get('checked'):
            row.update(inflight=None, error='absence verified; approved workflow may retry')
        else:
            raise ValueError('reconciliation requires read-back receipt or verified absence')
        save(path, state)


def terminal(state: dict) -> None:
    validate_rows(state)
    if any(r.get('inflight') or r.get('scope') != row_scope(r) or r.get('state') not in {'complete', 'declined'} for r in state['rows']):
        raise ValueError('pending routes prevent retention filing')


def repair_text(text: str, referent: Path, old: Path, new: Path, root: Path) -> str:
    old_root = old.relative_to(root).as_posix()
    new_root = new.relative_to(root).as_posix()
    old_rel = os.path.relpath(old, referent.parent)
    new_rel = os.path.relpath(new, referent.parent)
    # Structured JSON/source metadata and ordinary Markdown/wiki path links.
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r'\s*(?:"archived_from"|archived_from)\s*:', line):
            continue
        for before, after in sorted({old_root: new_root, old_rel: new_rel, str(old): str(new)}.items(), key=lambda pair: -len(pair[0])):
            line = re.sub(r'(?<![\w/.-])' + re.escape(before) + r'(?=[\s"\]\)#|]|$)', lambda _: after, line)
        lines[i] = line
    return ''.join(lines)


def move_with_references(root: Path, old: Path, new: Path, references: list[Path]) -> Path:
    old = within(root, old); new = within(root, new)
    if not old.is_file():
        raise ValueError('source to retain is unavailable')
    if old == new:
        return old
    if new.exists() and (not new.is_file() or new.read_bytes() != old.read_bytes()):
        raise ValueError('retention collision: never overwrite a different source')
    refs = [within(root, ref) for ref in references]
    updates = {}
    for ref in refs:
        if not ref.is_file():
            raise ValueError('reference repair target unavailable')
        destination_ref = new if ref == old else ref
        text = ref.read_text()
        if ref == old:
            # Rebase relative Markdown links in the moved artifact. Root-relative
            # source metadata and archived_from retain their distinct meaning.
            def rebase(match):
                target = match.group(1)
                if target.startswith(('.', '..')) and '://' not in target:
                    path_part, separator, anchor = target.partition('#')
                    resolved = (old.parent / path_part).resolve()
                    target = os.path.relpath(resolved, new.parent) + (separator + anchor if separator else '')
                return '](' + target + ')'
            text = re.sub(r'\]\(([^)]+)\)', rebase, text)
        updates[destination_ref] = repair_text(text, destination_ref, old, new, root)
    new.parent.mkdir(parents=True, exist_ok=True)
    if not new.exists():
        # Exclusive creation rather than replace: a concurrent different source
        # must not be overwritten between collision check and filing.
        with new.open('xb') as stream:
            stream.write(old.read_bytes()); stream.flush(); os.fsync(stream.fileno())
    for ref, text in updates.items():
        atomic_write(ref, text)
    # Reference writes may fail above. Leave intake available on that failure.
    if new.read_bytes() != old.read_bytes() and new not in updates:
        raise ValueError('retained source differs from intake')
    old.unlink()
    return new


def file_source(root: Path, record: Path, source: Path, retained_folder: str,
                references: list[Path]) -> Path:
    root = root.resolve(); record = within(root, record)
    with locked(record):
        state = read_record(record); terminal(state)
        source = within(root / 'raw', within(root, source))
        folder = within(root / 'raw', root / retained_folder)
        new = folder / source.name
        refs = list(dict.fromkeys([record, *references]))
        return move_with_references(root, source, new, refs)


def finalize(root: Path, record: Path, references: list[Path]) -> Path:
    root = root.resolve(); record = within(root, record)
    with locked(record):
        state = read_record(record); terminal(state)
        if state['kind'] == 'meeting':
            state.update(status='absorbed', absorbed_at=state.get('absorbed_at') or now())
            save(record, state)
            return record
        destination = root / 'raw/derived' / record.name
        if record == destination:
            return record
        if destination.exists():
            raise ValueError('research artifact archive collision')
        if record.parent != root / 'output':
            raise ValueError('research artifacts must start in canonical output')
        for ref in references:
            if not within(root, ref).is_file():
                raise ValueError('reference repair target unavailable')
        state.update(status='absorbed', use='artifact', compile_mode='exclude',
                     absorbed_at=now(), archived_from=record.relative_to(root).as_posix())
        save(record, state)
        text = record.read_text()
        fields = dict(status='absorbed', use='artifact', compile_mode='exclude',
                      absorbed_at=state['absorbed_at'], archived_from=state['archived_from'])
        if text.startswith('---\n'):
            head, body = text[4:].split('\n---', 1)
            lines = [line for line in head.splitlines() if line.split(':', 1)[0] not in fields]
            text = '---\n' + '\n'.join(lines + [f'{k}: {v}' for k, v in fields.items()]) + '\n---' + body
        else:
            text = '---\n' + '\n'.join(f'{k}: {v}' for k, v in fields.items()) + '\n---\n\n' + text
        atomic_write(record, text)
        return move_with_references(root, record, destination, [record, *references])


def command_workflow(argv: list[str]) -> Callable[[dict], dict]:
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) for a in argv):
        raise ValueError('workflow must be an explicit argv array, never a shell string')
    def run(request: dict) -> dict:
        result = subprocess.run(argv, input=json.dumps(request), text=True,
                                capture_output=True, check=True)
        return json.loads(result.stdout)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    cap = sub.add_parser('capture')
    cap.add_argument('--input', type=Path, required=True, help='JSON identity/date/title/sources and optional template/event_url')
    for command in ('inspect', 'plan', 'execute', 'reconcile', 'finalize', 'file-source', 'prepare-research'):
        p = sub.add_parser(command); p.add_argument('record', type=Path)
        if command in {'plan', 'reconcile', 'prepare-research'}:
            p.add_argument('--input', type=Path, required=True)
        if command == 'reconcile':
            p.add_argument('--row', required=True)
        if command == 'execute':
            p.add_argument('--workflows', type=Path, required=True, help='approved local workflow argv map by row kind')
        if command in {'finalize', 'file-source'}:
            p.add_argument('--reference', type=Path, action='append', default=[])
        if command == 'file-source':
            p.add_argument('--source', type=Path, required=True)
            p.add_argument('--retained-folder', required=True)
    args = parser.parse_args()
    root, _ = profile_schema.validate(args.profile)
    if args.command == 'capture':
        print(capture(args.profile, **json.loads(args.input.read_text()))); return
    path = within(root, args.record)
    if args.command == 'inspect':
        print(json.dumps(read_record(path), indent=2))
    elif args.command == 'prepare-research':
        initialize_research(path, sources_for(root, json.loads(args.input.read_text())))
    elif args.command == 'plan':
        set_plan(path, **json.loads(args.input.read_text()))
    elif args.command == 'execute':
        workflows = {kind: command_workflow(argv) for kind, argv in json.loads(args.workflows.read_text()).items()}
        print(json.dumps(execute(args.profile, path, workflows), indent=2))
    elif args.command == 'reconcile':
        reconcile(path, args.row, json.loads(args.input.read_text()))
    elif args.command == 'finalize':
        print(finalize(root, path, args.reference))
    elif args.command == 'file-source':
        print(file_source(root, path, args.source, args.retained_folder, args.reference))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration) as error:
        raise SystemExit(f'distribution refused: {error}')
