"""Generate the fixed cutover inventory from the two agreed git trees."""
import argparse
import collections
import csv
import io
from pathlib import Path
import re
import subprocess

BASE = '09d36f5a33e3d0a408ac5dee93b2138280331905'
SNAPSHOT = '5198d0567840694e71ddc20877c9a2c3415b0d80'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-repo', required=True, help='local clone containing the pinned source commit')
args = parser.parse_args()
pattern = re.compile('continuity', re.I)

def git(*args):
    return subprocess.check_output(['git', '-C', source_repo, *args])

def assignment(path, line):
    # Immutable source attribution is reviewed and retained by the rename slice.
    if re.search(r'github\.com/' + 'corey' + 'floyd/continuity/(?:blob|commit)/[0-9a-f]{7,40}', line):
        return 59, 'keep historical source attribution'
    if path in {'RELEASING.md', 'RELEASE_SIGNING_FINGERPRINT', 'scripts/build-release.sh', 'scripts/verify-release.sh'} or path.startswith(('tests/test_release', 'keys/')):
        return 64, 'replace package release naming and signing references'
    if path in {'INSTALLATION.md', 'scripts/install-codex.py', 'scripts/lib/codex_trust.py', '.github/workflows/test.yml'} or path.startswith(('tests/test_codex_adapter', 'tests/test_claude_plugin')):
        return 62, 'replace installer/plugin naming and update its fixtures'
    return 59, 'rename package/configuration/state/docs reference or fixture'

rows = []
for revision, prefix, source_repo in ((BASE, '', '.'), (SNAPSHOT, 'continuity/', args.source_repo)):
    for raw in git('ls-tree', '-r', '-z', '--name-only', revision).split(b'\0'):
        if not raw:
            continue
        path = raw.decode()
        for match in pattern.finditer(path):
            owner, action = assignment(path, path)
            rows.append([revision, prefix + path, 'path', 0, match.start() + 1, match.group(), owner, action])
        content = git('show', f'{revision}:{path}').decode('utf-8', errors='replace')
        for number, line in enumerate(content.splitlines(), 1):
            for match in pattern.finditer(line):
                owner, action = assignment(path, line)
                rows.append([revision, prefix + path, 'content', number, match.start() + 1, match.group(), owner, action])
rows.append([SNAPSHOT, 'continuity/', 'staging-prefix', 0, 1, 'continuity', 59, 'move staged files into final package directories; remove staging prefix'])
output = io.StringIO(newline='')
writer = csv.writer(output, delimiter='\t', lineterminator='\n')
writer.writerow(['revision', 'merged_path', 'kind', 'line', 'column', 'match', 'slice', 'disposition'])
writer.writerows(rows)
Path('docs/continuity-inventory.tsv').write_text(output.getvalue())
print(f'{len(rows)} entries; kinds: {dict(collections.Counter(row[2] for row in rows))}; slices: {dict(collections.Counter(row[6] for row in rows))}')
