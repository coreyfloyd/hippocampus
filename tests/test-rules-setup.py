#!/usr/bin/env python3
"""Contract tests for the set-up rules and memory proposal helper."""
import importlib.util
import json
import pathlib
import tempfile
import unittest


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
        self.base = pathlib.Path(self.temp.name)
        self.homes = {name: self.base / name for name in ("claude-code", "codex", "openclaw")}
        for name, home in self.homes.items():
            (home / "bin").mkdir(parents=True)
            executable = {"claude-code": "claude", "codex": "codex", "openclaw": "openclaw"}[name]
            (home / "bin" / executable).touch()

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
        for tool in self.homes:
            for state in ("off", "on", "customized"):
                with self.subTest(tool=tool, state=state, chosen="native"):
                    helper.write_memory_state(self.homes[tool], tool, state)
                    plan = helper.plan(self.describe(), "standard")
                    row = next(row for row in plan["tools"] if row["tool"] == tool)
                    self.assertEqual(row["memory"], "native")
                    self.assertEqual(row["memory_mutations"], [])
                with self.subTest(tool=tool, state=state, chosen="off"):
                    helper.write_memory_state(self.homes[tool], tool, state)
                    plan = helper.plan(self.describe(), "thin")
                    row = next(row for row in plan["tools"] if row["tool"] == tool)
                    expected = 0 if state in {"off", "customized"} else row["memory_change_count"]
                    self.assertEqual(len(row["memory_mutations"]), expected)
                    self.assertEqual(row["flagged"], state == "customized")

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
        (self.homes["openclaw"] / "workspace").mkdir()
        profile = self.base / "profile.md"
        profile.write_text("---\nprofile_version: 4\nknowledge_root: " + str(root) + "\nwiki_enabled: false\noperation_log_file: docs/log.md\ndecision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Tasks\n---\npolicy\n")
        plan = helper.plan(self.describe(), "thin")
        helper.apply(plan, profile, knowledge_root=root, approved=True)
        self.assertIn("shared rule", (self.homes["codex"] / "AGENTS.md").read_text())
        self.assertIn("rules:\n  preset: thin", profile.read_text())
        self.assertIn("tool: openclaw", profile.read_text())
        self.assertEqual(helper.plan(self.describe(), "thin", profile=profile)["mutation_list"], [])


if __name__ == "__main__":
    unittest.main()
