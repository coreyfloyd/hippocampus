#!/usr/bin/env python3
"""Merge attended setup choices with validated replacement and failure rollback."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/lib'))
# Even a refused setup must not leave an import cache in a fresh package.
previous_bytecode_policy = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    import checklist
finally:
    sys.dont_write_bytecode = previous_bytecode_policy

FENCE = re.compile(r'^```checklist-profile\s*\n(.*?)^```\s*$', re.M | re.S)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-present', action='store_true', help='agent confirmed a live setup conversation')
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--bindings', required=True, help='JSON object of only the slot choices being changed')
    parser.add_argument('--record-read', help='command naming the user-owned read skill')
    args = parser.parse_args()
    if not args.user_present:
        raise ValueError('setup requires the user present; unattended setup stopped without writes')
    path = args.profile or Path(os.environ.get('CHECKLIST_USER_PROFILE') or
                               str(Path(os.environ.get('XDG_CONFIG_HOME') or '~/.config') / 'checklist/profile.md'))
    path = path.expanduser().resolve()
    original = path.read_text() if path.exists() else None
    match = None
    if original is None:
        profile = {'name': 'user'}
    elif path.suffix == '.json':
        profile = json.loads(original)
    else:
        matches = list(FENCE.finditer(original))
        if len(matches) != 1:
            raise ValueError('existing profile requires one checklist-profile fence; left unchanged')
        match = matches[0]
        profile = json.loads(match[1])
    if not isinstance(profile, dict):
        raise ValueError('profile must be an object')
    choices = json.loads(args.bindings)
    if not isinstance(choices, dict) or set(choices) - set(checklist.SLOTS):
        raise ValueError('bindings must be an object containing only the four slots')
    profile.setdefault('bindings', {}).update(choices)
    if args.record_read is not None:
        profile['record_read'] = {'command': args.record_read}
    encoded = json.dumps(profile, indent=2) + '\n'
    if path.suffix == '.json':
        text = encoded
    elif match:
        text = original[:match.start(1)] + encoded + original[match.end(1):]
    else:
        text = '# User profile\n\n```checklist-profile\n' + encoded + '```\n'
    # Load the rendered candidate too: section references must still resolve.
    # The temporary file has the same extension as the destination.
    # Only successful replacement commits these filesystem changes. Track each
    # directory separately so partial mkdir failures can also be rolled back.
    temporary = None
    created_directories = []
    committed = False
    try:
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            try:
                directory.mkdir()
            except FileExistsError:
                if not directory.is_dir():
                    raise
            else:
                created_directories.append(directory)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix=path.suffix, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        checklist.compose([checklist.load_profile(temporary)])
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
        committed = True
    finally:
        try:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        finally:
            if not committed:
                for directory in reversed(created_directories):
                    directory.rmdir()
    print(str(path))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print('setup: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
