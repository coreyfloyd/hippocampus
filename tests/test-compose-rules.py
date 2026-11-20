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
        self.second_codex = self.targets / "second-codex.md"
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
        return {path: path.read_bytes() for path in (self.claude, self.codex, self.second_codex)}

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

    def test_check_reports_missing_changed_and_clean_targets_without_writes(self):
        self.write_config([self.target("codex", self.codex)])
        missing = self.compose("check")
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn("drift", missing.stderr)
        self.assertFalse(self.codex.exists())
        self.assertEqual(self.compose().returncode, 0)
        before = self.codex.read_bytes()
        self.assertEqual(self.compose("check").returncode, 0)
        self.cross.write_text("changed source\n")
        changed = self.compose("check")
        self.assertEqual(changed.returncode, 1, changed.stderr)
        self.assertIn(str(self.codex), changed.stderr)
        self.assertEqual(self.codex.read_bytes(), before)
        self.assertEqual(self.compose("refresh").returncode, 0)
        self.assertEqual(self.compose("check").returncode, 0)

    def test_check_reads_read_only_targets_and_directories_without_writes(self):
        self.write_config([self.target("codex", self.codex)])
        self.assertEqual(self.compose().returncode, 0)
        before = self.codex.read_bytes()
        for file_mode, directory_mode in ((0o444, 0o755), (0o644, 0o555), (0o444, 0o555)):
            with self.subTest(file_mode=file_mode, directory_mode=directory_mode):
                self.cross.write_text("cross-tool rule\n")
                self.codex.chmod(file_mode)
                self.targets.chmod(directory_mode)
                try:
                    clean = self.compose("check")
                    self.assertEqual(clean.returncode, 0, clean.stderr)
                    self.cross.write_text("changed source\n")
                    drift = self.compose("check")
                    self.assertEqual(drift.returncode, 1, drift.stderr)
                    self.assertIn("drift", drift.stderr)
                    self.assertIn(str(self.codex.resolve()), drift.stderr)
                    self.assertEqual(self.codex.read_bytes(), before)
                    self.assertEqual(self.codex.stat().st_mode & 0o777, file_mode)
                    self.assertEqual(self.targets.stat().st_mode & 0o777, directory_mode)
                    self.assertEqual(list(self.targets.iterdir()), [self.codex])
                finally:
                    self.targets.chmod(0o755)
                    self.codex.chmod(0o644)

    def test_check_missing_targets_report_drift_without_requiring_writable_parents(self):
        self.targets.chmod(0o555)
        try:
            for target in (self.codex, self.targets / "missing-parent" / "AGENTS.md"):
                with self.subTest(target=target):
                    self.write_config([self.target("codex", target)])
                    result = self.compose("check")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("drift", result.stderr)
                    self.assertIn(str(target.resolve()), result.stderr)
                    self.assertFalse(target.exists())
                    self.assertEqual(list(self.targets.iterdir()), [])
        finally:
            self.targets.chmod(0o755)

    def profile(self, routing, path=None, setting=""):
        """A controlled knowledge profile whose Lesson routing section holds ``routing``."""
        path = path or self.base / "profile.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        section = "" if routing is None else "\n## Lesson routing\n\n" + routing
        path.write_text("---\nprofile_version: 4\n" + setting + "---\n\nLocal policy.\n" + section)
        return path

    def environment(self, **values):
        env = {**os.environ, "XDG_CONFIG_HOME": str(self.base / "unused-config"), **values}
        env.pop("HIPPOCAMPUS_ROUTING", None)
        return env

    def surfaces(self, path, profile=None, env=None):
        args = ["python3", str(COMPOSER), "surfaces", "--source", str(path)]
        if profile is not None:
            args += ["--profile", str(profile)]
        return subprocess.run(args, capture_output=True, text=True, env=env or self.environment())

    def test_absent_empty_and_generated_source_mappings(self):
        profile = self.profile('''### Routing

```yaml
Produced surfaces:
  knowledge/context/cross-tool.md:
    - path: targets/codex.md
      regeneration command: "python3 compose_rules.py refresh --config targets.json"
    - path: targets/claude.md
      regeneration command: "python3 compose_rules.py refresh --config targets.json"
  knowledge/context/development.md: []
```
''')
        for source in (self.extra, self.development):
            result = self.surfaces(source, profile)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"sources": [str(source.resolve())], "surfaces": []})
        source = self.surfaces(self.cross, profile)
        generated = self.surfaces(self.codex, profile)
        self.assertEqual(source.returncode, 0, source.stderr)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(json.loads(source.stdout), json.loads(generated.stdout))
        mapping = json.loads(source.stdout)
        self.assertEqual(mapping["sources"], [str(self.cross.resolve())])
        self.assertEqual([row["path"] for row in mapping["surfaces"]], [str(self.codex.resolve()), str(self.claude.resolve())])
        self.assertTrue(all(row["regeneration command"] for row in mapping["surfaces"]))
        self.assertFalse(self.codex.exists())  # Lookup never runs the declared command.

    def test_profile_discovery_and_path_aliases(self):
        profile = self.profile('Produced surfaces:\n  "$RULE_SOURCE":\n    - path: "../targets/codex.md"\n'
                               '      regeneration command: "compose rules"\n', self.base / "hippocampus" / "profile.md")
        alias = self.base / "source-link.md"
        alias.symlink_to(self.cross)
        env = self.environment(XDG_CONFIG_HOME=str(self.base), RULE_SOURCE=str(self.cross.resolve()))
        result = self.surfaces(alias, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sources"], [str(self.cross.resolve())])
        self.assertEqual(json.loads(result.stdout)["surfaces"][0]["path"], str(self.codex.resolve()))
        env["XDG_CONFIG_HOME"] = str(self.base / "unused")
        self.assertEqual(self.surfaces(alias, profile, env=env).returncode, 0)

    def test_a_retired_routing_owner_is_refused(self):
        profile = self.profile("", self.base / "hippocampus" / "profile.md")
        for retired in ("file", "environment"):
            env = self.environment(XDG_CONFIG_HOME=str(self.base))
            if retired == "file":
                (profile.parent / "routing.md").write_text("Produced surfaces:\n")
            else:
                (profile.parent / "routing.md").unlink()
                env["HIPPOCAMPUS_ROUTING"] = str(self.base / "elsewhere.md")
            result = self.surfaces(self.cross, env=env)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("run hippocampus-set-up", result.stderr)
            if retired == "environment":
                self.assertIn("unset HIPPOCAMPUS_ROUTING", result.stderr)
                self.assertIn("does not exist", result.stderr)

    def test_missing_profile_section_or_other_section_produces_nothing(self):
        other = "\n## Other policy\n\nProduced surfaces:\n  rules.md:\n    - path: elsewhere.md\n"
        for profile in (self.base / "absent.md", self.profile(None), self.profile("### Routing\nOther instructions.\n"),
                        self.profile("lesson-policy: apply\n" + other)):
            result = self.surfaces(self.cross, profile)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["surfaces"], [])

    def test_malformed_mapping_or_profile_fails_instead_of_claiming_no_surfaces(self):
        for entry in ("    - path: targets/codex.md\n", "    - path: targets/codex.md\n      regeneration command: \"\"\n"):
            result = self.surfaces(self.cross, self.profile("Produced surfaces:\n  rules.md:\n" + entry))
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("routing", result.stderr)
        twice = self.profile("lesson-policy: apply\n\n## Lesson routing\n\nlesson-policy: propose\n")
        for profile in (twice, self.profile(None, setting="auto_apply: yes\n")):
            result = self.surfaces(self.cross, profile)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("knowledge profile", result.stderr)

    def test_unknown_tool_prevents_every_write(self):
        self.write_config([
            self.target("codex", self.codex),
            self.target("unknown-tool", self.second_codex),
        ])
        result = self.compose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported tool", result.stderr)
        self.assertFalse(self.codex.exists())
        self.assertFalse(self.second_codex.exists())

    def test_exact_forms_and_no_byte_change_rerun(self):
        self.write_config([
            self.target("claude", self.claude),
            self.target("codex", self.codex),
            self.target("codex", self.second_codex),
        ])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in (self.claude, self.codex, self.second_codex):
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
        self.assertEqual(self.second_codex.read_text(), generated)
        before = self.snapshot()
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_unchanged(before)

    def test_literal_render_is_per_target_and_preserves_complete_ordered_bodies(self):
        bodies = [b"# First\r\n\r\n@authored-reference\r\n", "# Second\nUnicode: café".encode(), b"# Mechanics\n"]
        sources = [self.cross, self.development, self.extra]
        for source, body in zip(sources, bodies):
            source.write_bytes(body)
        imported = self.targets / "claude-imports.md"
        literal_targets = [self.target(tool, path) | {"render": "literal"}
                           for tool, path in (("claude", self.claude), ("codex", self.codex), ("codex", self.second_codex))]
        self.write_config([self.target("claude", imported), *literal_targets])
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = self.generated_header(sources).encode() + bodies[0] + bodies[1] + b"\n" + bodies[2]
        for path in (self.claude, self.codex, self.second_codex):
            self.assertEqual(path.read_bytes(), expected)
        self.assertEqual(imported.read_bytes(),
                         b"<!-- hippocampus-rules: generated; do not hand-edit -->\n"
                         + b"".join(f"@{source}\n".encode() for source in sources))
        before = self.snapshot()
        mtimes = {path: path.stat().st_mtime_ns for path in before}
        for command in ("check", "compose", "refresh"):
            result = self.compose(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_unchanged(before)
            self.assertEqual(mtimes, {path: path.stat().st_mtime_ns for path in before})

    def test_literal_refresh_preserves_user_content_and_reports_drift(self):
        self.claude.write_bytes(b"user prefix\r\n")
        self.write_config([self.target("claude", self.claude) | {"render": "literal"}])
        self.assertEqual(self.compose().returncode, 0)
        start, end = self.block_markers(self.claude)
        suffix = b"user suffix\r\n"
        self.claude.write_bytes(self.claude.read_bytes() + suffix)
        self.cross.write_bytes(b"# Revised\ncomplete body\n")
        before = self.claude.read_bytes()
        self.assertEqual(self.compose("check").returncode, 1)
        self.assertEqual(self.claude.read_bytes(), before)
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (b"user prefix\r\n" + start.encode() + b"\n"
                    + self.generated_header([self.cross, self.development, self.extra]).encode()
                    + b"# Revised\ncomplete body\ndevelopment rule\ntool mechanic\n"
                    + end.encode() + b"\n" + suffix)
        self.assertEqual(self.claude.read_bytes(), expected)
        self.assertEqual(self.compose("check").returncode, 0)

    def test_invalid_render_fails_before_any_write(self):
        for invalid in (None, "", "imports", "Literal", False, [], {}):
            for command in ("compose", "refresh", "check"):
                with self.subTest(render=invalid, command=command):
                    self.write_config([self.target("codex", self.codex),
                                       self.target("claude", self.claude) | {"render": invalid}])
                    result = self.compose(command)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("render", result.stderr)
                    self.assertFalse(self.codex.exists())
                    self.assertFalse(self.claude.exists())

    def test_literal_missing_source_and_overlap_leave_all_targets_untouched(self):
        self.write_config([self.target("claude", self.claude) | {"render": "literal"},
                           self.target("codex", self.codex)])
        self.assertEqual(self.compose().returncode, 0)
        before = {path: path.read_bytes() for path in (self.claude, self.codex)}
        self.cross.write_text("changed source\n")
        for source, error in ((self.root / "missing.md", "missing"), (self.codex, "overlaps")):
            for command in ("compose", "refresh", "check"):
                with self.subTest(source=source, command=command):
                    self.write_config([self.target("codex", self.codex),
                                       self.target("claude", self.claude, [source]) | {"render": "literal"}])
                    result = self.compose(command)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stderr)
                    self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_switching_default_and_literal_keeps_composer_ownership(self):
        for render in ("default", "literal", "default"):
            self.write_config([self.target("claude", self.claude) | {"render": render}])
            result = self.compose()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("composer-owned:", result.stdout)
            expected = (self.generated_header([self.cross, self.development, self.extra])
                        + "cross-tool rule\ndevelopment rule\ntool mechanic\n") if render == "literal" else (
                            "<!-- hippocampus-rules: generated; do not hand-edit -->\n"
                            f"@{self.cross}\n@{self.development}\n@{self.extra}\n")
            self.assertEqual(self.claude.read_text(), expected)

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
        alias.symlink_to(self.second_codex)
        sources = [
            self.second_codex,
            self.targets / ".." / "targets" / "second-codex.md",
            alias,
            pathlib.Path("..") / "targets" / "second-codex.md",
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
                                self.target("codex", self.second_codex),
                            ]
                            targets[source_owner][field] = [str(source)]
                            self.write_config(targets)
                            result = self.compose(command)
                            self.assert_unchanged(before)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("configuration:", result.stderr)
                            self.assertIn(f"target {self.second_codex.resolve()}", result.stderr)
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
            self.target("codex", self.second_codex, sources, extras),
        ])

        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_header = self.generated_header([*sources, *extras])
        self.assertTrue(self.codex.read_text().startswith(expected_header))
        self.assertTrue(self.second_codex.read_text().startswith(expected_header))

        before = {target: target.read_bytes() for target in (self.codex, self.second_codex)}
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {target: target.read_bytes() for target in (self.codex, self.second_codex)})

        cross.write_text("new cross rule\n")
        result = self.compose("refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in (self.codex, self.second_codex):
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
        for tool, target in (("claude", self.claude), ("codex", self.codex), ("codex", self.second_codex)):
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
        for tool, target in (("claude", self.claude), ("codex", self.codex), ("codex", self.second_codex)):
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
        self.write_config([self.target("claude", self.claude), self.target("codex", self.codex), self.target("codex", self.second_codex)])
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

    def test_unreadable_source_leaves_targets_byte_identical(self):
        before = self.seed_targets()
        self.cross.write_text("revised rule\n")
        unreadable = self.rules / "unreadable.md"
        unreadable.write_text("private extra\n")
        unreadable.chmod(0o000)
        try:
            self.write_config([self.target("claude", self.claude), self.target("codex", self.codex, [self.cross], [unreadable])])
            result = self.compose()
        finally:
            unreadable.chmod(0o644)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(unreadable), result.stderr)
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
        self.write_config([self.target("codex", self.claude), self.target("codex", self.codex), self.target("codex", self.second_codex)])
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
        self.write_config([self.target("codex", self.claude), self.target("codex", self.codex), self.target("codex", self.second_codex)])
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
