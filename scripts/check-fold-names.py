#!/usr/bin/env python3
"""Audit the pinned fold inventory and all remaining source-package names.

Run from the repository root. --write records the reviewed current occurrences;
the immutable input inventory remains the work list from the snapshot slice.
"""
import argparse
import csv
import io
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OLD = 'con' + 'tinuity'
PATTERN = re.compile(OLD, re.I)
HISTORICAL = {
    f'docs/{OLD}-inventory.tsv', f'docs/{OLD}-snapshot.md',
    'scripts/generate-fold-inventory.py', 'docs/fold-name-dispositions.tsv',
}


def disposition(path, line):
    if path in HISTORICAL:
        return 'retained: pinned snapshot provenance and inventory tooling'
    if path in {'scripts/lib/install_conflicts.py', 'tests/test_install_conflicts.py'}:
        return 'retained: detection-only refusal of the old standalone install and its fixtures (issue 62)'
    if path.startswith('tests/fixtures/session-release/'):
        return 'retained: isolated old archive/signing fixture; release integration is issue 64'
    if path in {'docs/architecture/session/runtime.html',
                'docs/architecture/session/runtime.architecture.json',
                'tests/test_public_documentation.py'} and re.search(
                    r'https://github\.com/coreyfloyd/' + OLD + r'(?:\.git|/(?:blob|tree)/[0-9a-f]{40}|["<])', line):
        return 'retained: immutable imported architecture source attribution'
    return None


def audit():
    inventory = ROOT / f'docs/{OLD}-inventory.tsv'
    with inventory.open() as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    assert rows and all(row['disposition'] and row['slice'] in {'59', '62', '64'} for row in rows)
    files = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
    ).decode().split('\0')
    current, unhandled = [], []
    for relative in sorted(set(files) - {''}):
        path = ROOT / relative
        if relative == 'docs/fold-name-dispositions.tsv' or not path.is_file():
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeError:
            continue
        hits = [(0, relative)] if PATTERN.search(relative) else []
        hits += [(number, line) for number, line in enumerate(lines, 1) if PATTERN.search(line)]
        for number, line in hits:
            reason = disposition(relative, line)
            current.append((relative, number, reason or 'UNHANDLED'))
            if reason is None:
                unhandled.append(f'{relative}:{number}')
    return rows, current, unhandled


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    rows, current, unhandled = audit()
    if args.write:
        output = io.StringIO()
        writer = csv.writer(output, delimiter='\t', lineterminator='\n')
        writer.writerow(['current_path', 'line', 'disposition'])
        writer.writerows(current)
        (ROOT / 'docs/fold-name-dispositions.tsv').write_text(output.getvalue())
    print(f'{len(rows)} pinned inventory entries assigned; {len(current)} current hit lines reviewed; {len(unhandled)} unhandled')
    for hit in unhandled:
        print(hit)
    raise SystemExit(bool(unhandled))
