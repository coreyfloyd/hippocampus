#!/usr/bin/env python3
"""Black-box contract tests for the rule-target composer."""
import json
import pathlib
import subprocess
import tempfile
import unittest


COMPOSER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "compose_rules.py"
START = "<!-- hippocampus-rules:start -->"
END = "<!-- hippocampus-rules:end -->"


class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.root = self.base / "knowledge"
        self.rules = self.root / "context"
        self.rules.mkdir(parents=True)
        self.cross = self.rules / "cross-tool.md"
        self.development = self.rules / "development.md"
        self.extra = self.base / "mechanics.md"
        self.cross.write_text("cross-tool rule\n")
        self.development.write_text("development rule\n")
        self.extra.write_text("tool mechanic\n")
        self.targets = self.base / "targets"
        self.targets.mkdir()
        self.claude = self.targets / "claude.md"
        self.codex = self.targets / "codex.md"
        self.openclaw = self.targets / "openclaw.md"
        self.config = self.base / "targets.json"

    def write_config(self, targets, root=None):
        self.config.write_text(json.dumps({"knowledge_root": str(root or self.root), "targets": targets}))

    def target(self, tool, path, sources=None, extras=None):
        return {
            "tool": tool,
            "scope": "user",
            "file": str(path),
            "sources": [str(path) for path in (sources or [self.cross, self.development])],
            "extras": [str(path) for path in (extras or [self.extra])],
        }

    def compose(self, command="compose"):
        return subprocess.run(
            ["python3", str(COMPOSER), command, "--config", str(self.config)],
            capture_output=True,
            text=True,
        )

    def snapshot(self):
        return {path: path.read_bytes() for path in (self.claude, self.codex, self.openclaw)}

    def assert_unchanged(self, snapshot):
        self.assertEqual(snapshot, self.snapshot())

    def test_exact_forms_and_no_byte_change_rerun(self):
        self.write_config([
            self.target("claude", self.claude),
            self.target("codex", self.codex),
            self.target("openclaw", self.openclaw),
        ])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in (self.claude, self.codex, self.openclaw):
            self.assertIn(f"composer-owned: {target}", result.stdout)

        imports = (
            "<!-- hippocampus-rules: generated; do not hand-edit -->\n"
            f"@{self.cross}\n@{self.development}\n@{self.extra}\n"
        )
        generated = (
            f"<!-- hippocampus-rules: generated from {self.cross}, {self.development}, {self.extra}; do not hand-edit -->\n"
            "cross-tool rule\ndevelopment rule\ntool mechanic\n"
        )
        self.assertEqual(self.claude.read_text(), imports)
        self.assertEqual(self.codex.read_text(), generated)
        self.assertEqual(self.openclaw.read_text(), generated)
        before = self.snapshot()
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_unchanged(before)

    def test_user_owned_block_preserves_everything_else_and_refreshes(self):
        self.codex.write_text(f"before\n{START}\nold body\n{END}\nafter\n")
        self.write_config([self.target("codex", self.codex)])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"user-owned: {self.codex}", result.stdout)
        self.assertEqual(
            self.codex.read_text(),
            (
                f"before\n{START}\n"
                f"<!-- hippocampus-rules: generated from {self.cross}, {self.development}, {self.extra}; do not hand-edit -->\n"
                "cross-tool rule\ndevelopment rule\ntool mechanic\n"
                f"{END}\nafter\n"
            ),
        )
        self.cross.write_text("cross-tool rule revised\n")
        self.assertEqual(self.compose("refresh").returncode, 0)
        self.assertIn("cross-tool rule revised", self.codex.read_text())
        self.assertTrue(self.codex.read_text().startswith("before\n"))
        self.assertTrue(self.codex.read_text().endswith("after\n"))

    def seed_targets(self):
        self.write_config([self.target("claude", self.claude), self.target("codex", self.codex), self.target("openclaw", self.openclaw)])
        self.assertEqual(self.compose().returncode, 0)
        return self.snapshot()

    def test_missing_source_and_unavailable_root_leave_targets_byte_identical(self):
        before = self.seed_targets()
        missing = self.rules / "missing.md"
        self.write_config([self.target("claude", self.claude, [missing], [])])
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(missing), result.stderr)
        self.assert_unchanged(before)
        self.write_config([self.target("claude", self.claude, [self.cross], [])], self.base / "missing-root")
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("knowledge root unavailable", result.stderr)
        self.assert_unchanged(before)

    def test_malformed_or_unwritable_target_leaves_targets_byte_identical(self):
        before = self.seed_targets()
        malformed = self.targets / "malformed.md"
        malformed.write_text(f"custom\n{START}\nunterminated\n")
        self.write_config([self.target("claude", self.claude), self.target("codex", malformed)])
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed marked block", result.stderr)
        self.assert_unchanged(before)
        malformed.write_text(f"{START}\nfirst\n{END}\n{START}\nsecond\n{END}\n")
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed marked block", result.stderr)
        self.assert_unchanged(before)
        unwritable = self.targets / "not-a-file"
        unwritable.mkdir()
        self.write_config([self.target("claude", self.claude), self.target("codex", unwritable)])
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target cannot be written", result.stderr)
        self.assert_unchanged(before)

    def test_no_size_limit(self):
        large = self.rules / "large.md"
        large.write_text("x" * 65536 + "\n")
        target = self.targets / "large.md"
        self.write_config([self.target("codex", target, [large], [])])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(target.stat().st_size, 65536)


if __name__ == "__main__":
    unittest.main()
