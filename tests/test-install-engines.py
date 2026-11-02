"""Verify the actual release installed into an isolated home."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstalledSkills(unittest.TestCase):
    def test_installer_preserves_foreign_generic_setup_skills(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = dict(os.environ, HOME=directory, CODEX_HOME=str(home / '.codex'))
            originals = []
            for client in ('.claude', '.codex'):
                path = home / client / 'skills/setup/SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text('---\nname: setup\n---\nUser-owned generic setup.\n')
                originals.append((path, path.read_bytes()))
            result = subprocess.run(['bash', str(ROOT / 'install.sh')],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for path, original in originals:
                self.assertFalse(path.parent.is_symlink())
                self.assertEqual(path.read_bytes(), original)
                installed = path.parent.parent / 'hippocampus-set-up'
                self.assertTrue(installed.is_symlink())
                self.assertIn('name: hippocampus-set-up\n', (installed / 'SKILL.md').read_text())


if __name__ == '__main__':
    unittest.main()
