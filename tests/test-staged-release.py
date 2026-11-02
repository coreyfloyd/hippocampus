"""The staged source package must never archive the enclosing repository."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StagedReleaseTests(unittest.TestCase):
    def test_staged_release_refuses_before_signing_or_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'release'
            env = dict(os.environ)
            env.pop('CONTINUITY_GPG_KEY', None)
            result = subprocess.run(
                ['bash', str(ROOT / 'continuity/scripts/build-release.sh'), str(output)],
                cwd=directory, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('hippocampus#64', result.stderr)
            self.assertIn('staged snapshot', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
