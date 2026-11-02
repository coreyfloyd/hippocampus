#!/usr/bin/env python3
"""Generate package versions from VERSION; --check refuses metadata drift."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        parser.error('VERSION must contain a release version MAJOR.MINOR.PATCH')
    path = ROOT / '.claude-plugin/plugin.json'
    metadata = json.loads(path.read_text())
    if args.check:
        if metadata.get('version') != version:
            print('version drift: .claude-plugin/plugin.json; run python3 scripts/generate-release-metadata.py', file=sys.stderr)
            return 1
    else:
        metadata['version'] = version
        path.write_text(json.dumps(metadata, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
