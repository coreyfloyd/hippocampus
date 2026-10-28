#!/usr/bin/env python3
"""Black-box contract tests for the rule-target composer."""
import json
import hashlib
import os
import pathlib
import runpy
import subprocess
import tempfile
import unittest
from unittest import mock


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

    def block_markers(self, path):
        digest = hashlib.sha256(os.fsencode(str(path.resolve()))).hexdigest()
        return (
            f"<!-- hippocampus-rules:block:start {digest} -->",
            f"<!-- hippocampus-rules:block:end {digest} -->",
        )

    def generated_header(self, sources):
        encoded_sources = json.dumps(
            [str(source) for source in sources],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return f"<!-- hippocampus-rules: generated from {encoded_sources}; do not hand-edit -->\n"

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
            self.assertIn(f"composer-owned: {target.resolve()}", result.stdout)

        imports = (
            "<!-- hippocampus-rules: generated; do not hand-edit -->\n"
            f"@{self.cross}\n@{self.development}\n@{self.extra}\n"
        )
        generated = (
            self.generated_header([self.cross, self.development, self.extra])
            + "cross-tool rule\ndevelopment rule\ntool mechanic\n"
        )
        self.assertEqual(self.claude.read_text(), imports)
        self.assertEqual(self.codex.read_text(), generated)
        self.assertEqual(self.openclaw.read_text(), generated)
        before = self.snapshot()
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_unchanged(before)

    def test_target_aliases_are_rejected_before_any_write(self):
        target = self.targets / "shared.md"
        alias = self.targets / ".." / "targets" / "shared.md"
        self.write_config([
            self.target("claude", alias),
            self.target("codex", target),
        ])
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate target", result.stderr)
        self.assertFalse(target.exists())

    def test_source_target_overlaps_are_rejected_before_any_write(self):
        before = self.seed_targets()
        self.cross.write_text("revised rule requiring target updates\n")
        alias = self.base / "source-alias.md"
        alias.symlink_to(self.openclaw)
        sources = [
            self.openclaw,
            self.targets / ".." / "targets" / "openclaw.md",
            alias,
            pathlib.Path("..") / "targets" / "openclaw.md",
        ]
        for source in sources:
            for field in ("sources", "extras"):
                for source_owner in (1, 2):
                    for command in ("compose", "refresh"):
                        with self.subTest(source=source, field=field, owner=source_owner, command=command):
                            for path, content in before.items():
                                path.write_bytes(content)
                            targets = [
                                self.target("claude", self.claude),
                                self.target("codex", self.codex),
                                self.target("openclaw", self.openclaw),
                            ]
                            targets[source_owner][field] = [str(source)]
                            self.write_config(targets)
                            result = self.compose(command)
                            self.assert_unchanged(before)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("configuration:", result.stderr)
                            self.assertIn(f"target {self.openclaw.resolve()}", result.stderr)
                            absolute_source = source if source.is_absolute() else self.root / source
                            self.assertIn(f"source {absolute_source}", result.stderr)
                            self.assertIn("overlaps", result.stderr)
                            self.assertEqual(result.stdout, "")
                            self.assertEqual(list(self.targets.glob(".hippocampus-rules-*")), [])

    def test_user_owned_block_preserves_everything_else_and_refreshes(self):
        start, end = self.block_markers(self.codex)
        self.codex.write_text(f"before\n{start}\nold body\n{end}\nafter\n")
        self.write_config([self.target("codex", self.codex)])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"user-owned: {self.codex.resolve()}", result.stdout)
        self.assertEqual(
            self.codex.read_text(),
            (
                f"before\n{start}\n"
                + self.generated_header([self.cross, self.development, self.extra])
                + "cross-tool rule\ndevelopment rule\ntool mechanic\n"
                f"{end}\nafter\n"
            ),
        )
        self.cross.write_text("cross-tool rule revised\n")
        self.assertEqual(self.compose("refresh").returncode, 0)
        self.assertIn("cross-tool rule revised", self.codex.read_text())
        self.assertTrue(self.codex.read_text().startswith("before\n"))
        self.assertTrue(self.codex.read_text().endswith("after\n"))

    def test_encoded_source_header_round_trips_special_paths_for_generated_targets(self):
        special_rules = self.root / "context, special rules"
        special_rules.mkdir()
        cross = special_rules / "cross-tool, source & notes.md"
        development = special_rules / "development rule [v2].md"
        extra = self.base / "tool, mechanics @2.md"
        cross.write_text("old cross rule\n")
        development.write_text("development rule\n")
        extra.write_text("extra rule\n")
        sources = [cross, development]
        extras = [extra]
        self.write_config([
            self.target("codex", self.codex, sources, extras),
            self.target("openclaw", self.openclaw, sources, extras),
        ])

        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_header = self.generated_header([*sources, *extras])
        self.assertTrue(self.codex.read_text().startswith(expected_header))
        self.assertTrue(self.openclaw.read_text().startswith(expected_header))

        before = {target: target.read_bytes() for target in (self.codex, self.openclaw)}
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {target: target.read_bytes() for target in (self.codex, self.openclaw)})

        cross.write_text("new cross rule\n")
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in (self.codex, self.openclaw):
            content = target.read_text()
            self.assertIn("new cross rule", content)
            self.assertNotIn("old cross rule", content)

    def test_user_header_that_the_composer_did_not_emit_remains_user_owned(self):
        original = (
            "<!-- hippocampus-rules: generated from [\"/manual/rules.md\", \"/manual/extra.md\"]; do not hand-edit -->\n"
            "user instruction\n"
        )
        self.codex.write_text(original)
        self.write_config([self.target("codex", self.codex)])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"user-owned: {self.codex.resolve()}", result.stdout)
        self.assertTrue(self.codex.read_text().startswith(original))
        self.assertIn("cross-tool rule", self.codex.read_text())

    def test_source_marker_text_does_not_become_a_block_delimiter(self):
        self.cross.write_text("rule documentation\n<!-- hippocampus-rules:start -->\nmore rules\n")
        self.codex.write_text("user instruction\n")
        self.write_config([self.target("codex", self.codex)])
        self.assertEqual(self.compose().returncode, 0)
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("more rules", self.codex.read_text())

    def test_malformed_delimiters_prevent_every_write_for_each_tool(self):
        before = self.seed_targets()
        self.cross.write_text("revised rule requiring every target to change\n")
        for tool, target in (("claude", self.claude), ("codex", self.codex), ("openclaw", self.openclaw)):
            start, end = self.block_markers(target)
            variant_start = start.replace(" -->", "-1 -->")
            variant_end = end.replace(" -->", "-1 -->")
            header = ("<!-- hippocampus-rules: generated; do not hand-edit -->\n"
                      if tool == "claude" else self.generated_header([self.cross, self.development, self.extra]))
            valid = f"{start}\n{header}stale rule\n{end}\n"
            shapes = {
                "two blocks": valid + valid,
                "start without end": f"{start}\nunterminated\n",
                "end without start": f"orphan\n{end}\n",
                "reversed": f"{end}\n{start}\n",
                "nested": f"{start}\n{valid}{end}\n",
                "variant block": valid + f"{variant_start}\nignored rule\n{variant_end}\n",
                "variant start": valid + f"{variant_start}\nunterminated\n",
                "variant end": valid + f"{variant_end}\n",
                "only variant block": f"{variant_start}\nold rule\n{variant_end}\n",
            }
            for shape, content in shapes.items():
                for command in ("compose", "refresh"):
                    with self.subTest(tool=tool, shape=shape, command=command):
                        for path, original in before.items():
                            path.write_bytes(original)
                        target.write_text("user instructions\n" + content)
                        snapshot = self.snapshot()
                        # The bad target comes last so earlier planned writes must be withheld.
                        targets = [self.target("codex", path) for path in before if path != target]
                        self.write_config([*targets, self.target(tool, target)])
                        result = self.compose(command)
                        self.assert_unchanged(snapshot)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(f"malformed marked block in target {target.resolve()}", result.stderr)
                        self.assertIn("marker", result.stderr)
                        self.assertEqual(result.stdout, "")
                        self.assertEqual(list(self.targets.glob(".hippocampus-rules-*")), [])

    def test_source_delimiters_prevent_every_write_for_rules_and_extras(self):
        before = self.seed_targets()
        for tool, target in (("claude", self.claude), ("codex", self.codex), ("openclaw", self.openclaw)):
            for marker_target in before:
                for delimiter in self.block_markers(marker_target):
                    for source in (self.cross, self.extra):
                        for command in ("compose", "refresh"):
                            with self.subTest(tool=tool, delimiter=delimiter, source=source, command=command):
                                for path, original in before.items():
                                    path.write_bytes(original)
                                self.cross.write_text("revised rule\n")
                                self.extra.write_text("revised extra\n")
                                source.write_text(f"rule text\n{delimiter}\nmore rules\n")
                                # Even an import-only target must validate its source text.
                                self.write_config([
                                    *[self.target("codex", path, [self.development], [self.development])
                                      for path in before if path != target],
                                    self.target(tool, target),
                                ])
                                result = self.compose(command)
                                self.assert_unchanged(before)
                                self.assertNotEqual(result.returncode, 0)
                                self.assertIn(f"source document {source}", result.stderr)
                                self.assertIn("delimiter line", result.stderr)
                                self.assertEqual(result.stdout, "")
                                self.assertEqual(list(self.targets.glob(".hippocampus-rules-*")), [])

    def test_replacement_preserves_existing_mode_and_new_target_uses_default_mode(self):
        self.write_config([self.target("codex", self.codex)])
        previous_umask = os.umask(0o022)
        try:
            initial = self.compose()
        finally:
            os.umask(previous_umask)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertEqual(self.codex.stat().st_mode & 0o777, 0o644)

        self.codex.chmod(0o640)
        self.cross.write_text("revised rule\n")
        refreshed = self.compose("refresh")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertEqual(self.codex.stat().st_mode & 0o777, 0o640)

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
        start, end = self.block_markers(malformed)
        malformed.write_text(f"custom\n{start}\nunterminated\n")
        self.write_config([self.target("claude", self.claude), self.target("codex", malformed)])
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed marked block", result.stderr)
        self.assert_unchanged(before)
        malformed.write_text(f"{start}\nfirst\n{end}\n{start}\nsecond\n{end}\n")
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

    def test_read_only_existing_target_prevents_every_write(self):
        before = self.seed_targets()
        self.write_config([self.target("codex", self.claude), self.target("codex", self.codex), self.target("openclaw", self.openclaw)])
        self.cross.write_text("revised rules requiring every target to change\n")
        self.codex.chmod(0o444)
        self.addCleanup(self.codex.chmod, 0o600)
        result = self.compose("refresh")
        self.assert_unchanged(before)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"target cannot be written: {self.codex.resolve()}", result.stderr)
        self.assertIn("not writable", result.stderr)
        self.assertEqual(list(self.targets.glob(".hippocampus-rules-*")), [])

    def test_later_replacement_failure_rolls_back_and_names_failed_target(self):
        before = self.seed_targets()
        self.write_config([self.target("codex", self.claude), self.target("codex", self.codex), self.target("openclaw", self.openclaw)])
        self.cross.write_text("revised rules requiring every target to change\n")
        composer = runpy.run_path(str(COMPOSER))
        replace = os.replace

        def fail_second_replacement(source, destination):
            if destination == self.codex.resolve():
                self.assertNotEqual(self.claude.read_bytes(), before[self.claude])
                raise PermissionError("replacement denied")
            return replace(source, destination)

        # Inject a filesystem failure after preflight, without platform-specific flags.
        with mock.patch.object(os, "replace", side_effect=fail_second_replacement):
            with self.assertRaises(composer["ComposeError"]) as raised:
                composer["compose"](self.config)
        self.assert_unchanged(before)
        self.assertEqual(
            str(raised.exception),
            f"target cannot be written: {self.codex.resolve()}: replacement denied",
        )
        self.assertEqual(list(self.targets.glob(".hippocampus-rules-*")), [])


if __name__ == "__main__":
    unittest.main()
