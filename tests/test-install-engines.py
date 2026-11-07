"""Verify the actual release installed into an isolated home."""
from pathlib import Path
import os
import re
import sys
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


    def test_installed_skills_have_their_scripts_and_engines_are_manifested(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = dict(os.environ, HOME=directory, CODEX_HOME=str(home / '.codex'))
            result = subprocess.run(['bash', str(ROOT / 'install.sh')],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            runtime = home / '.local/share/hippocampus/current'
            shipped = {path.name for path in runtime.rglob('*') if path.is_file()}
            script_name = re.compile(r'(?<![\w.-])([\w./<>-]+\.(?:sh|py|mjs))\b')
            for client in ('.claude', '.codex'):
                for skill in (home / client / 'skills').iterdir():
                    text = (skill / 'SKILL.md').read_text()
                    for match in script_name.finditer(text):
                        token = match.group(1).strip('<>')
                        name = Path(token).name
                        if name == 'setup.py':
                            continue  # a project marker, not a package engine
                        self.assertIn(name, shipped, f'{client}/{skill.name}: missing {token}')
                        if token.startswith('../'):
                            self.assertTrue((skill.resolve() / token).is_file(),
                                            f'{client}/{skill.name}: missing relative script {token}')
                        elif token.startswith('scripts/'):
                            # Instructions may resolve scripts within another named
                            # skill (the checklist explicitly names its checkpoint skill).
                            candidates = [runtime / token, skill.resolve() / token]
                            candidates.extend(runtime.glob('skills/*/' + token))
                            self.assertTrue(any(path.is_file() for path in candidates),
                                            f'{client}/{skill.name}: missing script path {token}')
            for relative in ('scripts/lib/handoff.py', 'scripts/lib/checklist.py',
                             'skills/hippocampus-set-up/scripts/profile.py'):
                result = subprocess.run([sys.executable, str(runtime / relative), '--help'],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for relative in ('hooks/hooks.json', 'INTERFACE.md'):
                self.assertTrue((runtime / relative).is_file(), relative)
            engine = runtime / 'scripts/lib/handoff.py'
            engine.write_text(engine.read_text() + '\n# modified installed engine\n')
            result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--verify'],
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('current manifest hash', result.stderr)


if __name__ == '__main__':
    unittest.main()
