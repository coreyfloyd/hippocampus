"""Checklist profile seam; run with python3 -m unittest discover -s tests -p test_checklist.py."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts/lib/checklist.py"
NUDGE = ROOT / "hooks/checklist-nudge.sh"
GUARD = ROOT / "hooks/checklist-actor-guard.sh"
PROFILES = ROOT / "tests/fixtures/profiles"
STATE_MODULE = ROOT / "tests/support/unattended_state.py"
# The unattended section a user would write: a state provider, the command that
# completes a slate, and what that command leaves behind in the session record.
UNATTENDED = {"state_module": str(STATE_MODULE),
              "completion_command": r"slate\.sh['\"]?\s+complete-(?:slate|scope|plan-slate)\b",
              "completed_by": ["slate-completed", "scope-completed"]}


class ChecklistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ENGINE.exists():
            cls.engine = None
            return
        spec = importlib.util.spec_from_file_location("checklist", ENGINE)
        cls.engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.engine)

    def setUp(self):
        self.assertTrue(ENGINE.exists(), "The checklist profile composer has not been implemented")
        # The CLI refuses headless sessions; pin an interactive one even when a factory runs this suite.
        self.state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_dir.cleanup)
        # `plan` writes a start marker to the session ledger; keep it off the live ledger.
        config = Path(self.state_dir.name) / "continuity-config.json"
        config.write_text(json.dumps({"unattended": UNATTENDED}))
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli", "CHECKLIST_STATE_DIR": self.state_dir.name,
                                               "HANDOFF_LEDGER_DIR": self.state_dir.name,
                                               "CONTINUITY_CONFIG": str(config)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_spine_has_four_slots_and_final_handoff(self):
        plan = self.engine.compose([])
        self.assertEqual([s["id"] for s in plan], ["record", "knowledge", "lessons", "persist", "handoff"])
        self.assertEqual([s["slot"] for s in plan[:-1]], ["record", "knowledge", "lessons", "persist"])
        self.assertNotIn("slot", plan[-1])
        self.assertEqual(plan[2]["binding"]["command"], "/improve-harness")

    def test_user_profile_runs_nine_steps(self):
        user = self.engine.load_profile(PROFILES / "user.md")
        plan = self.engine.compose([user])
        self.assertEqual([s["id"] for s in plan], ["record", "knowledge", "lessons", "persist", "cleanup", "context-health", "session-metadata", "whats-next", "handoff"])
        self.assertEqual([s["binding"]["command"] for s in plan[:4]], ["/record-step", "/knowledge-step", "/improve-harness", "/persist-step"])
        for step in plan[4:-1]:
            self.assertTrue(step["instructions"])

    def test_repository_additions_keep_user_and_spine_steps(self):
        user = self.engine.load_profile(PROFILES / "user.md")
        repo = {"name": "example-repo", "steps": [{"id": "tests", "after": "before-spine", "instructions": "run tests"}, {"id": "deploy", "after": "persist", "instructions": "deploy"}]}
        plan = self.engine.compose([user, repo])
        self.assertEqual(plan[0]["id"], "tests")
        self.assertEqual(plan[-2]["id"], "deploy")
        self.assertEqual(plan[-1]["id"], "handoff")
        self.assertEqual(len(plan), 11)

    def test_repository_profiles_are_executable_additions(self):
        for path in [PROFILES / "repository.md", PROFILES / "code.md"]:
            with self.subTest(path=path):
                profile = self.engine.load_profile(path)
                plan = self.engine.compose([profile])
                self.assertGreater(len(plan), 5)
                self.assertEqual(plan[-1]["id"], "handoff")
                self.assertTrue(all(step.get("instructions") for step in plan if "slot" not in step and step["id"] != "handoff"))

    def test_every_insertion_anchor(self):
        for anchor in ["before-spine", "record", "knowledge", "lessons", "persist"]:
            plan = self.engine.compose([{"name": "extra", "steps": [{"id": "extra", "after": anchor, "instructions": "do extra"}]}])
            ids = [s["id"] for s in plan]
            self.assertEqual(ids.index("extra"), 0 if anchor == "before-spine" else ids.index(anchor) + 1)
            self.assertEqual(ids[-1], "handoff")

    def test_profiles_cannot_remove_skip_replace_or_append_after_handoff(self):
        for profile in [{"skip": ["record"]}, {"remove": ["knowledge"]}, {"steps": [{"id": "handoff", "after": "persist", "instructions": "replace"}]}, {"steps": [{"id": "extra", "after": "handoff", "instructions": "late"}]}, {"bindings": {"handoff": {"command": "/other", "consumes": []}}}]:
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(ValueError, "record|knowledge|handoff"):
                    self.engine.compose([dict(name="invalid", **profile)])

    def test_only_own_worktree_may_follow_the_handoff(self):
        late = {"id": "own-worktree", "after": "handoff", "instructions": "remove the session's own worktree"}
        plan = self.engine.compose([{"name": "user", "steps": [late]}])
        self.assertEqual([s["id"] for s in plan[-2:]], ["handoff", "own-worktree"])
        for steps in [[{"id": "other", "after": "handoff", "instructions": "late"}], [late, {"id": "other", "after": "handoff", "instructions": "late"}]]:
            with self.subTest(steps=steps):
                with self.assertRaisesRegex(ValueError, "cannot add step other after handoff; only own-worktree may follow it"):
                    self.engine.compose([{"name": "user", "steps": steps}])
        for anchor in ["before-spine", "record", "knowledge", "lessons", "persist"]:
            with self.subTest(anchor=anchor):
                with self.assertRaisesRegex(ValueError, f"step own-worktree must follow handoff, not {anchor}"):
                    self.engine.compose([{"name": "user", "steps": [dict(late, after=anchor)]}])
        with self.assertRaisesRegex(ValueError, "cannot replace or duplicate step own-worktree"):
            self.engine.compose([{"name": "user", "steps": [late]}, {"name": "repo", "steps": [late]}])
        results = [{"id": step["id"], "status": "run", "writes": []} for step in plan]
        self.assertEqual(self.engine.check_report(plan, results), [])
        kept = dict(results[-1], status="failed", reason="kept: branch not merged into the trunk")
        self.assertEqual(self.engine.check_report(plan, results[:-1] + [kept]), [])
        early = results[:-2] + [results[-1], results[-2]]
        self.assertIn("plan is", self.engine.check_report(plan, early)[0])

    def test_repository_profile_cannot_override_user_binding(self):
        user = self.engine.load_profile(PROFILES / "user.md")
        with self.assertRaisesRegex(ValueError, "record"):
            self.engine.compose([user, {"name": "repo", "bindings": {"record": {"command": "/other", "consumes": ["decision"]}}}])

    def handoff(self):
        return {"subject": {"session_id": "resumed-session"}, "resume": {"session_summary": "earlier work", "open_loops": [{"type": kind, "context": kind + " text", "session_id": "earlier-session", "produced_at": "2026-10-02T12:00:00Z", "author": "user", "location": "https://example.test/page", "disposition": "keep"} for kind in ["progress", "commitment", "decision", "knowledge", "lesson", "artifact"]]}}

    def test_bound_slots_receive_carried_items_unchanged_and_acknowledged_items_leave(self):
        profile = self.engine.load_profile(PROFILES / "user.md")
        plan = self.engine.compose([profile])
        handoff = self.handoff()
        before = copy.deepcopy(handoff)
        record = self.engine.slot_inputs(plan, "record", handoff)
        self.assertEqual([row["index"] for row in record], [0, 1, 2, 5])
        self.assertEqual(record[0]["item"], before["resume"]["open_loops"][0])
        self.assertEqual(self.engine.slot_inputs(plan, "knowledge", handoff)[0]["index"], 3)
        self.assertEqual(self.engine.slot_inputs(plan, "lessons", handoff)[0]["index"], 4)
        remaining = self.engine.settle(plan, handoff, {"record": [0, 1], "lessons": [4]})
        self.assertEqual([loop["type"] for loop in remaining["resume"]["open_loops"]], ["decision", "knowledge", "artifact"])
        self.assertEqual(remaining["resume"]["session_summary"], "earlier work")
        self.assertEqual(handoff, before)

    def test_failed_pending_unbound_and_legacy_items_are_not_consumed(self):
        handoff = self.handoff()
        handoff["resume"]["open_loops"].append({"context": "legacy loop", "disposition": "continue"})
        plan = self.engine.compose([])
        self.assertEqual(self.engine.slot_inputs(plan, "record", handoff), [])
        self.assertEqual(self.engine.settle(plan, handoff, {}), handoff)
        for receipts in [{"record": [0]}, {"lessons": [0]}, {"lessons": [99]}, {"lessons": [True]}, {"handoff": [0]}]:
            with self.subTest(receipts=receipts):
                with self.assertRaises(ValueError):
                    self.engine.settle(plan, handoff, receipts)

    def test_cli_plan_and_settle(self):
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / "handoff.json"
            handoff.write_text(json.dumps(self.handoff()))
            user = PROFILES / "user.md"
            command = [sys.executable, str(ENGINE)]
            result = subprocess.run(command + ["plan", "--user-profile", str(user), "--handoff", str(handoff)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(len(output["steps"]), 9)
            self.assertEqual(output["steps"][0]["carried_items"][0]["item"]["session_id"], "earlier-session")
            receipts = Path(directory) / "receipts.json"
            receipts.write_text('{"record": [0]}')
            result = subprocess.run(command + ["settle", "--user-profile", str(user), "--handoff", str(handoff), "--receipts", str(receipts)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["resume"]["open_loops"]), 5)
            self.assertEqual(len(json.loads(handoff.read_text())["resume"]["open_loops"]), 6)

    def test_cli_repository_profile_cannot_bind_a_spine_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "repo.json"
            profile.write_text(json.dumps({"name": "repo", "bindings": {"record": {"command": "/record", "consumes": ["progress"]}}}))
            result = subprocess.run([sys.executable, str(ENGINE), "plan", "--repository-profile", str(profile)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("record", result.stderr)

    def test_settled_items_leave_the_written_handoff_with_provenance_preserved(self):
        plan = self.engine.compose([self.engine.load_profile(PROFILES / "user.md")])
        supplied = self.engine.settle(plan, self.handoff(), {"record": [0, 1, 2, 5]})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "wrapped.json"
            environment = dict(os.environ, HANDOFF_PATH=str(target), HANDOFF_STATE_DIR=directory, HANDOFF_LEDGER_DIR=directory)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/lib/handoff.py"), "checkpoint", "--cwd", directory, "--session-id", "resumed-session", "--trigger", "wrap"], input=json.dumps(supplied), text=True, capture_output=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads(target.read_text())
            self.assertEqual([loop["type"] for loop in written["resume"]["open_loops"]], ["knowledge", "lesson"])
            self.assertEqual(written["resume"]["open_loops"][0], self.handoff()["resume"]["open_loops"][3])

    def test_no_profile_plan_runs_five_spine_steps_and_carries_unbound_slots(self):
        result = subprocess.run([sys.executable, str(ENGINE), "plan"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = json.loads(result.stdout)["steps"]
        self.assertEqual([s["id"] for s in steps], ["record", "knowledge", "lessons", "persist", "handoff"])
        self.assertEqual({s["id"]: s.get("carries") for s in steps[:4]},
                         {"record": ["progress", "commitment", "decision", "artifact"], "knowledge": ["knowledge"], "lessons": None, "persist": []})

    def test_rejections_name_the_spine_step(self):
        cases = [
            ({"skip": ["record"]}, "cannot remove or skip spine step record$"),
            ({"remove": "knowledge"}, "cannot remove or skip spine step knowledge$"),
            ({"spine": ["record", "knowledge", "persist", "handoff"]}, "cannot remove or skip spine step lessons$"),
            ({"bindings": {"record": {"command": "", "consumes": []}}}, "cannot remove or skip spine step record;"),
            ({"steps": [{"id": "late", "after": "handoff", "instructions": "late"}]}, "cannot add step late after handoff; only own-worktree may follow it"),
        ]
        for profile, message in cases:
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(ValueError, "^invalid: " + message):
                    self.engine.compose([dict(name="invalid", **profile)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"name": "invalid", "skip": ["handoff"]}))
            result = subprocess.run([sys.executable, str(ENGINE), "plan", "--user-profile", str(path)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("cannot remove or skip spine step handoff", result.stderr)

    def wrap(self, directory, session_items, profile_args=(), record_at=None, ledger=()):
        """Checkpoint as step 5 does, then run the wrap check through the CLI."""
        target = Path(directory) / "wrapped.json"
        environment = dict(os.environ, HANDOFF_PATH=str(target), HANDOFF_STATE_DIR=directory, HANDOFF_LEDGER_DIR=directory)
        with open(Path(directory) / "session-touched-paths.wrap-session.jsonl", "a") as handle:
            for row in ledger:
                handle.write(json.dumps(row) + "\n")
        supplied = dict(self.handoff(), session_items=session_items)
        supplied["resume"]["headline"] = "wrap"
        supplied["resume"]["open_loops"] = []
        checkpoint = subprocess.run([sys.executable, str(ROOT / "scripts/lib/handoff.py"), "checkpoint", "--cwd", directory, "--session-id", "wrap-session", "--trigger", "wrap"], input=json.dumps(supplied), text=True, capture_output=True, env=environment)
        command = [sys.executable, str(ENGINE), "wrap-check", *profile_args, "--written-handoff", str(target)]
        if record_at:
            command += ["--record-at", record_at]
        return checkpoint, subprocess.run(command, text=True, capture_output=True, env=environment), target

    def item(self, kind):
        return {"type": kind, "context": kind + " now", "session_id": "wrap-session", "produced_at": "2026-10-06T12:00:00Z", "author": "user", "location": "https://example.test/now", "disposition": "keep"}

    def filing_profile(self, ask=True, record=True):
        profile = {"name": "filing", "bindings": {"lessons": None,
                   "knowledge": {"command": "/knowledge", "consumes": ["knowledge"]}}}
        if record:
            profile["bindings"]["record"] = {"command": "/record", "consumes": ["progress"]}
        if ask:
            profile["ask"] = {"command": "/ask"}
        return profile

    def test_current_session_items_are_filed_before_checkpoint_can_reintroduce_them(self):
        source = self.handoff()
        source["resume"]["open_loops"] = []
        source["session_items"] = [self.item("progress"), dict(self.item("knowledge"), recorded=True)]
        result = self.engine.file_items(self.engine.compose([]), source,
            [dict(index=0, rule="R6", status="dropped", reason="optional observation")])
        self.assertEqual(result["resume"]["open_loops"], [])
        self.assertNotIn("session_items", result)
        self.assertEqual(result["filing"]["items"][0]["item"], self.item("progress"))

    def test_written_handoff_rejects_a_filed_item_still_carried_and_failed_write(self):
        profile = self.filing_profile()
        plan = self.engine.compose([profile])
        source = self.handoff()
        source["resume"]["open_loops"] = [self.item("progress")]
        filed = self.engine.file_items(plan, source,
            [dict(index=0, rule="R7", status="filed", destination="document")])
        filed["resume"]["open_loops"] = source["resume"]["open_loops"]
        self.assertIn("still carried", " ".join(self.engine.filing_check(plan, filed)[0]))
        failed = self.engine.file_items(plan, source,
            [dict(index=0, rule="R7", status="failed", error="write denied")])
        self.assertIn("write denied", " ".join(self.engine.filing_check(plan, failed)[0]))

    def test_explicit_attended_plan_restarts_an_unfinished_unattended_wrap(self):
        marker = self.engine._unattended_marker("wrap-session")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}")
        self.start(self.state_dir.name)
        self.assertFalse(marker.exists())

    def test_drop_and_new_ticket_require_reason_and_successful_read(self):
        source = self.handoff()
        source["resume"]["open_loops"] = [self.item("progress")]
        profile = self.filing_profile()
        plan = self.engine.compose([profile])
        for rule in ["R1", "R6"]:
            row = dict(index=0, rule=rule, status="dropped", information_only=True)
            with self.assertRaisesRegex(ValueError, "reason"):
                self.engine.file_items(plan, source, [row])
            self.assertEqual(self.engine.file_items(plan, source, [dict(row, reason="information only")])
                             ["resume"]["open_loops"], [])
        row = dict(index=0, rule="R5", status="filed", read_status="ok", destination="new ticket")
        with self.assertRaisesRegex(ValueError, "priority"):
            self.engine.file_items(plan, source, [row])
        result = self.engine.file_items(plan, source, [dict(row, priority="normal", priority_reason="Unblocks planned work")])
        self.assertEqual(result["resume"]["open_loops"], [])
        for read in [None, "failed", "unsupported", "malformed"]:
            result = self.engine.file_items(plan, source, [dict(row, read_status=read)])
            self.assertEqual(result["filing"]["items"][0]["status"], "read failed")

    def test_attended_plan_after_unattended_plan_runs_all_steps_again(self):
        command = [sys.executable, str(ENGINE), "plan", "--session-id", "wrap-session"]
        first = subprocess.run(command + ["--unattended"], text=True, capture_output=True)
        second = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        attended = json.loads(second.stdout)
        self.assertTrue(attended["rerun_all_steps"])
        self.assertEqual([step["id"] for step in attended["steps"]], list(self.engine.SPINE))
        self.assertNotIn("when_answer_needed", attended)
        self.assertTrue(all("status" not in step for step in attended["steps"]))

    def test_ask_binding_is_user_only_and_not_a_slot(self):
        profile = self.filing_profile()
        plan = self.engine.compose([profile])
        self.assertEqual([s["id"] for s in plan], list(self.engine.SPINE))
        self.assertEqual(self.engine.ask_binding(profile), {"command": "/ask"})
        for value in [None, {}, {"command": ""}, {"command": "/ask", "consumes": []}]:
            with self.assertRaises(ValueError):
                self.engine.compose([dict(profile, ask=value)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repo.json"
            path.write_text(json.dumps(profile))
            result = subprocess.run([sys.executable, str(ENGINE), "plan", "--repository-profile", str(path)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("cannot bind ask", result.stderr)

    def test_filing_outcomes_remove_only_successes_and_report_every_item(self):
        profile = self.filing_profile()
        plan = self.engine.compose([profile])
        source = self.handoff()
        source["subject"]["working_directory"] = "/work"
        rows = [dict(index=i, rule=rule, status=status, reason="optional observation" if rule == "R6" else "saved",
                     destination=destination, read_status="ok", choices=["approve", "decline"])
                for i, (rule, status, destination) in enumerate([
                    ("R2", "filed", "https://example.test/ticket"), ("R3", "filed", "ask receipt"),
                    ("R7", "filed", "https://example.test/doc"), ("R4", "filed", "knowledge receipt"),
                    ("R4", "pending", "ask"), ("R6", "dropped", "")])]
        # Pending R4 routes to ask; only an acknowledged ask write removes it.
        result = self.engine.file_items(plan, source, rows, self.engine.ask_binding(profile))
        self.assertEqual(result["resume"]["open_loops"], [source["resume"]["open_loops"][4]])
        self.assertEqual(len(result["filing"]["items"]), 6)
        ask = result["filing"]["items"][1]["ask"]
        self.assertEqual(ask["session_id"], "earlier-session")
        self.assertEqual(ask["directory"], "/work")
        self.assertEqual(ask["choices"], ["approve", "decline"])
        self.assertEqual(result["filing"]["items"][4]["binding"], "ask")
        complete = self.engine.file_items(plan, source, [dict(r, status="filed") if r["status"] == "pending" else r for r in rows], self.engine.ask_binding(profile))
        self.assertEqual(complete["resume"]["open_loops"], [])
        self.assertEqual(complete["resume"]["next_action"], "Session finished.")
        self.assertEqual(source, self.handoff() | {"subject": source["subject"]})

    def test_filing_preserves_failed_reads_and_never_treats_unknown_as_absence(self):
        plan = self.engine.compose([self.filing_profile()])
        source = self.handoff()
        source["resume"]["open_loops"] = [self.item("progress")]
        for rule in ["R1", "R2", "R5"]:
            result = self.engine.file_items(plan, source, [dict(index=0, rule=rule, status="filed",
                destination="ticket", read_status="failed", error="unsupported read")])
            self.assertEqual(result["resume"]["open_loops"], source["resume"]["open_loops"])
            self.assertEqual(result["filing"]["items"][0]["status"], "read failed")
            self.assertIn("unsupported read", " ".join(result["filing"]["failures"]))
        with self.assertRaisesRegex(ValueError, "every item"):
            self.engine.file_items(plan, source, [])

    def test_wrap_bound_carry_fails_unbound_warns_and_checkpoint_is_unchanged(self):
        for bound in [False, True]:
            with self.subTest(bound=bound), tempfile.TemporaryDirectory() as directory:
                profile = Path(directory) / "profile.json"
                profile.write_text(json.dumps(self.filing_profile(ask=False, record=bound)))
                checkpoint, result, target = self.wrap(directory, [self.item("progress")],
                    ["--user-profile", str(profile)], "2026-10-06T13:00:00Z")
                self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
                self.assertEqual(result.returncode, int(bound), result.stderr)
                self.assertIn("progress now", result.stderr)
                self.assertIn("record", result.stderr)
                self.assertTrue(json.loads(target.read_text())["resume"]["open_loops"])

    def test_wrap_rejects_lost_unbound_ask_and_unfinished_next_action(self):
        profile = self.filing_profile(ask=False)
        plan = self.engine.compose([profile])
        source = self.handoff()
        source["resume"]["open_loops"] = [self.item("decision")]
        result = self.engine.file_items(plan, source,
            [dict(index=0, rule="R3", status="pending", choices=["approve", "decline"])])
        result["resume"]["open_loops"] = []
        self.assertIn("missing from handoff", " ".join(self.engine.filing_check(plan, result)[0]))
        complete = self.engine.file_items(plan, source,
            [dict(index=0, rule="R6", status="dropped", reason="optional observation")])
        complete["resume"]["next_action"] = "Next session should do this"
        self.assertIn("Session finished", " ".join(self.engine.filing_check(plan, complete)[0]))

    def test_failed_ask_is_kept_and_unbound_ask_warns_under_directory(self):
        source = self.handoff()
        source["subject"]["working_directory"] = "/work"
        source["resume"]["open_loops"] = [self.item("decision")]
        for bound in [False, True]:
            profile = self.filing_profile(ask=bound)
            result = self.engine.file_items(self.engine.compose([profile]), source,
                [dict(index=0, rule="R3", status="failed", error="write refused", choices=["approve", "decline"])],
                self.engine.ask_binding(profile))
            self.assertEqual(result["resume"]["open_loops"], source["resume"]["open_loops"])
            report = result["filing"]
            self.assertEqual(bool(report["failures"]), bound)
            self.assertEqual(bool(report["warnings"]), not bound)
            self.assertEqual(report["asks"]["/work"][0]["text"], "decision now")
            if bound:
                self.assertIn("write refused", " ".join(report["failures"]))
            else:
                self.assertIn("decision now", result["resume"]["next_action"])

    def test_no_profile_wrap_carries_unbound_items_and_runs_no_record_check(self):
        with tempfile.TemporaryDirectory() as directory:
            items = [self.item(kind) for kind in ["progress", "commitment", "decision", "knowledge"]]
            stale = [{"kind": "file", "path": "/x", "checkout": "/", "session_id": "wrap-session", "ts": "2026-10-06T13:00:00Z"}]
            checkpoint, result, target = self.wrap(directory, items, ledger=stale)
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"wrap": "ok", "record_check": "not run: record unbound"})
            loops = json.loads(target.read_text())["resume"]["open_loops"]
            self.assertEqual(loops, items)

    def test_wrap_fails_when_the_handoff_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint, result, _ = self.wrap(directory, [{"type": "decision", "context": "no author"}])
            self.assertNotEqual(checkpoint.returncode, 0)
            self.assertEqual(result.returncode, 1)
            self.assertIn("wrap failed: handoff invalid: open_loops[0].session_id must be a non-empty string", result.stderr)
            missing = subprocess.run([sys.executable, str(ENGINE), "wrap-check", "--written-handoff", str(Path(directory) / "absent.json")], text=True, capture_output=True)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("handoff invalid: no file at", missing.stderr)

    def test_bound_record_must_not_predate_the_last_change(self):
        user = ["--user-profile", str(PROFILES / "user.md")]
        ledger = [{"kind": "file", "path": "/x", "checkout": "/", "session_id": "wrap-session", "ts": "2026-10-06T13:00:00Z"},
                  {"repo_root": "/", "head": "a", "ts": "2026-10-06T15:00:00Z"}]
        with tempfile.TemporaryDirectory() as directory:
            _, stale, _ = self.wrap(directory, [], user, "2026-10-06T12:59:00Z", ledger)
            self.assertEqual(stale.returncode, 1)
            self.assertIn("wrap failed: record stale: /record-step recorded at 2026-10-06T12:59:00Z, older than the session's last change at 2026-10-06T13:00:00Z", stale.stderr)
        with tempfile.TemporaryDirectory() as directory:
            _, absent, _ = self.wrap(directory, [], user, None, ledger)
            self.assertEqual(absent.returncode, 1)
            self.assertIn("record not checked: /record-step is bound but no record time was supplied", absent.stderr)
        with tempfile.TemporaryDirectory() as directory:
            _, fresh, _ = self.wrap(directory, [], user, "2026-10-06T13:00:00Z", ledger)
            self.assertEqual(fresh.returncode, 0, fresh.stderr)
            self.assertEqual(json.loads(fresh.stdout)["record_check"], "passed")

    def start(self, directory, profile_args=()):
        """Run `plan` as the checklist's start does, against the test ledger."""
        environment = dict(os.environ, HANDOFF_LEDGER_DIR=directory)
        result = subprocess.run([sys.executable, str(ENGINE), "plan", *profile_args, "--session-id", "wrap-session"],
                                text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)

    def edit(self, directory, ts):
        return self.append_ledger(directory, {"kind": "file", "path": "/x", "checkout": "/", "session_id": "wrap-session", "ts": ts})

    def append_ledger(self, directory, row):
        with open(Path(directory) / "session-touched-paths.wrap-session.jsonl", "a") as handle:
            handle.write(json.dumps(row) + "\n")

    def test_wrap_up_commit_after_the_record_passes(self):
        user = ["--user-profile", str(PROFILES / "user.md")]
        with tempfile.TemporaryDirectory() as directory:
            self.edit(directory, "2026-10-06T11:00:00Z")
            self.start(directory, user)
            commit = {"repo_root": "/", "head": "b", "commit": "b", "session_id": "wrap-session", "ts": "2026-10-06T14:00:00Z"}
            _, result, _ = self.wrap(directory, [], user, "2026-10-06T13:00:00Z", [commit])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["record_check"], "passed")

    def test_wrap_up_lessons_edit_after_the_record_passes(self):
        user = ["--user-profile", str(PROFILES / "user.md")]
        with tempfile.TemporaryDirectory() as directory:
            self.edit(directory, "2026-10-06T11:00:00Z")
            self.start(directory, user)
            lesson = {"kind": "file", "path": "/rules/core.md", "checkout": "/", "session_id": "wrap-session", "ts": "2026-10-06T14:00:00Z"}
            _, result, _ = self.wrap(directory, [], user, "2026-10-06T13:00:00Z", [lesson])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["record_check"], "passed")

    def test_record_older_than_a_change_before_the_start_still_fails(self):
        user = ["--user-profile", str(PROFILES / "user.md")]
        with tempfile.TemporaryDirectory() as directory:
            self.edit(directory, "2026-10-06T12:00:00Z")
            self.start(directory, user)
            _, result, _ = self.wrap(directory, [], user, "2026-10-06T11:00:00Z")
            self.assertEqual(result.returncode, 1)
            self.assertIn("wrap failed: record stale: /record-step recorded at 2026-10-06T11:00:00Z, "
                          "older than the session's last change at 2026-10-06T12:00:00Z", result.stderr)

    def test_only_changes_after_the_latest_start_are_ignored(self):
        user = ["--user-profile", str(PROFILES / "user.md")]
        with tempfile.TemporaryDirectory() as directory:
            self.start(directory, user)
            self.edit(directory, "2026-10-06T14:00:00Z")
            self.start(directory, user)
            _, result, _ = self.wrap(directory, [], user, "2026-10-06T13:00:00Z")
            self.assertEqual(result.returncode, 1)
            self.assertIn("older than the session's last change at 2026-10-06T14:00:00Z", result.stderr)

    def test_without_a_start_marker_every_change_counts(self):
        user = ["--user-profile", str(PROFILES / "user.md")]
        with tempfile.TemporaryDirectory() as directory:
            _, result, _ = self.wrap(directory, [], user, "2026-10-06T11:00:00Z", [
                {"kind": "file", "path": "/x", "checkout": "/", "session_id": "wrap-session", "ts": "2026-10-06T12:00:00Z"}])
            self.assertEqual(result.returncode, 1)
            self.assertIn("older than the session's last change at 2026-10-06T12:00:00Z", result.stderr)

    def test_started_wrap_with_record_unbound_runs_no_record_check(self):
        with tempfile.TemporaryDirectory() as directory:
            self.edit(directory, "2026-10-06T12:00:00Z")
            self.start(directory)
            self.edit(directory, "2026-10-06T14:00:00Z")
            _, result, _ = self.wrap(directory, [])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"wrap": "ok", "record_check": "not run: record unbound"})

    def test_plan_writes_one_start_marker_that_is_not_a_change(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "session-touched-paths.wrap-session.jsonl"
            self.start(directory)
            rows = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual({rows[0]["kind"], rows[0]["session_id"]}, {"checklist-start", "wrap-session"})
            with mock.patch.dict(os.environ, {"HANDOFF_LEDGER_DIR": directory}):
                self.assertIsNone(self.engine.last_change("wrap-session"))
            self.start(directory)
            self.assertEqual(len(ledger.read_text().splitlines()), 2)

    def afk_state(self, directory, session_id):
        """Write the session record the configured state module reads for an unattended slate in progress."""
        modes = self.engine._load_session_mode_module()
        state = {"session_id": session_id, "mode": "afk", "updated_by": "slate-launch", "updated_at": "2026-10-06T12:00:00Z"}
        path = Path(directory) / session_id
        path.write_text(json.dumps(state))
        self.assertEqual(modes.read_state(path, session_id), state)
        return state

    def test_factory_sessions_and_subagents_never_run_the_checklist(self):
        self.assertEqual(self.engine.session_kind({"agent_id": "a1"}, "cli"), "subagent")
        self.assertEqual(self.engine.session_kind({}, "sdk-cli"), "factory")
        self.assertEqual(self.engine.session_kind({}, "cli"), "interactive")
        for payload, entrypoint in [({"session_id": "s", "agent_id": "a1"}, "cli"), ({"session_id": "s"}, "sdk-cli")]:
            with self.subTest(payload=payload, entrypoint=entrypoint):
                self.assertEqual(self.engine.wrap_cadence(payload, entrypoint), "none")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "handoff.json"
            environment = dict(os.environ, CLAUDE_CODE_ENTRYPOINT="sdk-cli", HANDOFF_PATH=str(target))
            for operation in (["plan"], ["plan", "--unattended"], ["wrap-check", "--written-handoff", str(target)]):
                with self.subTest(operation=operation):
                    result = subprocess.run([sys.executable, str(ENGINE), *operation], text=True, capture_output=True, env=environment)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("a factory session never runs the checklist or writes a handoff", result.stderr)
            self.assertFalse(target.exists())

    def test_unattended_slate_checkpoints_per_ticket_and_wraps_once_after_the_slate(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"UNATTENDED_STATE_DIR": directory}):
            state = self.afk_state(directory, "afk-session")
            self.assertEqual(self.engine.wrap_cadence({"session_id": "afk-session"}, "cli"), "checkpoint")
            # The completion verb returns the session to HITL: now the one full checklist runs.
            state.update(mode="hitl", approval_slate=None, approval_grant=None)
            (Path(directory) / "afk-session").write_text(json.dumps(state))
            self.assertEqual(self.engine.wrap_cadence({"session_id": "afk-session"}, "cli"), "checklist")
            self.assertEqual(self.engine.wrap_cadence({"session_id": "never-afk"}, "cli"), "checklist")

    def nudge(self, payload, environment):
        result = subprocess.run(["bash", str(NUDGE)], input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"] if result.stdout.strip() else ""

    def test_nudge_follows_the_wrap_cadence(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, UNATTENDED_STATE_DIR=directory, TMPDIR=directory, HOME=directory,
                               CHECKLIST_CONFIG_DIR=directory + "/config")
            self.afk_state(directory, "afk-session")
            commit = {"cwd": directory + "/Development/repo", "tool_input": {"command": "git commit -m x"}}
            tests = {"cwd": directory + "/Development/repo", "tool_input": {"command": "pytest -q"}, "tool_response": {"stdout": "3 passed"}}
            self.assertEqual(self.nudge(dict(commit, session_id="sub", agent_id="a1"), environment), "")
            self.assertEqual(self.nudge(dict(commit, session_id="factory"), dict(environment, CLAUDE_CODE_ENTRYPOINT="sdk-cli")), "")
            for _ in range(2):
                text = self.nudge(dict(commit, session_id="afk-session"), environment)
                self.assertIn("checkpoint now", text)
                self.assertIn("once, after the slate completion command", text)
            self.assertEqual(self.nudge(dict(tests, session_id="afk-session"), environment), "")
            self.assertIn("run /checklist before moving on", self.nudge(dict(commit, session_id="attended"), environment))

    def test_nudge_scope_comes_from_the_users_roots_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            environment = dict(os.environ, UNATTENDED_STATE_DIR=directory, TMPDIR=directory, HOME=directory,
                               CHECKLIST_CONFIG_DIR=str(config))
            commit = {"tool_input": {"command": "git commit -m x"}}
            self.assertIn("run /checklist", self.nudge(dict(commit, cwd="/anywhere", session_id="unscoped"), environment))
            config.mkdir()
            (config / "nudge-roots").write_text("# work trees\n~/work\n" + directory + "/notes/\n")
            self.assertIn("run /checklist", self.nudge(dict(commit, cwd=directory + "/work/repo", session_id="home-root"), environment))
            self.assertIn("run /checklist", self.nudge(dict(commit, cwd=directory + "/notes", session_id="absolute-root"), environment))
            self.assertEqual(self.nudge(dict(commit, cwd=directory + "/workshop", session_id="prefix-only"), environment), "")
            self.assertEqual(self.nudge(dict(commit, cwd="/anywhere", session_id="outside"), environment), "")

    def test_unattended_plan_states_the_pending_rule(self):
        result = subprocess.run([sys.executable, str(ENGINE), "plan", "--unattended"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["unattended"])
        self.assertIn("reports pending with the answer it needs, writes nothing, and the checklist continues", output["when_answer_needed"])
        attended = json.loads(subprocess.run([sys.executable, str(ENGINE), "plan"], text=True, capture_output=True).stdout)
        self.assertFalse(attended["unattended"])
        self.assertNotIn("when_answer_needed", attended)

    def test_completion_entry_points_require_a_written_handoff_in_both_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results.json"
            results.write_text(json.dumps([{"id": step["id"], "status": "run", "writes": []}
                                           for step in self.engine.compose([])]))
            receipts = root / "receipts.json"
            receipts.write_text("{}")
            malformed = root / "malformed.json"
            malformed.write_text("{")
            empty = root / "empty.json"
            empty.write_text("{}")
            for mode in [[], ["--unattended"]]:
                for operation, extra in [("report", ["--results", str(results)]), ("wrap-check", []),
                                         ("settle", ["--receipts", str(receipts)]), ("file", ["--filing", str(receipts)])]:
                    with self.subTest(mode=mode, operation=operation, handoff="omitted"):
                        result = subprocess.run([sys.executable, str(ENGINE), operation, *mode, *extra],
                                                text=True, capture_output=True)
                        self.assertEqual(result.returncode, 1, result.stdout)
                        self.assertIn("requires", result.stderr)
                        self.assertEqual(result.stdout, "")
                for path in [root / "absent.json", malformed, empty]:
                    for operation, flag, extra in [("report", "--handoff", ["--results", str(results)]),
                                                   ("wrap-check", "--written-handoff", [])]:
                        with self.subTest(mode=mode, operation=operation, handoff=path.name):
                            result = subprocess.run([sys.executable, str(ENGINE), operation, *mode,
                                                     flag, str(path), *extra], text=True, capture_output=True)
                            self.assertEqual(result.returncode, 1, result.stdout)
                            self.assertEqual(result.stdout, "")
                # Planning a new session intentionally has no resumed handoff.
                planned = subprocess.run([sys.executable, str(ENGINE), "plan", *mode, "--session-id", "wrap-session"],
                                         text=True, capture_output=True)
                self.assertEqual(planned.returncode, 0, planned.stderr)
                self.assertNotIn("report", json.loads(planned.stdout))
                self.assertNotIn("wrap", json.loads(planned.stdout))
                # Settling source input is not a completion check, even with no loops.
                settled = subprocess.run([sys.executable, str(ENGINE), "settle", *mode, "--handoff", str(empty),
                                          "--receipts", str(receipts)], text=True, capture_output=True)
                self.assertEqual(settled.returncode, 0, settled.stderr)
                self.assertEqual(json.loads(settled.stdout), {})

    def test_pending_step_writes_nothing_and_the_run_continues(self):
        plan = self.engine.compose([self.engine.load_profile(PROFILES / "user.md")])
        results = [{"id": step["id"], "status": "run", "writes": []} for step in plan]
        results[1] = {"id": "knowledge", "status": "pending", "reason": "approve which findings to capture", "writes": []}
        self.assertEqual(self.engine.check_report(plan, results, unattended=True), [])
        wrote = copy.deepcopy(results)
        wrote[1]["writes"] = ["~/notes/output/x.md"]
        self.assertEqual(self.engine.check_report(plan, wrote, unattended=True),
                         ["knowledge: a pending step writes nothing, but wrote ['~/notes/output/x.md']"])
        silent = copy.deepcopy(results)
        del silent[1]["reason"]
        self.assertEqual(self.engine.check_report(plan, silent, True), ["knowledge: a pending step names the answer it needs"])
        stopped = results[:2]
        problems = self.engine.check_report(plan, stopped, unattended=True)
        self.assertIn("steps reported ['record', 'knowledge'], plan is", problems[0])
        self.assertEqual(problems[-1], "handoff: an unattended run still writes the handoff")
        asked = copy.deepcopy(results)
        asked[0]["status"] = "waiting"
        self.assertEqual(self.engine.check_report(plan, asked), ["record: status 'waiting' is not one of run, carried, pending, failed"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            path.write_text(json.dumps(results))
            user = ["--user-profile", str(PROFILES / "user.md")]
            _, _, written = self.wrap(directory, [])
            unavailable = ["--no-summary", "session summary unavailable: HTTP 502", "--handoff", str(written)]
            result = subprocess.run([sys.executable, str(ENGINE), "report", *user, "--unattended", "--results", str(path), *unavailable], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"summary": None, "summary_unavailable": "session summary unavailable: HTTP 502",
                                                         "report": "ok", "pending": ["knowledge"], "filing": {}, "warnings": []})
            path.write_text(json.dumps(wrote))
            result = subprocess.run([sys.executable, str(ENGINE), "report", *user, "--unattended", "--results", str(path), *unavailable], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("checklist: report invalid: knowledge: a pending step writes nothing", result.stderr)

    def test_report_starts_with_the_session_summary(self):
        """The record binding composes the session summary; the report leads with it."""
        user = ["--user-profile", str(PROFILES / "user.md")]
        plan = self.engine.compose([self.engine.load_profile(PROFILES / "user.md")])
        results = [{"id": step["id"], "status": "run", "writes": []} for step in plan]
        text = "## Session summary\n\n- No record outcome closed or moved this session.\n"
        with tempfile.TemporaryDirectory() as directory:
            path, summary = Path(directory) / "results.json", Path(directory) / "summary.md"
            path.write_text(json.dumps(results))
            summary.write_text(text)

            _, _, written = self.wrap(directory, [])

            def report(*extra, profile=user):
                return subprocess.run([sys.executable, str(ENGINE), "report", *profile, "--results", str(path), "--handoff", str(written), *extra],
                                      text=True, capture_output=True)

            result = report("--summary", str(summary))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(list(output)[0], "summary")
            self.assertEqual(output["summary"], text)

            missing = report()
            self.assertEqual(missing.returncode, 1)
            self.assertIn("checklist: report invalid: session summary: missing; pass --summary <file> from /record-step", missing.stderr)
            # An older record binding composes nothing; the error names the path that still wraps.
            self.assertIn('--no-summary "/record-step composed no session summary"', missing.stderr)
            older = report("--no-summary", "/record-step composed no session summary")
            self.assertEqual(older.returncode, 0, older.stderr)
            self.assertEqual(list(json.loads(older.stdout))[:2], ["summary", "summary_unavailable"])

            both = report("--summary", str(summary), "--no-summary", "why")
            self.assertEqual(both.returncode, 1)
            self.assertIn("pass --summary or --no-summary, not both", both.stderr)

            summary.write_text("  \n")
            empty = report("--summary", str(summary))
            self.assertEqual(empty.returncode, 1)
            self.assertIn("session summary: the summary file is empty", empty.stderr)

            path.write_text(json.dumps([{"id": step["id"], "status": "carried" if "slot" in step else "run", "writes": []}
                                        for step in self.engine.compose([])]))
            unbound = report(profile=[])
            self.assertEqual(unbound.returncode, 0, unbound.stderr)
            self.assertEqual(json.loads(unbound.stdout)["summary_unavailable"], "record unbound: no binding composes a session summary")

    def complete(self, directory, session_id, updated_by="slate-completed"):
        """Rewrite the record as the completion command leaves it: attended, marked by the command."""
        state = {"session_id": session_id, "mode": "hitl", "updated_by": updated_by, "updated_at": "2026-10-06T13:00:00Z"}
        (Path(directory) / session_id).write_text(json.dumps(state))

    def test_slate_completion_selects_the_unattended_wrap_until_it_passes(self):
        verb = {"tool_input": {"command": "printf x | bash hooks/slate.sh complete-slate"}}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"UNATTENDED_STATE_DIR": directory}):
            self.afk_state(directory, "wrap-session")
            # A refused completion leaves the session unattended: still mid-slate.
            self.assertEqual(self.engine.wrap_cadence(dict(verb, session_id="wrap-session"), "cli"), "checkpoint")
            self.complete(directory, "wrap-session")
            self.assertEqual(self.engine.wrap_cadence({"session_id": "wrap-session"}, "cli"), "checklist")
            self.assertEqual(self.engine.wrap_cadence(dict(verb, session_id="wrap-session"), "cli"), "unattended-checklist")
            self.assertEqual(self.engine.wrap_cadence({"session_id": "wrap-session"}, "cli"), "unattended-checklist")
            self.complete(directory, "other", "pre-tool-use")
            self.assertEqual(self.engine.wrap_cadence(dict(verb, session_id="other"), "cli"), "checklist")
            _, result, _ = self.wrap(directory, [])
            self.assertEqual(result.returncode, 1)
            self.assertIn("slate completed unattended; run the checklist with --unattended", result.stderr)
            target = Path(directory) / "wrapped.json"
            unattended = subprocess.run([sys.executable, str(ENGINE), "wrap-check", "--unattended", "--written-handoff", str(target)], text=True, capture_output=True)
            self.assertEqual(unattended.returncode, 0, unattended.stderr)
            self.assertEqual(self.engine.wrap_cadence({"session_id": "wrap-session"}, "cli"), "checklist")

    def test_state_dir_resolves_from_the_environment_then_the_configuration_then_the_package_default(self):
        marker = lambda: str(self.engine._unattended_marker("s1"))
        self.assertTrue(marker().startswith(self.state_dir.name + os.sep))
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"checklist_state_dir": directory + "/configured"}))
            env = {"CONTINUITY_CONFIG": str(config)}
            with mock.patch.dict(os.environ, env):
                os.environ.pop("CHECKLIST_STATE_DIR")
                self.assertEqual(marker(), directory + "/configured/s1.unattended-wrap")
                config.write_text("{}")
                self.assertEqual(marker(), str(Path("~/.local/state/continuity/checklist/s1.unattended-wrap").expanduser()))

    def test_the_plan_slate_command_selects_the_unattended_wrap(self):
        """A slate of plans ends with its own completion command."""
        verb = {"tool_input": {"command": "printf x | bash hooks/slate.sh complete-plan-slate"}}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {"UNATTENDED_STATE_DIR": directory, "CHECKLIST_STATE_DIR": directory}):
            self.afk_state(directory, "plans-session")
            self.assertEqual(self.engine.wrap_cadence(dict(verb, session_id="plans-session"), "cli"), "checkpoint")
            self.complete(directory, "plans-session")
            self.assertEqual(self.engine.wrap_cadence(dict(verb, session_id="plans-session"), "cli"),
                             "unattended-checklist")
            environment = dict(os.environ, UNATTENDED_STATE_DIR=directory, TMPDIR=directory, HOME=directory,
                               CHECKLIST_STATE_DIR=directory + "/nudge")
            self.complete(directory, "nudged-session")
            nudge = dict(verb, cwd=directory + "/Development/repo", session_id="nudged-session")
            self.assertIn("pass --unattended to plan, report, and wrap-check", self.nudge(nudge, environment))

    def test_nudge_names_the_unattended_wrap_after_the_completion_command(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, UNATTENDED_STATE_DIR=directory, TMPDIR=directory, HOME=directory)
            self.complete(directory, "done-session", "scope-completed")
            verb = {"cwd": directory + "/Development/repo", "session_id": "done-session",
                    "tool_input": {"command": "printf x | bash hooks/slate.sh complete-scope"}}
            text = self.nudge(verb, environment)
            self.assertIn("pass --unattended to plan, report, and wrap-check", text)
            self.assertEqual(self.nudge(verb, environment), "")
            self.complete(directory, "hitl-session", "pre-tool-use")
            self.assertEqual(self.nudge(dict(verb, session_id="hitl-session"), environment), "")

    def guard(self, payload, **environment):
        result = subprocess.run(["bash", str(GUARD)], input=json.dumps(payload), text=True, capture_output=True,
                                env=dict(os.environ, **environment))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None

    def test_guard_denies_subagents_and_factory_sessions_the_checklist(self):
        commands = ["python3 ~/.local/share/continuity/scripts/lib/checklist.py plan --unattended",
                    "python3 scripts/lib/checklist.py wrap-check --written-handoff h.json",
                    "bash \"$HOME/.local/share/continuity/skills/checkpoint/scripts/checkpoint.sh\" <<'JSON'\n{}\nJSON",
                    "python3 scripts/lib/handoff.py checkpoint --cwd ."]
        for command in commands:
            payload = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": command}}
            with self.subTest(command=command):
                denied = self.guard(dict(payload, agent_id="a1"))
                self.assertEqual(denied["permissionDecision"], "deny")
                self.assertIn("a subagent session never runs the checklist", denied["permissionDecisionReason"])
                self.assertIn("a factory session", self.guard(payload, CLAUDE_CODE_ENTRYPOINT="sdk-cli")["permissionDecisionReason"])
                self.assertIsNone(self.guard(payload))
        self.assertIsNone(self.guard({"agent_id": "a1", "tool_input": {"command": "git status"}}))
        self.assertIsNone(self.guard({"agent_id": "a1", "tool_input": {"command": "python3 checklist.py wrap-cadence"}}))

    def test_guard_denies_nothing_to_an_interactive_session(self):
        payload = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "python3 scripts/lib/checklist.py wrap-check"}}
        self.assertIsNone(self.guard(payload, CLAUDE_CODE_ENTRYPOINT="cli"))


class UnattendedConfigurationTests(unittest.TestCase):
    """The package knows unattended mode only through the `unattended` configuration section."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("checklist", ENGINE)
        cls.engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.engine)

    def configure(self, directory, section):
        config = Path(directory) / "continuity.json"
        config.write_text(json.dumps({} if section is None else {"unattended": section}))
        return mock.patch.dict(os.environ, {"CONTINUITY_CONFIG": str(config), "CLAUDE_CODE_ENTRYPOINT": "cli",
                                            "UNATTENDED_STATE_DIR": directory, "CHECKLIST_STATE_DIR": directory,
                                            "HANDOFF_LEDGER_DIR": directory})

    def test_without_the_section_every_session_is_attended(self):
        with tempfile.TemporaryDirectory() as directory, self.configure(directory, None):
            (Path(directory) / "s1").write_text(json.dumps({"session_id": "s1", "mode": "afk"}))
            self.assertIsNone(self.engine._load_session_mode_module())
            self.assertEqual(self.engine.wrap_cadence({"session_id": "s1"}, "cli"), "checklist")
            self.assertFalse(self.engine.is_completion_command("bash slate.sh complete-slate"))

    def test_a_configured_provider_makes_an_unattended_session_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory, self.configure(directory, UNATTENDED):
            (Path(directory) / "s1").write_text(json.dumps({"session_id": "s1", "mode": "afk"}))
            self.assertEqual(self.engine.wrap_cadence({"session_id": "s1"}, "cli"), "checkpoint")

    def test_a_malformed_section_is_a_configuration_error(self):
        cadence = lambda: self.engine.wrap_cadence({"session_id": "s1"}, "cli")
        completion = lambda: self.engine.is_completion_command("bash slate.sh complete-slate")
        for section, ask, message in [("nope", cadence, "unattended must be an object"),
                                      ({"state_module": 3}, cadence, "unattended.state_module must be a non-empty string"),
                                      ({"completion_command": ""}, completion, "unattended.completion_command must be a non-empty string"),
                                      ({"state_module": "/no/such/module.py"}, cadence, "No such file")]:
            with self.subTest(section=section), tempfile.TemporaryDirectory() as directory, self.configure(directory, section):
                with self.assertRaisesRegex((ValueError, OSError), message):
                    ask()

    def test_completion_command_cli_answers_by_exit_status(self):
        with tempfile.TemporaryDirectory() as directory, self.configure(directory, UNATTENDED):
            def ask(command):
                return subprocess.run([sys.executable, str(ENGINE), "is-completion-command"], text=True, capture_output=True,
                                      input=json.dumps({"tool_input": {"command": command}}), env=dict(os.environ)).returncode
            self.assertEqual(ask("bash hooks/slate.sh complete-slate"), 0)
            self.assertEqual(ask("bash hooks/slate.sh start-slate"), 1)
            self.assertEqual(ask("git commit -m x"), 1)


if __name__ == "__main__":
    unittest.main()
