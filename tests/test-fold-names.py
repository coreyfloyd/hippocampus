"""The combined package has one discovery name and one configuration home."""
from pathlib import Path
import json
import re
import unittest
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

class FoldNames(unittest.TestCase):
    def test_one_plain_name_per_skill_in_one_plugin(self):
        names = []
        for path in ROOT.glob('**/skills/*/SKILL.md'):
            name = re.search(r'^name: (.+)$', path.read_text(), re.M).group(1)
            self.assertEqual(name, path.parent.name)
            names.append(name)
        self.assertEqual(len(names), len(set(names)), 'duplicate skill name')
        self.assertIn('setup', names)
        self.assertNotIn('hippocampus-set-up', names)
        self.assertEqual(json.loads((ROOT / '.claude-plugin/plugin.json').read_text())['name'], 'hippocampus')
        self.assertTrue((ROOT / 'skills/checklist/SKILL.md').exists())

    def test_claude_invocations_use_plugin_namespace(self):
        names = [path.parent.name for path in ROOT.glob('skills/*/SKILL.md')]
        pattern = re.compile(r'(?<![\w./])/(?:' + '|'.join(names) + r')(?=[\s`"<:]|$)')
        for path in ROOT.glob('skills/*/SKILL.md'):
            self.assertIsNone(pattern.search(path.read_text()), str(path))

    def test_runtime_uses_new_configuration_and_state(self):
        source = (ROOT / 'scripts/lib/handoff.py').read_text()
        self.assertIn('HIPPOCAMPUS_CONFIG', source)
        self.assertIn('~/.local/state/hippocampus/handoffs', source)
        self.assertNotIn('CON' + 'TINUITY_CONFIG', source)
        self.assertIn('hippocampus/checklist-profile.md', (ROOT / 'scripts/lib/pickup_record.py').read_text())

    def test_snapshot_inventory_has_no_unhandled_name(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-fold-names.py')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_glossary_resolves_profiles_and_native_steps(self):
        text = (ROOT / 'docs/glossary.md').read_text()
        terms = re.findall(r'^\*\*([^*]+)\*\*:', text, re.M)
        self.assertEqual(len(terms), len(set(terms)))
        for term in ('Knowledge profile', 'Checklist profile', 'Knowledge root', 'Native step'):
            self.assertIn(term, terms)
        self.assertNotIn('Profile', terms)
        self.assertIn('There are two: `record` and `persist`', text)

if __name__ == '__main__':
    unittest.main()
