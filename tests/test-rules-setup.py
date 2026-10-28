#!/usr/bin/env python3
"""Contract tests for the set-up rules and memory proposal helper."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "rules_setup.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("rules_setup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RulesSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.homes = {name: self.base / name for name in ("claude-code", "codex", "openclaw")}
        for name, home in self.homes.items():
            (home / "bin").mkdir(parents=True)
            executable = {"claude-code": "claude", "codex": "codex", "openclaw": "openclaw"}[name]
            binary = home / "bin" / executable
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)

    def test_skills_only_homes_do_not_configure_uninstalled_tools(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        for tool, home in self.homes.items():
            (home / "bin" / helper.TOOLS[tool]["binary"]).unlink()
            (home / "skills").mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(self.base / "empty-path")}):
            rows = helper.inspect_tools(self.homes)
            for row in rows:
                self.assertFalse(row["installed"], row["tool"])
                self.assertNotIn("target", row)
                self.assertNotIn("memory", row)
            value = helper.plan(rows, "thin", profile=profile)
            self.assertEqual(value["tools"], [])
            self.assertEqual([m["kind"] for m in value["mutation_list"]], ["profile"])
            helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
        self.assertEqual(helper.profile_reader().parse(profile)["rules"]["tools"], [])
        for home in self.homes.values():
            self.assertEqual(sorted(p.name for p in home.iterdir()), ["bin", "skills"])

    def test_codex_home_environment_controls_detection_targets_and_memory(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        user_home = self.base / "user-home"
        conventional = user_home / ".codex"
        conventional.mkdir(parents=True)
        (conventional / "AGENTS.md").write_text("keep conventional instructions\n")
        (conventional / "config.toml").write_text("features.memories = false\n")
        before = {p.name: p.read_bytes() for p in conventional.iterdir()}
        custom = self.homes["codex"]
        (custom / "config.toml").write_text("features.memories = true\n")
        with mock.patch.dict(os.environ, {"HOME": str(user_home), "CODEX_HOME": str(custom), "PATH": str(custom / "bin")}):
            self.assertEqual(helper.default_homes()["codex"], custom)
            rows = helper.inspect_tools()
            codex = next(r for r in rows if r["tool"] == "codex")
            self.assertTrue(codex["installed"])
            self.assertEqual(codex["target"]["file"], str(custom / "AGENTS.md"))
            self.assertEqual(codex["memory"]["settings_file"], str(custom / "config.toml"))
            self.assertEqual(codex["memory"]["state"], "on")
            value = helper.plan(rows, "thin", profile=profile)
            self.assertEqual([r["tool"] for r in value["tools"]], ["codex"])
            helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
            self.assertEqual(helper.plan(helper.inspect_tools(), "thin", profile=profile)["mutation_list"], [])
        self.assertIn("shared rule", (custom / "AGENTS.md").read_text())
        self.assertIs(tomllib.loads((custom / "config.toml").read_text())["features"]["memories"], False)
        choices = helper.profile_reader().parse(profile)["rules"]["tools"]
        self.assertEqual(choices, [{"tool": "codex", "rules_target": str(custom / "AGENTS.md"), "memory": "off"}])
        self.assertEqual({p.name: p.read_bytes() for p in conventional.iterdir()}, before)

    def configured_profile(self):
        root = self.base / "configured-knowledge"
        for name in ("context", "raw", "output", "docs"):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in ("log.md", "DECISIONS.md"):
            (root / "docs" / name).touch()
        (root / "context" / "rules.md").write_text("shared rule\n")
        (root / "context" / "development-rules.md").write_text("development rule\n")
        profile = self.base / "configured-profile.md"
        profile.write_text("---\nprofile_version: 4\nknowledge_root: " + str(root) + "\nwiki_enabled: false\noperation_log_file: docs/log.md\ndecision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Tasks\n---\npolicy\n")
        return root, profile

    def test_rules_changes_and_selected_override_are_reviewed(self):
        helper = load_helper()
        root, profile = self.configured_profile()
        first = helper.plan(self.describe(), "thin", profile=profile)
        helper.apply(first, profile, approved=True, approval_fingerprint=first["approval_fingerprint"])
        clean = helper.plan(self.describe(), "thin", profile=profile)
        (root / "context" / "rules.md").write_text("updated shared rule\n")
        changed = helper.plan(self.describe(), "thin", profile=profile)
        self.assertNotEqual(clean["approval_fingerprint"], changed["approval_fingerprint"])
        self.assertIn(str(self.homes["codex"] / "AGENTS.md"), [m["file"] for m in changed["mutation_list"]])
        before = (self.homes["codex"] / "AGENTS.md").read_bytes()
        with self.assertRaisesRegex(ValueError, "approved mutation list changed"):
            helper.apply(clean, profile, approved=True, approval_fingerprint=clean["approval_fingerprint"])
        self.assertEqual((self.homes["codex"] / "AGENTS.md").read_bytes(), before)
        for exists in (False, True):
            override = self.base / ("existing.md" if exists else "absent.md")
            if exists:
                override.write_text("user rules\n")
            value = helper.plan(self.describe(), "thin", overrides={"codex": {"rules_target": str(override)}}, profile=profile)
            self.assertIn(str(override), [m["file"] for m in value["mutation_list"]])

    def test_development_root_inherited_from_profile_and_composed(self):
        helper = load_helper()
        root, profile = self.configured_profile()
        dev = self.base / "development"
        initial = helper.plan(self.describe(), "thin", development_root=dev, profile=profile)
        helper.apply(initial, profile, approved=True, approval_fingerprint=initial["approval_fingerprint"])
        inherited = helper.plan(self.describe(), "thin", profile=profile)
        self.assertEqual(inherited["development_root"], str(dev))
        self.assertIn("@" + str(root / "context" / "development-rules.md"), (dev / "CLAUDE.md").read_text())
        self.assertIn("development rule", (dev / "AGENTS.md").read_text())
        self.assertNotIn("shared rule", (dev / "AGENTS.md").read_text())
        self.assertEqual(inherited["mutation_list"], [])
        self.assertTrue(all(row["development_delivery"] for row in inherited["tools"]))

    def test_codex_valid_toml_forms_disable_only_memories(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        config = self.homes["codex"] / "config.toml"
        for text in ('[features]\nmemories = true # enabled\nother = true\n',
                     'features.memories = true\nfeatures.other = true\n',
                     'features = { memories = true, other = true }\n',
                     '["features"]\n"memories" = true\nother = true\n'):
            with self.subTest(text=text):
                config.write_text(text)
                value = helper.plan(self.describe(), "thin", profile=profile)
                row = next(row for row in value["tools"] if row["tool"] == "codex")
                self.assertEqual(row["memory_mutations"], [{"file": str(config), "setting": "features.memories", "current": True, "proposed": False}])
                helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
                expected = tomllib.loads(text)
                expected["features"]["memories"] = False
                self.assertEqual(tomllib.loads(config.read_text()), expected)

    def test_memory_inventory_counts_only_memory_content(self):
        project = self.homes["claude-code"] / "projects" / "sample"
        project.mkdir(parents=True)
        (project / "session.jsonl").write_text("transcript\n")
        workspace = self.homes["openclaw"] / "workspace"
        workspace.mkdir()
        (workspace / "MEMORY.md").write_text("durable fact\n")
        rows = {r["tool"]: r for r in self.describe()}
        self.assertEqual(rows["claude-code"]["memory"]["store"]["file_count"], 0)
        self.assertEqual(rows["openclaw"]["memory"]["store"]["file_count"], 1)
        (project / "memory").mkdir()
        (project / "memory" / "fact.md").write_text("fact\n")
        (workspace / "memory").mkdir()
        (workspace / "memory" / "daily.md").write_text("daily\n")
        rows = {r["tool"]: r for r in self.describe()}
        self.assertEqual(rows["claude-code"]["memory"]["store"]["file_count"], 1)
        self.assertEqual(rows["openclaw"]["memory"]["store"]["file_count"], 2)

    def test_fresh_workspace_is_an_explicit_approved_directory(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        workspace = self.homes["openclaw"] / "workspace"
        value = helper.plan(self.describe(), "thin", profile=profile)
        self.assertIn({"kind": "directory", "file": str(workspace), "current": "absent", "proposed": "create directory"}, value["mutation_list"])
        self.assertFalse(workspace.exists())
        helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
        self.assertTrue((workspace / "AGENTS.md").is_file())

    def test_mixed_openclaw_settings_propose_only_changed_values(self):
        helper = load_helper()
        for flush, dreaming in ((False, True), (True, False)):
            config = {}
            helper.set_nested(config, ("agents", "defaults", "compaction", "memoryFlush", "enabled"), flush)
            helper.set_nested(config, ("plugins", "entries", "memory-core", "config", "dreaming", "enabled"), dreaming)
            helper.dump_json(self.homes["openclaw"] / "openclaw.json", config)
            row = next(r for r in self.describe() if r["tool"] == "openclaw")
            self.assertEqual(len(row["off_mutations"]), 1)
            self.assertIs(row["off_mutations"][0]["current"], True)

    def describe(self):
        helper = load_helper()
        return helper.inspect_tools(self.homes)

    def test_detects_installed_targets_ownership_memory_and_store_count(self):
        (self.homes["claude-code"] / "CLAUDE.md").write_text("manual instructions\n")
        (self.homes["claude-code"] / "settings.json").write_text(json.dumps({"autoMemoryEnabled": True}))
        memory = self.homes["claude-code"] / "projects" / "sample" / "memory"
        memory.mkdir(parents=True)
        (memory / "fact.md").write_text("fact\n")
        rows = {row["tool"]: row for row in self.describe()}
        claude = rows["claude-code"]
        self.assertTrue(claude["installed"])
        self.assertEqual(claude["target"]["ownership"], "user-owned")
        self.assertEqual(claude["memory"]["state"], "on")
        self.assertEqual(claude["memory"]["store"]["file_count"], 1)
        self.assertEqual(rows["codex"]["memory"]["state"], "off")
        self.assertEqual(rows["openclaw"]["target"]["ownership"], "composer-owned")

    def test_memory_matrix_proposes_only_non_off_non_customized_states(self):
        helper = load_helper()
        settings = {
            "claude-code": ("settings.json", {"autoMemoryEnabled": True}),
            "codex": ("config.toml", {"features.memories": True}),
            "openclaw": ("openclaw.json", {
                "agents.defaults.compaction.memoryFlush.enabled": True,
                "plugins.entries.memory-core.config.dreaming.enabled": True,
            }),
        }
        for tool in self.homes:
            for state in ("off", "on", "customized"):
                for chosen in ("native", "off"):
                    with self.subTest(tool=tool, state=state, chosen=chosen):
                        _, profile = self.configured_profile()
                        helper.write_memory_state(self.homes[tool], tool, state)
                        overrides = {name: {"rules_target": "none", "memory": chosen if name == tool else "native"} for name in self.homes}
                        value = helper.plan(self.describe(), "standard", overrides=overrides, profile=profile)
                        row = next(row for row in value["tools"] if row["tool"] == tool)
                        filename, entries = settings[tool]
                        expected = [{"file": str(self.homes[tool] / filename), "setting": key, "current": current, "proposed": False}
                                    for key, current in entries.items()] if chosen == "off" and state == "on" else []
                        self.assertEqual(row["memory_mutations"], expected)
                        self.assertEqual(row["flagged"], chosen == "off" and state == "customized")
                        path = self.homes[tool] / filename
                        before = path.read_bytes()
                        helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
                        if not expected:
                            self.assertEqual(path.read_bytes(), before)
                        again = helper.plan(self.describe(), "standard", overrides=overrides, profile=profile)
                        self.assertEqual(again["mutation_list"], [])

    def test_thin_plan_targets_installed_tools_and_names_development_delivery(self):
        helper = load_helper()
        plan = helper.plan(self.describe(), "thin", development_root=self.base / "development")
        self.assertEqual({row["rules_target"] for row in plan["tools"]}, {
            str(self.homes["claude-code"] / "CLAUDE.md"),
            str(self.homes["codex"] / "AGENTS.md"),
            str(self.homes["openclaw"] / "workspace" / "AGENTS.md"),
        })
        delivery = {row["tool"]: row["development_delivery"] for row in plan["tools"]}
        self.assertEqual(delivery["claude-code"], "directory walk from the development root")
        self.assertEqual(delivery["codex"], "repository block")
        self.assertEqual(delivery["openclaw"], "repository block")

    def test_apply_requires_approval_and_never_deletes_memory(self):
        helper = load_helper()
        memory = self.homes["openclaw"] / "workspace" / "memory"
        memory.mkdir(parents=True)
        record = memory / "keep.md"
        record.write_text("keep\n")
        plan = helper.plan(self.describe(), "thin")
        profile = self.base / "profile.md"
        with self.assertRaisesRegex(ValueError, "approval"):
            helper.apply(plan, profile, approved=False)
        self.assertTrue(record.exists())
        self.assertFalse(profile.exists())

    def test_approved_apply_composes_selected_targets_and_records_profile_choices(self):
        helper = load_helper()
        root = self.base / "knowledge"
        (root / "context").mkdir(parents=True)
        for name in ("raw", "output", "docs"):
            (root / name).mkdir()
        (root / "docs" / "log.md").touch()
        (root / "docs" / "DECISIONS.md").touch()
        (root / "context" / "rules.md").write_text("shared rule\n")
        (root / "context" / "development-rules.md").write_text("development rule\n")
        profile = self.base / "profile.md"
        profile.write_text("---\nprofile_version: 4\nknowledge_root: " + str(root) + "\nwiki_enabled: false\noperation_log_file: docs/log.md\ndecision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Tasks\n---\npolicy\n")
        plan = helper.plan(self.describe(), "thin", profile=profile)
        helper.apply(
            plan,
            profile,
            knowledge_root=root,
            approved=True,
            approval_fingerprint=plan["approval_fingerprint"],
        )
        self.assertIn("shared rule", (self.homes["codex"] / "AGENTS.md").read_text())
        self.assertIn("rules:\n  preset: thin", profile.read_text())
        self.assertIn("tool: openclaw", profile.read_text())
        self.assertEqual(helper.plan(self.describe(), "thin", profile=profile)["mutation_list"], [])

    def test_apply_refuses_a_stale_approved_plan_before_writing(self):
        helper = load_helper()
        root = self.base / "knowledge"
        (root / "context").mkdir(parents=True)
        for name in ("raw", "output", "docs"):
            (root / name).mkdir()
        (root / "docs" / "log.md").touch()
        (root / "docs" / "DECISIONS.md").touch()
        (root / "context" / "rules.md").write_text("shared rule\n")
        (root / "context" / "development-rules.md").write_text("development rule\n")
        profile = self.base / "profile.md"
        profile.write_text("---\nprofile_version: 4\nknowledge_root: " + str(root) + "\nwiki_enabled: false\noperation_log_file: docs/log.md\ndecision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Tasks\n---\npolicy\n")
        reviewed = helper.plan(self.describe(), "thin", profile=profile)
        profile_before = profile.read_text()
        (self.homes["claude-code"] / "settings.json").write_text(
            json.dumps({"autoMemoryEnabled": False})
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "apply",
                "--homes",
                json.dumps({name: str(home) for name, home in self.homes.items()}),
                "--preset",
                "thin",
                "--profile",
                str(profile),
                "--approve",
                "--approval-fingerprint",
                reviewed["approval_fingerprint"],
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approved mutation list changed", result.stderr)
        self.assertEqual(profile.read_text(), profile_before)
        self.assertFalse((self.homes["claude-code"] / "CLAUDE.md").exists())
        self.assertFalse((self.homes["codex"] / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
