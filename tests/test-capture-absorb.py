#!/usr/bin/env python3
"""Isolated document-review capture using the package's public wiki contract."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'skills/absorb/scripts/distribution.py'

class CaptureAbsorb(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for folder in ('raw/research', 'output', 'docs'):
            (self.root / folder).mkdir(parents=True)
        for name in ('log.md', 'DECISIONS.md'):
            (self.root / 'docs' / name).touch()
        self.profile = self.root / 'profile.md'
        self.profile.write_text(f'---\nprofile_version: 4\nknowledge_root: {self.root}\nwiki_enabled: false\noperation_log_file: docs/log.md\ndecision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Test workflow\n---\n')
        self.source = self.root / 'raw/research/contract.md'
        self.source.write_text((REPO / 'contracts/karpathy-wiki.md').read_text())

    def module(self):
        self.assertTrue(HELPER.is_file(), 'shared distribution helper must be packaged')
        spec = importlib.util.spec_from_file_location('distribution', HELPER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def capture(self, **overrides):
        return self.module().capture(self.profile, 'contract-review', '2026-10-09',
            'Public contract review', [{'id': 'contract', 'path': 'raw/research/contract.md',
             'primary': True, 'coverage': 'complete'}], **overrides)

    def row(self, kind='action', **overrides):
        row = dict(id='A1', decision='D1', kind=kind, evidence=['contract'],
            target='Test workflow', change='Review the public contract', owner='requester',
            authorization='approved', preconditions=[], state='pending')
        row.update(overrides)
        return row

    def test_default_in_place_and_repeat_preserves_user_edits(self):
        record = self.capture()
        self.assertEqual(record.parent, self.root / 'meetings')
        record.write_text(record.read_text() + '\nUser authored notes.\n')
        self.assertEqual(self.capture(), record)
        self.assertIn('User authored notes.', record.read_text())
        self.assertEqual(list((self.root / 'output').iterdir()), [])

    def test_custom_template_override_and_actual_event_url(self):
        template = self.root / 'custom.md'
        template.write_text('# {{title}}\nOptional coaching\n{{date}}\n')
        url = 'https://calendar.example.invalid/events/contract-review'
        record = self.capture(template=str(template), event_url=url)
        self.assertIn('Optional coaching', record.read_text())
        self.assertIn(url, record.read_text())
        self.assertEqual(self.module().read_record(record)['event_url'], url)

    def test_invalid_explicit_template_and_folder_escape_fail_without_writes(self):
        for template in ('missing.md', 'bad.txt'):
            with self.subTest(template=template):
                with self.assertRaises(ValueError):
                    self.capture(template=template)
        self.assertFalse((self.root / 'meetings').exists())
        self.profile.write_text(self.profile.read_text().replace('wiki_enabled: false', 'wiki_enabled: false\nmeeting_record_folder: ../outside'))
        with self.assertRaises((ValueError, SystemExit)):
            self.capture()

    def test_only_approved_rows_run_and_retry_reuses_confirmed_receipts(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1', 'D2'], [self.row(), self.row(id='A2', decision='D2', authorization='pending')])
        calls = []
        def workflow(request):
            calls.append(request)
            return dict(confirmed=True, receipt='task:contract-review', target=request['row']['target'])
        mod.execute(self.profile, record, {'action': workflow})
        mod.execute(self.profile, record, {'action': workflow})
        self.assertEqual(len(calls), 1)
        state = mod.read_record(record)
        self.assertEqual(state['rows'][0]['state'], 'complete')
        self.assertEqual(state['rows'][1]['state'], 'pending')
        self.assertEqual(record.parent, self.root / 'meetings')

    def test_preconditions_missing_receipts_and_uncertain_effects_stay_pending(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row(preconditions=['confirm current context'])])
        calls = []
        mod.execute(self.profile, record, {'action': lambda req: calls.append(req)})
        self.assertEqual(calls, [])
        mod.set_plan(record, ['D1'], [self.row()])
        mod.set_plan(record, ['D1'], [self.row()])  # renewed approval of changed preconditions
        def uncertain(request):
            calls.append(request); return {'confirmed': False}
        mod.execute(self.profile, record, {'action': uncertain})
        mod.execute(self.profile, record, {'action': uncertain})
        self.assertEqual(len(calls), 1, 'uncertain writes require read-back reconciliation, never automatic repeat')
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'pending')

    def test_wiki_disabled_and_generated_evidence_are_rejected(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row(kind='wiki')])
        mod.execute(self.profile, record, {'wiki': lambda req: self.fail('disabled wiki invoked')})
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'pending')
        with self.assertRaises(ValueError):
            mod.set_plan(record, ['D1'], [self.row(evidence=['not-a-source'])])
        with self.assertRaises(ValueError):
            mod.set_plan(record, [], [self.row()])

    def test_writing_routes_and_no_destination_preserve_authored_prose(self):
        mod = self.module(); record = self.capture()
        authored = self.root / 'docs/draft.md'; authored.write_text('Authored draft unchanged.\n')
        rows = [self.row(id=f'W{i}', kind='writing', opportunity=kind,
            author='contract author', angle='Explain scoped compilation',
            addition='Add a source-linked note about the selected subset', privacy='public contract only',
            coverage={'ideas': 'searched', 'drafts': 'searched', 'published': 'unavailable'},
            target='docs/draft.md', workflow='local writing workflow')
            for i, kind in enumerate(('new', 'enrich', 'published-followup'))]
        mod.set_plan(record, ['D1'], rows)
        seen = []
        def writing(req):
            seen.append(req['row']['opportunity'])
            return dict(confirmed=True, receipt='writing:' + req['idempotency_key'], target=req['row']['target'])
        mod.execute(self.profile, record, {'writing': writing})
        mod.execute(self.profile, record, {'writing': writing})
        self.assertEqual(seen, ['new', 'enrich', 'published-followup'])
        self.assertEqual(authored.read_text(), 'Authored draft unchanged.\n')
        rows[0]['id'] = 'W4'; rows[0]['target'] = ''; rows[0]['workflow'] = ''
        mod.set_plan(record, ['D1'], [rows[0]])
        mod.execute(self.profile, record, {'writing': writing})
        self.assertEqual(len(seen), 3)
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'pending')
        rows[0]['authorization'] = 'declined'
        mod.set_plan(record, ['D1'], [rows[0]])
        mod.set_plan(record, [], [], writing_result='none: no useful opportunity')
        self.assertIn('no useful opportunity', mod.read_record(record)['writing_result'])

    def test_changed_scope_drops_approval_but_preserves_prior_receipt(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row()])
        mod.execute(self.profile, record, {'action': lambda req: dict(confirmed=True, receipt='saved-task', target=req['row']['target'])})
        mod.set_plan(record, ['D1'], [self.row(change='Different action')])
        state = mod.read_record(record)
        self.assertEqual(state['rows'][0]['authorization'], 'pending')
        self.assertEqual(len(state['history']), 1)
        self.assertEqual(state['history'][0]['receipt']['receipt'], 'saved-task')

    def test_separate_research_and_transcript_retention_and_repaired_links(self):
        mod = self.module(); meeting = self.capture()
        mod.set_plan(meeting, ['D1'], [self.row(authorization='declined')])
        intake = self.root / 'raw/inbox'; intake.mkdir()
        transcript = intake / 'contract.md'; transcript.write_bytes(self.source.read_bytes())
        links = self.root / 'docs/references.md'; links.write_text('[source](../raw/inbox/contract.md)\n')
        retained = mod.file_source(self.root, meeting, transcript, 'raw/archive/reviews', [meeting, links])
        self.assertFalse(transcript.exists()); self.assertEqual(retained.read_bytes(), self.source.read_bytes())
        self.assertIn('../raw/archive/reviews/contract.md', links.read_text())
        self.assertTrue(meeting.exists())
        research = self.root / 'output/research.md'
        research.write_text('# Public contract research\n')
        mod.initialize_research(research, [{'id': 'contract', 'path': 'raw/research/contract.md', 'primary': True, 'coverage': 'complete'}])
        mod.set_plan(research, ['D1'], [self.row(authorization='declined')])
        archived = mod.finalize(self.root, research, [links])
        self.assertEqual(archived.parent, self.root / 'raw/derived')
        self.assertIn('compile_mode: exclude', archived.read_text())
        self.assertFalse(research.exists())

    def test_cli_dispatch_uses_real_local_workflow_and_saved_receipts(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row(target='docs/task.json')])
        adapter = self.root / 'workflow.py'
        adapter.write_text("""import json, pathlib, sys
request = json.load(sys.stdin)
target = pathlib.Path(request['knowledge_root']) / request['row']['target']
if not target.exists():
    target.write_text(json.dumps({'identity': request['idempotency_key'], 'change': request['row']['change']}))
saved = json.loads(target.read_text())
print(json.dumps({'confirmed': saved['identity'] == request['idempotency_key'], 'receipt': saved['identity'], 'target': request['row']['target']}))
""")
        config = self.root / 'workflows.json'
        config.write_text(json.dumps({'action': ['python3', str(adapter)]}))
        command = ['python3', str(HELPER), '--profile', str(self.profile), 'execute', str(record), '--workflows', str(config)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        receipt = (self.root / 'docs/task.json').read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((self.root / 'docs/task.json').read_bytes(), receipt)
        self.assertEqual(json.loads(second.stdout)['rows'][0]['state'], 'complete')

    def enable_wiki(self):
        (self.root / 'wiki').mkdir()
        (self.root / 'wiki/hot.md').touch()
        self.profile.write_text(self.profile.read_text().replace('wiki_enabled: false',
            'wiki_enabled: true\nhot_file: wiki/hot.md\nwiki_followup_destination: Maintenance'))

    def test_wiki_workflow_gets_only_selected_primary_sources(self):
        self.enable_wiki()
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row(kind='wiki')])
        calls = []
        def compiler(req):
            calls.append(req)
            return dict(confirmed=True, receipt='wiki:contract', target=req['row']['target'])
        mod.execute(self.profile, record, {'wiki': compiler})
        self.assertEqual([s['id'] for s in calls[0]['sources']], ['contract'])
        self.assertEqual(calls[0]['sources'][0]['path'], 'raw/research/contract.md')
        self.assertNotIn(str(record), [s.get('path') for s in calls[0]['sources']])

    def test_excluded_artifact_cannot_be_promoted_to_primary_by_a_flag(self):
        self.enable_wiki()
        self.source.write_text('---\nuse: artifact\ncompile_mode: exclude\n---\nDerived summary.\n')
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row(kind='wiki')])
        calls = []
        mod.execute(self.profile, record, {'wiki': lambda req: calls.append(req)})
        self.assertEqual(calls, [])
        self.assertIn('primary', mod.read_record(record)['rows'][0]['error'])

    def test_direct_row_edits_invalidate_approval_and_completed_state(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row()])
        mod.execute(self.profile, record, {'action': lambda req: dict(confirmed=True, receipt='saved', target=req['row']['target'])})
        state = mod.read_record(record); state['rows'][0]['change'] = 'Changed scope in editor'
        mod.save(record, state)
        calls = []
        mod.execute(self.profile, record, {'action': lambda req: calls.append(req)})
        self.assertEqual(calls, [])
        state = mod.read_record(record)
        self.assertEqual(state['rows'][0]['authorization'], 'pending')
        self.assertEqual(state['history'][0]['receipt']['receipt'], 'saved')

    def test_reconcile_confirmed_and_verified_absent_external_effects(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row()])
        mod.execute(self.profile, record, {'action': lambda req: {'confirmed': False}})
        with self.assertRaises(ValueError):
            mod.reconcile(record, 'A1', {'absent': True})
        mod.reconcile(record, 'A1', {'absent': True, 'checked': 'Task search read-back'})
        mod.execute(self.profile, record, {'action': lambda req: {'confirmed': False}})
        mod.reconcile(record, 'A1', dict(confirmed=True, receipt='read-back-task', target='Test workflow'))
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'complete')

    def test_retention_preserves_original_path_and_rebases_source_links(self):
        mod = self.module()
        artifact = self.root / 'output/review.md'
        artifact.write_text('# Review\n[source](../raw/research/contract.md)\n')
        mod.initialize_research(artifact, [{'id': 'contract', 'path': 'raw/research/contract.md', 'primary': True, 'coverage': 'complete'}])
        mod.set_plan(artifact, [], [], writing_result='none: documentation review')
        archived = mod.finalize(self.root, artifact, [])
        state = mod.read_record(archived)
        self.assertEqual(state['archived_from'], 'output/review.md')
        self.assertIn('[source](../research/contract.md)', archived.read_text())
        self.assertEqual((archived.parent / '../research/contract.md').resolve(), self.source)

    def test_uncertain_effect_cannot_be_declined_and_filed(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row()])
        mod.execute(self.profile, record, {'action': lambda req: {'confirmed': False}})
        with self.assertRaises(ValueError):
            mod.set_plan(record, ['D1'], [self.row(authorization='declined')])
        with self.assertRaises(ValueError):
            mod.finalize(self.root, record, [])

    def test_failed_research_reference_repair_remains_pending_without_move(self):
        mod = self.module(); artifact = self.root / 'output/review.md'
        artifact.write_text('# Review\n')
        mod.initialize_research(artifact, [{'id': 'contract', 'path': 'raw/research/contract.md', 'primary': True, 'coverage': 'complete'}])
        mod.set_plan(artifact, [], [])
        with self.assertRaises(ValueError):
            mod.finalize(self.root, artifact, [self.root / 'docs/missing.md'])
        self.assertTrue(artifact.exists())
        self.assertNotEqual(mod.read_record(artifact)['status'], 'absorbed')

    def test_pending_routes_keep_intake_and_collisions_never_overwrite(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, ['D1'], [self.row()])
        with self.assertRaises(ValueError):
            mod.finalize(self.root, record, [])
        intake = self.root / 'raw/inbox'; intake.mkdir()
        transcript = intake / 'contract.md'; transcript.write_bytes(self.source.read_bytes())
        with self.assertRaises(ValueError):
            mod.file_source(self.root, record, transcript, 'raw/archive/reviews', [])
        self.assertTrue(transcript.exists())
        mod.set_plan(record, ['D1'], [self.row(authorization='declined')])
        archive = self.root / 'raw/archive/reviews'; archive.mkdir(parents=True)
        (archive / 'contract.md').write_text('Different source.\n')
        with self.assertRaises(ValueError):
            mod.file_source(self.root, record, transcript, 'raw/archive/reviews', [])
        self.assertEqual((archive / 'contract.md').read_text(), 'Different source.\n')

if __name__ == '__main__':
    unittest.main()
