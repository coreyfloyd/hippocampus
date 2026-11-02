#!/usr/bin/env python3
"""Install/uninstall the nine continuity skills and Codex hooks in one action."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import sys

from lib import codex_trust as trust

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ('checkpoint','pickup','checklist','handoff-prompt','wip','improve-harness','slim-harness','setup','sweep')
REGISTRATIONS = (('SessionStart','post-compact',None), ('PreCompact','pre-compact',None),
                 ('UserPromptSubmit','context-guard',None), ('PostToolUse','ledger-record',None),
                 ('Stop','guard-decide',None), ('PostToolUse','checklist-nudge','Bash'),
                 ('PreToolUse','actor-guard','Bash'))


def registrations(package):
    hooks = {}
    for event, operation, matcher in REGISTRATIONS:
        group = {'hooks':[{'type':'command', 'command':'python3 '+shlex.quote(str(package/'scripts/codex-hook.py'))+' '+operation,'timeout':10}]}
        if matcher is not None:
            group['matcher'] = matcher
        hooks.setdefault(event,[]).append(group)
    return hooks


def read_hooks(path):
    if not path.exists():
        return {'hooks':{}}
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or not isinstance(value.get('hooks',{}),dict):
        raise ValueError('existing hooks.json must hold an object of hook groups')
    value.setdefault('hooks',{})
    return value


def remove_managed(hooks, managed):
    result=copy.deepcopy(hooks)
    for event, groups in managed.items():
        keys={trust.handler_key(h) for g in groups for h in g['hooks']}
        remaining=[]
        for group in result['hooks'].get(event,[]):
            group=copy.deepcopy(group)
            group['hooks']=[h for h in group['hooks'] if (h.get('type'),h.get('command')) not in keys]
            if group['hooks']:
                remaining.append(group)
        if remaining:
            result['hooks'][event]=remaining
        else:
            result['hooks'].pop(event,None)
    return result


def assignment_key(line):
    """Decode a single TOML assignment key without interpreting its value."""
    match=re.match(r'''^\s*("(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)\s*=''', line)
    if not match:
        return None
    key=match.group(1)
    if key.startswith('"'):
        # JSON shares TOML's basic-key escapes except the eight-digit Unicode form.
        key=re.sub(r'\\(?:U([0-9a-fA-F]{8})|.)',
                   lambda escape: json.dumps(chr(int(escape.group(1), 16)))[1:-1]
                   if escape.group(1) else escape.group(0), key)
        try:
            return json.loads(key)
        except ValueError:
            return None
    return key[1:-1] if key.startswith("'") else key


def remove_trust(text, keys, replacements=None):
    """Remove owned tables, or refresh their hash while retaining user values."""
    lines=trust.config_lines(text); result=[];skip=False
    quote=None; depth=0; escaped=False
    preserve_table=False; preserve_value=False
    for line in lines:
        if quote is None and depth == 0:
            if line.lstrip().startswith('['):
                key=trust.state_key_from_header(line.strip())
                skip=key in keys
                preserve_table=skip and replacements is not None and key in replacements
                if skip:
                    if replacements is not None and key in replacements:
                        ending=trust.config_line_ending(line) or '\n'
                        result.extend((line if line.endswith('\n') else line + ending,
                                       f'trusted_hash = {json.dumps(replacements[key])}' + ending))
                    continue
            if not skip or not re.match(r'^\s*[^#\s][^=]*=', line):
                result.append(line)
                continue
            preserve_value=preserve_table and assignment_key(line) != 'trusted_hash'
        if preserve_value:
            result.append(line)
        # Outside strings, comments and blank lines survive even within arrays.
        if quote is None and (not line.strip() or line.lstrip().startswith('#')):
            if not preserve_value:
                result.append(line)
            continue
        # Follow the complete value, so continuation lines cannot become tables.
        index=0
        while index < len(line):
            char=line[index]
            if quote is not None:
                if escaped:
                    escaped=False
                elif char == '\\' and quote[0] == '"':
                    escaped=True
                elif line.startswith(quote, index):
                    width=len(quote)
                    if width == 3:
                        # TOML permits one or two literal quote characters before a closing triple.
                        while index + width < len(line) and line[index + width] == quote[0]:
                            width += 1
                    quote=None
                    index += width
                    continue
            elif char == '#':
                # Keep trailing comments as standalone lines, excluding string content.
                indent=line[:len(line) - len(line.lstrip())]
                if not preserve_value:
                    result.append(indent + line[index:])
                break
            elif char in ('"', "'"):
                quote=char * 3 if line.startswith(char * 3, index) else char
                index += len(quote)
                continue
            elif char in '[{':
                depth += 1
            elif char in ']}':
                depth -= 1
            index += 1
    return ''.join(result)


def relocate_trust(original, cleaned, config_text, target):
    """Keep existing trust attached to the same definition when group indexes move.

    This never approves a foreign hook. Only an exact trusted_hash from that
    hook's original state table may move to its new discovery key.
    """
    trusted = {}
    section = None
    for line in config_text.splitlines():
        if line.lstrip().startswith('['):
            section = trust.state_key_from_header(line.strip())
        elif section and re.match(r'^\s*trusted_hash\s*=', line):
            value = line.split('=', 1)[1].strip()
            try:
                trusted[section] = json.loads(value)
            except ValueError:
                pass
    relocated = {}
    for event, groups in cleaned['hooks'].items():
        for gi, group in enumerate(groups):
            for hi, handler in enumerate(group['hooks']):
                if handler.get('type') != 'command' or not isinstance(handler.get('timeout'), int):
                    continue
                newkey = f'{os.path.realpath(target)}:{trust.event_label(event)}:{gi}:{hi}'
                for oi, oldgroup in enumerate(original['hooks'].get(event, [])):
                    for oj, oldhandler in enumerate(oldgroup['hooks']):
                        oldkey = f'{os.path.realpath(target)}:{trust.event_label(event)}:{oi}:{oj}'
                        if oldhandler == handler and oldgroup.get('matcher') == group.get('matcher'):
                            digest = trust.hook_hash(event, oldgroup, oldhandler)
                            if trusted.get(oldkey) == digest:
                                relocated[newkey] = digest
    return relocated


def copy_package(destination):
    destination.mkdir(parents=True)
    for name in ('scripts','skills','hooks'):
        shutil.copytree(ROOT/name,destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('INTERFACE.md','LICENSE'):
        shutil.copy2(ROOT/name,destination/name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home',type=Path,default=Path(os.environ.get('CODEX_HOME') or os.path.expanduser('~/.codex')))
    parser.add_argument('--codex',default=shutil.which('codex'),help='Codex executable used to verify persisted hook trust')
    parser.add_argument('--uninstall',action='store_true')
    args=parser.parse_args()
    if not args.codex and not args.uninstall:
        raise ValueError('codex executable required for hooks/list trust verification')
    home=args.codex_home.expanduser().resolve(); package=home/'continuity'; skills=home/'skills'
    target=home/'hooks.json';config=home/'config.toml'; manifest=home/'continuity-install.json'
    saved=json.loads(manifest.read_text()) if manifest.exists() else None
    managed=saved['hooks'] if saved else registrations(package)
    # Refuse collisions before writing anything; reinstall owns only its own links.
    for name in SKILLS:
        path=skills/name
        if os.path.lexists(path) and not (path.is_symlink() and path.resolve()==package/'skills'/name):
            raise ValueError('existing skill '+str(path)+' is not owned by continuity')
    if package.exists() and not saved:
        raise ValueError('existing package directory is not owned by continuity')
    old_hooks=target.read_text() if target.exists() else None
    old_config=config.read_bytes().decode('utf-8') if config.exists() else None
    hooks=read_hooks(target)
    cleaned=remove_managed(hooks,managed) if saved else hooks
    clean_config=remove_trust(old_config or '',set(saved['trust_keys'])) if saved else old_config or ''
    backup=home/'continuity-install-backup'
    if backup.exists():
        raise ValueError('an earlier install backup needs recovery before installing')
    newlinks=[]
    foreign_hashes = relocate_trust(hooks, cleaned, old_config or '', target) if saved else {}
    if args.uninstall:
        if not saved:
            print('continuity is not installed');return 0
        trust.atomic_write(target,json.dumps(cleaned,indent=2)+'\n')
        trust.atomic_write(config,trust.update_config_text(clean_config,foreign_hashes) if foreign_hashes else clean_config)
        for name in SKILLS:
            path=skills/name
            if path.is_symlink():path.unlink()
        try:
            shutil.rmtree(package)
        except FileNotFoundError:
            pass
        manifest.unlink()
        print('continuity removed from Codex; handoffs and checklist state retained')
        return 0
    home.mkdir(parents=True,exist_ok=True);skills.mkdir(exist_ok=True)
    installed=trust.merge_hooks(registrations(package),cleaned)
    hashes=trust.managed_state(registrations(package),installed,target)
    if saved:
        # Reuse owned table positions so preserved separators are not duplicated.
        clean_config=remove_trust(old_config or '',set(saved['trust_keys']),hashes)
    try:
        if package.exists():package.rename(backup)
        copy_package(package)
        for name in SKILLS:
            path=skills/name
            if not path.is_symlink():
                path.symlink_to(package/'skills'/name,target_is_directory=True);newlinks.append(path)
        trust.atomic_write(target,json.dumps(installed,indent=2)+'\n')
        trust.atomic_write(config,trust.update_config_text(clean_config,{**foreign_hashes,**hashes}))
        trust.verify_with_hooks_list(args.codex,home,home,hashes)
        trust.atomic_write(manifest,json.dumps({'hooks':registrations(package),'trust_keys':list(hashes)},indent=2)+'\n')
    except Exception:
        trust.restore_file(target,old_hooks);trust.restore_file(config,old_config)
        for link in newlinks:link.unlink()
        if package.exists():shutil.rmtree(package)
        if backup.exists():backup.rename(package)
        raise
    if backup.exists():shutil.rmtree(backup)
    print('Installed nine continuity skills, six hooks, and the checklist actor guard; seven trusted handlers')
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as error:
        print('continuity install: '+str(error),file=sys.stderr)
        raise SystemExit(1)
