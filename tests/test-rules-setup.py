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
        # Policy reads resolve the configuration folder; keep them inside this test's directory.
        isolated = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base / "config")})
        isolated.start()
        self.addCleanup(isolated.stop)
        os.environ.pop("HIPPOCAMPUS_ROUTING", None)
        self.homes = {name: self.base / name for name in ("claude-code", "codex")}
        for name, home in self.homes.items():
            (home / "bin").mkdir(parents=True)
            executable = {"claude-code": "claude", "codex": "codex"}[name]
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
        store = self.homes["codex"] / "memories"
        rows = {r["tool"]: r for r in self.describe()}
        self.assertEqual(rows["codex"]["memory"]["store"]["file_count"], 0)
        self.assertTrue(rows["codex"]["memory"]["store"]["empty"])
        self.assertEqual(rows["claude-code"]["memory"]["store"]["file_count"], 0)
        (project / "memory").mkdir()
        (project / "memory" / "fact.md").write_text("fact\n")
        (store / "nested").mkdir(parents=True)
        (store / "keep.md").write_text("keep\n")
        (store / "nested" / "fact.md").write_text("fact\n")
        rows = {r["tool"]: r for r in self.describe()}
        self.assertEqual(rows["codex"]["memory"]["store"]["file_count"], 2)
        self.assertFalse(rows["codex"]["memory"]["store"]["empty"])
        self.assertEqual(rows["claude-code"]["memory"]["store"]["file_count"], 1)

    def test_new_target_parent_is_an_explicit_approved_directory(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        directory = self.base / "new-targets"
        target = directory / "AGENTS.md"
        value = helper.plan(self.describe(), "thin", profile=profile,
                            overrides={"codex": {"rules_target": str(target)}})
        self.assertIn({"kind": "directory", "file": str(directory), "current": "absent", "proposed": "create directory"}, value["mutation_list"])
        self.assertFalse(directory.exists())
        helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
        self.assertTrue(target.is_file())

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

    def test_memory_matrix_proposes_only_non_off_non_customized_states(self):
        helper = load_helper()
        settings = {
            "claude-code": ("settings.json", {"autoMemoryEnabled": True}),
            "codex": ("config.toml", {"features.memories": True}),
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
        })
        delivery = {row["tool"]: row["development_delivery"] for row in plan["tools"]}
        self.assertEqual(delivery["claude-code"]["file"], str(self.base / "development" / "CLAUDE.md"))
        self.assertEqual(delivery["codex"]["file"], str(self.base / "development" / "AGENTS.md"))
        self.assertTrue(all(row["discovery"] for row in delivery.values()))

    def only(self, *tools):
        """Leave only the named tools installed; PATH is emptied for the caller's block."""
        helper = load_helper()
        for tool, home in self.homes.items():
            if tool not in tools:
                (home / "bin" / helper.TOOLS[tool]["binary"]).unlink(missing_ok=True)
        return mock.patch.dict(os.environ, {"PATH": str(self.base / "empty-path")})

    def test_development_root_receives_only_installed_tools_entries(self):
        helper = load_helper()
        for tools, expected in ((("claude-code",), {"CLAUDE.md"}), (("codex",), {"AGENTS.md"}),
                                (("claude-code", "codex"), {"CLAUDE.md", "AGENTS.md"})):
            with self.subTest(tools=tools):
                self.setUp()
                root, profile = self.configured_profile()
                dev = self.base / "development"
                with self.only(*tools):
                    value = helper.plan(self.describe(), "standard", development_root=dev, profile=profile)
                    planned = {pathlib.Path(m["file"]).name for m in value["mutation_list"] if m["kind"] == "rule target"}
                    self.assertEqual(planned, expected)
                    self.assertEqual({row["tool"] for row in value["tools"]}, set(tools))
                    helper.apply(value, profile, approved=True, approval_fingerprint=value["approval_fingerprint"])
                self.assertEqual({p.name for p in dev.iterdir()}, expected)
                if "CLAUDE.md" in expected:
                    # Claude's entry is a minimal import of the provider-neutral source.
                    self.assertEqual((dev / "CLAUDE.md").read_text().splitlines()[1:],
                                     ["@" + str(root / "context" / "development-rules.md")])
                if "AGENTS.md" in expected:
                    self.assertIn("development rule", (dev / "AGENTS.md").read_text())

    def test_recommends_thin_only_for_several_tools_or_portability(self):
        helper = load_helper()
        rows = [{"tool": "claude-code", "installed": True}, {"tool": "codex", "installed": False}]
        self.assertEqual(helper.recommend_preset(rows)["preset"], "standard")
        self.assertEqual(helper.recommend_preset(rows, portable=True)["preset"], "thin")
        rows[1]["installed"] = True
        self.assertEqual(helper.recommend_preset(rows)["preset"], "thin")
        self.assertEqual(helper.recommend_preset([{"tool": "codex", "installed": False}])["preset"], "standard")
        with self.only("codex"):
            result = subprocess.run([sys.executable, str(SCRIPT), "plan", "--homes", self.homes_json(), "--preset", "thin"],
                                    capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["recommendation"]["preset"], "standard")

    def homes_json(self):
        return json.dumps({name: str(home) for name, home in self.homes.items()})

    def repository(self, tools, files, profile=None, repo=None):
        helper = load_helper()
        repo = repo or self.base / ("repo-" + "-".join(tools) + "-" + "-".join(sorted(files)))
        repo.mkdir()
        for name, text in files.items():
            (repo / name).write_text(text)
        before = {p.name: p.read_bytes() for p in repo.iterdir()}
        with self.only(*tools):
            value = helper.repository_entries(repo, self.describe(), profile)
        self.assertEqual({p.name: p.read_bytes() for p in repo.iterdir()}, before)  # inspection writes nothing
        return repo, value, {entry["tool"]: entry for entry in value["entries"]}

    def test_repository_source_is_agents_md_whatever_entries_exist(self):
        cases = {"neither": {}, "agents": {"AGENTS.md": "repo rule\n"}, "claude": {"CLAUDE.md": "claude rule\n"},
                 "both": {"AGENTS.md": "repo rule\n", "CLAUDE.md": "@AGENTS.md\nclaude extra\n"}}
        for label, files in cases.items():
            for tools in (("claude-code",), ("codex",), ("claude-code", "codex")):
                with self.subTest(files=label, tools=tools):
                    self.setUp()
                    repo, value, entries = self.repository(tools, files)
                    self.assertEqual(value["source"]["files"], [str(repo / "AGENTS.md")])
                    self.assertEqual(set(entries), set(tools))
                    kept = {pathlib.Path(row["file"]).name for row in value["kept"]}
                    if "claude-code" in entries:
                        claude = entries["claude-code"]
                        if "CLAUDE.md" not in files:
                            self.assertEqual((claude["action"], claude["contents"]), ("create", "@AGENTS.md\n"))
                        elif label == "both":
                            self.assertEqual(claude["action"], "keep")
                        else:
                            self.assertEqual(claude["contents"], "@AGENTS.md\n\nclaude rule\n")
                            self.assertIn("CLAUDE.md", kept)
                    else:
                        self.assertEqual("CLAUDE.md" in kept, "CLAUDE.md" in files)
                    if "codex" in entries:
                        self.assertEqual(entries["codex"]["action"],
                                         "keep" if "AGENTS.md" in files else "create with the first repository rule")
                    elif "AGENTS.md" in files:
                        self.assertNotIn("AGENTS.md", kept)  # the source, not an unneeded entry
                    self.assertTrue(all(entry["discovery"] for entry in entries.values()))

    def test_symlinked_entries_are_one_file_and_never_import_themselves(self):
        helper = load_helper()
        for link, real in (("AGENTS.md", "CLAUDE.md"), ("CLAUDE.md", "AGENTS.md")):
            with self.subTest(link=link):
                self.setUp()
                repo = self.base / ("repo-link-" + link)
                repo.mkdir()
                (repo / real).write_text("repo rule\n")
                (repo / link).symlink_to(real)
                with self.only("claude-code", "codex"):
                    value = helper.repository_entries(repo, self.describe())
                self.assertEqual(value["source"]["files"], [str(repo / "AGENTS.md")])
                self.assertIsNone(value["source"]["generated_entry"])
                actions = {entry["tool"]: entry["action"] for entry in value["entries"]}
                self.assertEqual(actions, {"codex": "keep", "claude-code": "keep: the same file as AGENTS.md"})
                self.assertTrue(all("contents" not in entry for entry in value["entries"]))

    def test_composer_import_entry_reports_its_imported_files(self):
        helper = load_helper()
        shared = self.base / "shared.md"
        shared.write_text("rule\n")
        for imports, expected in (("@" + str(shared) + "\n", [str(shared)]), ("", None)):
            with self.subTest(imports=bool(imports)):
                self.setUp()
                repo = self.base / ("repo-header-" + str(bool(imports)))
                repo.mkdir()
                (repo / "AGENTS.md").write_text("<!-- hippocampus-rules: generated; do not hand-edit -->\n" + imports)
                with self.only("codex"):
                    if expected is None:
                        with self.assertRaisesRegex(ValueError, "names no source"):
                            helper.repository_entries(repo, self.describe())
                    else:
                        value = helper.repository_entries(repo, self.describe())
                        self.assertEqual(value["source"]["files"], expected)

    def test_import_inside_a_fenced_example_is_not_active(self):
        _, _, entries = self.repository(("claude-code",), {
            "CLAUDE.md": "Example:\n\n```markdown\n@AGENTS.md\n```\n"})
        self.assertEqual(entries["claude-code"]["action"], "add import; existing content stays")

    def test_repository_reads_the_configured_profile_by_default(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        shared = self.base / "own-rules.md"
        shared.write_text("custom rule\n")
        repo = self.base / "repo-default-profile"
        configured = self.base / "config" / "hippocampus" / "profile.md"
        configured.parent.mkdir(parents=True)
        configured.write_text(profile.read_text() + "\n## Lesson routing\n\nProduced surfaces:\n  "
                              + str(shared) + ":\n    - path: " + str(repo / "AGENTS.md")
                              + "\n      regeneration command: \"make rules\"\n")
        _, value, entries = self.repository(("codex",), {"AGENTS.md": "generated\n"}, repo=repo)
        self.assertEqual(value["source"]["files"], [str(shared)])
        self.assertEqual(entries["codex"]["action"], "regenerate from its source")
        with self.only("codex"):
            result = subprocess.run([sys.executable, str(SCRIPT), "repository", "--repository", str(repo),
                                     "--homes", self.homes_json()], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["source"]["files"], [str(shared)])

    def test_an_inline_import_is_active_and_a_dangling_link_is_not_replaced(self):
        for text, action in (("Shared rules: @AGENTS.md\n", "keep"), ("Rules @./AGENTS.md here\n", "keep"),
                             ("Write `@AGENTS.md` to import\n", "add import; existing content stays"),
                             ("mail me@AGENTS.md\n", "add import; existing content stays")):
            with self.subTest(text=text):
                self.setUp()
                _, _, entries = self.repository(("claude-code",), {"CLAUDE.md": text})
                self.assertEqual(entries["claude-code"]["action"], action)
        helper = load_helper()
        repo = self.base / "repo-dangling"
        repo.mkdir()
        (repo / "CLAUDE.md").symlink_to(self.base / "missing.md")
        with self.only("claude-code"):
            value = helper.repository_entries(repo, self.describe())
        [entry] = value["entries"]
        self.assertTrue(entry["exists"])
        self.assertNotIn("contents", entry)
        self.assertIn("missing file", entry["action"])
        self.assertTrue((repo / "CLAUDE.md").is_symlink())

    def test_repository_custom_sources_stay_the_users(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        shared = self.base / "own-rules.md"
        shared.write_text("custom rule\n")
        repo = self.base / "repo-custom"
        profile.write_text(profile.read_text() + "\n## Lesson routing\n\nProduced surfaces:\n  "
                           + str(shared) + ":\n    - path: " + str(repo / "AGENTS.md")
                           + "\n      regeneration command: \"make rules\"\n")
        _, value, entries = self.repository(("claude-code", "codex"), {"AGENTS.md": "generated\n"}, profile, repo)
        self.assertEqual(value["source"]["files"], [str(shared)])
        self.assertEqual(entries["codex"]["action"], "regenerate from its source")
        self.assertEqual(entries["claude-code"]["action"], "create")
        generated = self.base / "repo-generated"
        generated.mkdir()
        header = '<!-- hippocampus-rules: generated from ["' + str(shared) + '"]; do not hand-edit -->\n'
        (generated / "CLAUDE.md").write_text(header + "custom rule\n")
        with self.only("claude-code"):
            value = helper.repository_entries(generated, self.describe())
        self.assertEqual(value["entries"][0]["action"], "keep: produced from its own source")
        self.assertNotIn("contents", value["entries"][0])

    def test_apply_requires_approval_and_never_deletes_memory(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        records = []
        for tool, store in (("claude-code", "projects/sample/memory"), ("codex", "memories")):
            helper.write_memory_state(self.homes[tool], tool, "on")
            memory = self.homes[tool] / store
            memory.mkdir(parents=True)
            record = memory / "keep.md"
            record.write_bytes(b"keep\n")
            records.append(record)
        before_profile = profile.read_bytes()
        plan = helper.plan(self.describe(), "thin", profile=profile)
        with self.assertRaisesRegex(ValueError, "approval"):
            helper.apply(plan, profile, approved=False)
        self.assertEqual(profile.read_bytes(), before_profile)
        self.assertEqual([p.read_bytes() for p in records], [b"keep\n", b"keep\n"])
        helper.apply(plan, profile, approved=True,
                     approval_fingerprint=plan["approval_fingerprint"])
        self.assertEqual([p.read_bytes() for p in records], [b"keep\n", b"keep\n"])
        for row in self.describe():
            self.assertEqual(row["memory"]["state"], "off")

    def test_setup_replaces_unsupported_profile_row_with_detected_tools(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        previous = profile.read_text().replace("---\npolicy", "rules:\n  preset: standard\n"
            "  cross_tool_document: context/rules.md\n"
            "  development_document: context/development-rules.md\n"
            "  tools:\n    - tool: unknown-tool\n      rules_target: none\n"
            "      memory: native\n---\npolicy")
        profile.write_text(previous)
        value = helper.plan(self.describe(), "standard", profile=profile)
        self.assertEqual(profile.read_text(), previous)
        self.assertTrue(any(m["kind"] == "profile" for m in value["mutation_list"]))
        helper.apply(value, profile, approved=True,
                     approval_fingerprint=value["approval_fingerprint"])
        helper.profile_reader().validate(profile)
        parsed = helper.profile_reader().parse(profile)
        self.assertEqual(parsed["rules"]["tools"], [
            {"tool": tool, "rules_target": "none", "memory": "native"}
            for tool in self.homes])

    def test_replacing_rules_does_not_bypass_other_profile_validation(self):
        helper = load_helper()
        _, profile = self.configured_profile()
        profile.write_text(profile.read_text().replace("profile_version: 4", "profile_version: invalid"))
        before = profile.read_bytes()
        value = helper.plan(self.describe(), "thin", profile=profile)
        with self.assertRaises(SystemExit):
            helper.apply(value, profile, approved=True,
                         approval_fingerprint=value["approval_fingerprint"])
        self.assertEqual(profile.read_bytes(), before)
        self.assertFalse((self.homes["claude-code"] / "CLAUDE.md").exists())
        self.assertFalse((self.homes["codex"] / "AGENTS.md").exists())
        self.assertFalse((self.homes["claude-code"] / "settings.json").exists())

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
        self.assertIn("tool: claude-code", profile.read_text())
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
