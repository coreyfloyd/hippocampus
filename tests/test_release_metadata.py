"""Release metadata is derived from VERSION and drift blocks a release."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_metadata_generation_and_drift(tmp_path):
    shutil.copytree(ROOT / '.claude-plugin', tmp_path / '.claude-plugin')
    (tmp_path / 'scripts').mkdir()
    shutil.copy(ROOT / 'scripts/generate-release-metadata.py', tmp_path / 'scripts')
    version = (ROOT / 'VERSION').read_text().strip()
    (tmp_path / 'VERSION').write_text(version + '\n')
    script = tmp_path / 'scripts/generate-release-metadata.py'
    subprocess.run([sys.executable, str(script)], check=True)
    manifest = tmp_path / '.claude-plugin/plugin.json'
    assert json.loads(manifest.read_text())['version'] == version
    assert subprocess.run([sys.executable, str(script), '--check']).returncode == 0
    data = json.loads(manifest.read_text())
    data['version'] = version + '-drift'
    manifest.write_text(json.dumps(data))
    result = subprocess.run([sys.executable, str(script), '--check'], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'version drift' in result.stderr
    subprocess.run([sys.executable, str(script)], check=True)
    assert json.loads(manifest.read_text())['version'] == version
