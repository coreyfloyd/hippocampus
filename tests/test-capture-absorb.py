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

    def attach_source(self, mod, record, source):
        state = mod.read_record(record)
        relative = source.relative_to(self.root).as_posix()
        state['sources'].extend(mod.sources_for(self.root,
            [dict(id=relative, path=relative, primary=True, coverage='complete')]))
        mod.save(record, state)

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

    def test_meaningful_meeting_filename(self):
        record = self.capture()
        self.assertEqual(record.name, '2026-10-09-public-contract-review.md')

    def test_different_meetings_with_same_title_keep_distinct_records(self):
        first = self.capture()
        original = first.read_bytes()
        mod = self.module()
        second = mod.capture(self.profile, 'other-contract-review', '2026-10-09',
            'Public contract review', mod.read_record(first)['sources'])
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.startswith('2026-10-09-public-contract-review-'))
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(mod.read_record(second)['record_id'], 'other-contract-review')

    def test_retry_reuses_renamed_existing_record_and_user_edits(self):
        record = self.capture()
        renamed = record.with_name('my-reviewed-meeting.md')
        record.rename(renamed)
        renamed.write_text(renamed.read_text() + '\nMy edited purpose.\n')
        before = renamed.read_bytes()
        self.assertEqual(self.capture(), renamed)
        self.assertEqual(renamed.read_bytes(), before)

    def test_title_change_on_retry_does_not_rename_or_rewrite(self):
        record = self.capture(); before = record.read_bytes()
        mod = self.module()
        retried = mod.capture(self.profile, 'contract-review', '2026-10-09',
            'Revised purpose', mod.read_record(record)['sources'])
        self.assertEqual(retried, record)
        self.assertEqual(record.read_bytes(), before)

    def test_provider_and_kind_are_metadata_not_filename_decoration(self):
        mod = self.module()
        source = self.root / 'raw/research/Zoom-Public contract review-transcript.md'
        source.write_text('Original transcript.\n')
        record = mod.capture(self.profile, 'provider-meeting', '2026-10-09',
            'Zoom-Public contract review-transcript',
            [dict(id='provider-source', path=source.relative_to(self.root).as_posix(),
                  primary=True, coverage='complete', provider='Zoom', kind='transcript')])
        self.assertEqual(record.name, '2026-10-09-public-contract-review.md')
        self.assertEqual(mod.read_record(record)['sources'][0]['provider'], 'Zoom')
        mod.set_plan(record, [], [])
        retained = mod.file_source(self.root, record, source, 'raw/archive/meetings', [])
        self.assertEqual(retained.name, 'public-contract-review.md')
        self.assertEqual(retained.read_text(), 'Original transcript.\n')
        state = mod.read_record(record)
        self.assertEqual(state['sources'][0]['kind'], 'transcript')
        self.assertEqual(state['sources'][0]['path'], 'raw/archive/meetings/public-contract-review.md')
        self.assertEqual(mod.file_source(self.root, record, retained, 'raw/archive/meetings', []), retained)

    def test_provider_only_source_uses_record_subject_and_safe_collision(self):
        mod = self.module()
        source = self.root / 'raw/research/Zoom-transcript.md'
        source.write_text('Primary meeting evidence.\n')
        record = mod.capture(self.profile, 'provider-only', '2026-10-09',
            'Public contract review', [dict(id='provider-source',
                path=source.relative_to(self.root).as_posix(), primary=True,
                coverage='complete', provider='Zoom', kind='transcript')])
        mod.set_plan(record, [], [])
        target = self.root / 'raw/archive/meetings' / record.name
        target.parent.mkdir(parents=True); target.write_text('Different meeting.\n')
        with self.assertRaisesRegex(ValueError, 'collision'):
            mod.file_source(self.root, record, source, 'raw/archive/meetings', [])
        self.assertTrue(source.exists())
        self.assertEqual(target.read_text(), 'Different meeting.\n')
        target.unlink()
        retained = mod.file_source(self.root, record, source, 'raw/archive/meetings', [])
        self.assertEqual(retained.name, record.name)
        self.assertEqual(retained.read_text(), 'Primary meeting evidence.\n')

    def test_meaningful_name_preserves_unrelated_existing_prose(self):
        folder = self.root / 'meetings'; folder.mkdir()
        unrelated = folder / '2026-10-09-public-contract-review.md'
        unrelated.write_text('User authored unrelated notes.\n')
        record = self.capture()
        self.assertNotEqual(record, unrelated)
        self.assertTrue(record.name.startswith('2026-10-09-public-contract-review-'))
        self.assertEqual(unrelated.read_text(), 'User authored unrelated notes.\n')

    def test_empty_subject_refuses_before_creating_meeting_folder(self):
        mod = self.module()
        with self.assertRaisesRegex(ValueError, 'meaningful'):
            mod.capture(self.profile, 'empty-subject', '2026-10-09', 'transcript',
                [dict(id='contract', path='raw/research/contract.md',
                      primary=True, coverage='complete')])
        self.assertFalse((self.root / 'meetings').exists())

    def test_record_heading_uses_subject_without_provider_or_kind(self):
        mod = self.module()
        record = mod.capture(self.profile, 'display-subject', '2026-10-09',
            'Zoom-Public contract review-transcript', [dict(id='contract',
                path='raw/research/contract.md', provider='Zoom', kind='transcript',
                primary=True, coverage='complete')])
        self.assertTrue(record.read_text().startswith('# Public contract review\n'))
        self.assertEqual(mod.read_record(record)['title'], 'Public contract review')

    def test_capture_retry_after_source_filing_reuses_record_identity(self):
        mod = self.module(); record = self.capture(); mod.set_plan(record, [], [])
        mod.file_source(self.root, record, self.source, 'raw/archive/meetings', [])
        before = record.read_bytes()
        # Retry the original input; retained metadata now resolves its source.
        self.assertEqual(self.capture(), record)
        self.assertEqual(record.read_bytes(), before)

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

    def test_template_override_containment_and_absolute_external_template(self):
        outside = self.root.parent / (self.root.name + '-template.md')
        outside.write_text('# {{title}}\nExternal template\n')
        self.addCleanup(outside.unlink)
        (self.root / 'external.md').symlink_to(outside)
        for value in ('../' + outside.name, 'external.md'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'escapes knowledge_root'):
                    self.capture(template=value)
                self.assertFalse((self.root / 'meetings').exists())
        record = self.capture(template=str(outside))
        self.assertIn('External template', record.read_text())
        self.assertEqual(self.capture(template=str(outside)), record)

    def test_source_filing_rejects_unattached_raw_file_without_mutation(self):
        mod = self.module(); record = self.capture(); mod.set_plan(record, [], [])
        unrelated = self.root / 'raw/unrelated.md'
        unrelated.write_bytes(self.source.read_bytes())
        references = self.root / 'docs/references.md'
        references.write_text('[Unrelated](../raw/unrelated.md)\n')
        before = record.read_bytes(); reference_before = references.read_bytes()
        for supplied in (Path('raw/unrelated.md'), unrelated):
            with self.subTest(supplied=supplied):
                with self.assertRaisesRegex(ValueError, 'not attached to the meeting record'):
                    mod.file_source(self.root, record, supplied, 'raw/archive/reviews', [references])
                self.assertEqual(unrelated.read_bytes(), self.source.read_bytes())
                self.assertEqual(record.read_bytes(), before)
                self.assertEqual(references.read_bytes(), reference_before)
                self.assertFalse((self.root / 'raw/archive/reviews').exists())

    def test_source_filing_cli_rejects_unattached_file_without_mutation(self):
        mod = self.module(); record = self.capture(); mod.set_plan(record, [], [])
        unrelated = self.root / 'raw/unrelated.md'; unrelated.write_text('Unrelated evidence.\n')
        before = record.read_bytes()
        result = subprocess.run(['python3', str(HELPER), '--profile', str(self.profile),
            'file-source', str(record), '--source', 'raw/unrelated.md',
            '--retained-folder', 'raw/archive/reviews'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not attached to the meeting record', result.stderr)
        self.assertEqual(unrelated.read_text(), 'Unrelated evidence.\n')
        self.assertEqual(record.read_bytes(), before)
        self.assertFalse((self.root / 'raw/archive/reviews').exists())

    def test_source_filing_resolves_root_relative_and_absolute_raw_paths(self):
        mod = self.module(); record = self.capture()
        mod.set_plan(record, [], [], writing_result='none')
        for form in ('relative', 'absolute'):
            with self.subTest(form=form):
                source = self.root / 'raw' / (form + '.md')
                source.write_text('Original public source\n')
                state = mod.read_record(record)
                metadata = mod.sources_for(self.root, [dict(id=form, path=source.relative_to(self.root).as_posix(), primary=True, coverage='partial')])[0]
                state['sources'].append(metadata); mod.save(record, state)
                record.write_text(record.read_text() + f'\n[Source](../raw/{source.name})\n')
                supplied = source.relative_to(self.root) if form == 'relative' else source
                retained = mod.file_source(self.root, record, supplied, 'raw/archive/reviews', [])
                self.assertEqual(retained.read_text(), 'Original public source\n')
                self.assertFalse(source.exists())
                self.assertIn(f'../raw/archive/reviews/{source.name}', record.read_text())
                filed = next(s for s in mod.read_record(record)['sources'] if s['id'] == form)
                self.assertEqual(filed['path'], retained.relative_to(self.root).as_posix())
                self.assertEqual(filed['sha256'], metadata['sha256'])
                self.assertEqual(filed['coverage'], 'partial')
        before = record.read_bytes()
        outside = self.root / 'output/outside.md'; outside.write_text('Outside raw\n')
        (self.root / 'raw/escape.md').symlink_to(outside)
        for value in (Path('output/outside.md'), outside, Path('raw/escape.md'), Path('../outside.md')):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    mod.file_source(self.root, record, value, 'raw/archive/reviews', [])
                self.assertEqual(record.read_bytes(), before)
                self.assertTrue(outside.exists())
        intake = self.root / 'raw/intake.md'; intake.write_text('Public source\n')
        self.attach_source(mod, record, intake); before = record.read_bytes()
        (self.root / 'raw/linked-folder').symlink_to(self.root / 'output', target_is_directory=True)
        for folder in ('output', 'raw/linked-folder', '../outside'):
            with self.subTest(folder=folder):
                with self.assertRaises(ValueError):
                    mod.file_source(self.root, record, Path('raw/intake.md'), folder, [])
                self.assertTrue(intake.exists()); self.assertEqual(record.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'reference repair target unavailable'):
            mod.file_source(self.root, record, Path('raw/intake.md'), 'raw/archive/reviews', [Path('docs/missing.md')])
        self.assertTrue(intake.exists()); self.assertEqual(record.read_bytes(), before)
        self.assertFalse((self.root / 'raw/archive/reviews/intake.md').exists())

    def test_source_filing_cli_keeps_pending_and_colliding_intake_then_deduplicates(self):
        mod = self.module(); record = self.capture()
        source = self.root / 'raw/inbox/public.md'
        source.parent.mkdir(); source.write_text('Public source\n')
        self.attach_source(mod, record, source)
        relative_record = record.relative_to(self.root).as_posix()
        command = ['python3', str(HELPER), '--profile', str(self.profile),
                   'file-source', relative_record, '--source', 'raw/inbox/public.md',
                   '--retained-folder', 'raw/archive/reviews']
        mod.set_plan(record, ['D1'], [self.row()])
        before = record.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True, cwd=self.root / 'docs')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(source.exists()); self.assertEqual(record.read_bytes(), before)
        mod.set_plan(record, ['D1'], [self.row(authorization='declined')])
        target = self.root / 'raw/archive/reviews/public.md'
        target.parent.mkdir(parents=True); target.write_text('Different source\n')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('collision', result.stderr)
        self.assertEqual(target.read_text(), 'Different source\n'); self.assertTrue(source.exists())
        target.write_bytes(source.read_bytes())
        result = subprocess.run(command, capture_output=True, text=True, cwd=self.root / 'docs')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), target)
        self.assertFalse(source.exists()); self.assertEqual(target.read_text(), 'Public source\n')
        # Filing an already retained source at its destination is a harmless retry.
        self.assertEqual(mod.file_source(self.root, record, target.relative_to(self.root),
                                        'raw/archive/reviews', []), target)

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

    def declare_class(self, **overrides):
        declaration = dict(name='review', search_before_proposing=['existing reviews'],
                           required_fields=['author', 'addition'], workflow='review-workflow')
        declaration.update(overrides)
        self.profile.write_text(self.profile.read_text().split('```hippocampus-classes')[0] +
            '\n```hippocampus-classes\n' + json.dumps([declaration]) + '\n```\n')
        return declaration

    def test_custom_class_validation_and_declared_workflow(self):
        mod = self.module(); record = self.capture()
        self.assertIn('profile', mod.set_plan.__code__.co_varnames, 'planning must validate locally declared classes')
        row = self.row(kind='review', author='document author', addition='source-linked note',
                       search={'existing reviews': 'searched'}, workflow='review-workflow')
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            mod.set_plan(record, ['D1'], [row], profile=self.profile)
        self.declare_class()
        for field in ('author', 'addition', 'search'):
            missing = dict(row); missing.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                mod.set_plan(record, ['D1'], [missing], profile=self.profile)
        mod.set_plan(record, ['D1'], [row], profile=self.profile)
        calls = []
        def workflow(req):
            calls.append(req)
            return dict(confirmed=True, receipt='read-back-review', target=req['row']['target'])
        mod.execute(self.profile, record, {'review': lambda req: self.fail('undeclared workflow'),
                                           'review-workflow': workflow})
        mod.execute(self.profile, record, {'review-workflow': workflow})
        self.assertEqual(len(calls), 1)
        self.assertEqual(mod.read_record(record)['rows'][0]['receipt']['receipt'], 'read-back-review')

    def test_custom_destination_and_policy_change_require_renewed_approval(self):
        mod = self.module(); record = self.capture()
        self.declare_class(destination='docs/review.md')
        row = self.row(kind='review', author='author', addition='addition',
                       search={'existing reviews': 'unavailable'}, workflow='wrong', target='docs/other.md')
        mod.set_plan(record, ['D1'], [row], profile=self.profile)
        calls = []
        mod.execute(self.profile, record, {'review-workflow': lambda req: calls.append(req)})
        self.assertEqual(calls, [])
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'pending')
        row.update(workflow='review-workflow', target='docs/review.md')
        mod.set_plan(record, ['D1'], [row], profile=self.profile)
        mod.set_plan(record, ['D1'], [row], profile=self.profile)
        self.declare_class(destination='docs/review.md', required_fields=['author', 'addition', 'privacy'])
        mod.execute(self.profile, record, {'review-workflow': lambda req: calls.append(req)})
        self.assertEqual(calls, [])
        self.assertEqual(mod.read_record(record)['rows'][0]['authorization'], 'pending')

    def test_completed_custom_receipt_survives_policy_change(self):
        mod = self.module(); record = self.capture()
        self.declare_class()
        row = self.row(kind='review', author='author', addition='addition',
                       search={'existing reviews': 'searched'}, workflow='review-workflow')
        mod.set_plan(record, ['D1'], [row], profile=self.profile)
        mod.execute(self.profile, record, {'review-workflow': lambda req:
            dict(confirmed=True, receipt='saved-review', target=req['row']['target'])})
        self.declare_class(workflow='changed-workflow')
        mod.execute(self.profile, record, {})
        saved = mod.read_record(record)['rows'][0]
        self.assertEqual(saved['authorization'], 'approved')
        self.assertEqual(saved['state'], 'complete')
        self.assertEqual(saved['receipt']['receipt'], 'saved-review')

    def test_replanning_completed_custom_row_preserves_receipt_after_policy_changes(self):
        for saved_input in (False, True):
            for policy in (dict(workflow='changed-workflow'),
                           dict(required_fields=['author', 'addition', 'privacy']),
                           dict(search_before_proposing=['new review index'])):
                with self.subTest(saved_input=saved_input, policy=policy):
                    mod = self.module()
                    self.declare_class()
                    record = mod.capture(self.profile, 'replan-' + str(saved_input) + str(policy),
                        '2026-10-09', 'Public contract review',
                        [dict(id='contract', path='raw/research/contract.md',
                              primary=True, coverage='complete')])
                    row = self.row(kind='review', author='author', addition='addition',
                                   search={'existing reviews': 'searched'}, workflow='review-workflow')
                    mod.set_plan(record, ['D1'], [row], profile=self.profile)
                    calls = []
                    def workflow(req):
                        calls.append(req)
                        return dict(confirmed=True, receipt='saved-review', target=req['row']['target'])
                    mod.execute(self.profile, record, {'review-workflow': workflow})
                    before = mod.read_record(record)
                    completed = before['rows'][0]
                    self.declare_class(**policy)
                    submitted = completed if saved_input else row
                    mod.set_plan(record, ['D1'], [submitted], profile=self.profile)
                    replanned = mod.read_record(record)
                    self.assertEqual(replanned['rows'], [completed])
                    self.assertEqual(replanned['history'], before['history'])
                    mod.terminal(replanned)
                    mod.execute(self.profile, record, {'review-workflow': workflow,
                                                       'changed-workflow': workflow})
                    self.assertEqual(len(calls), 1, 'completed work must not execute twice')
                    self.assertEqual(mod.read_record(record)['rows'], [completed])

    def test_completed_custom_row_with_changed_work_still_requires_renewed_approval(self):
        mod = self.module(); record = self.capture()
        self.declare_class()
        row = self.row(kind='review', author='author', addition='addition',
                       search={'existing reviews': 'searched'}, workflow='review-workflow')
        mod.set_plan(record, ['D1'], [row], profile=self.profile)
        mod.execute(self.profile, record, {'review-workflow': lambda req:
            dict(confirmed=True, receipt='saved-review', target=req['row']['target'])})
        completed = mod.read_record(record)['rows'][0]
        self.declare_class(workflow='changed-workflow')
        changed = dict(row, addition='different addition', workflow='changed-workflow')
        mod.set_plan(record, ['D1'], [changed], profile=self.profile)
        state = mod.read_record(record)
        self.assertEqual(state['rows'][0]['state'], 'pending')
        self.assertEqual(state['rows'][0]['authorization'], 'pending')
        self.assertNotIn('receipt', state['rows'][0])
        self.assertEqual(state['history'], [completed])
        self.assertEqual(state['rows'][0]['class_policy'], mod.digest(mod.proposal_classes(self.profile)['review']))

    def test_destination_only_class_cli_and_uncertain_readback(self):
        mod = self.module(); record = self.capture()
        declaration = self.declare_class(destination='docs/review.md')
        declaration.pop('workflow')
        self.profile.write_text(self.profile.read_text().split('```hippocampus-classes')[0] +
            '```hippocampus-classes\n' + json.dumps([declaration]) + '\n```\n')
        row = self.row(kind='review', target='docs/review.md', author='author', addition='addition',
                       search={'existing reviews': 'searched'})
        plan = self.root / 'plan.json'; plan.write_text(json.dumps(dict(decisions=['D1'], rows=[row], class_results={'review': 'candidate'})))
        result = subprocess.run(['python3', str(HELPER), '--profile', str(self.profile), 'plan', str(record), '--input', str(plan)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = []
        def uncertain(req):
            calls.append(req)
            return dict(confirmed=True, receipt='wrong-target', target='docs/other.md')
        mod.execute(self.profile, record, {'review': uncertain})
        mod.execute(self.profile, record, {'review': uncertain})
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(mod.read_record(record)['rows'][0]['inflight'])
        mod.reconcile(record, 'A1', dict(confirmed=True, receipt='read-back', target='docs/review.md'))
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'complete')
        self.assertEqual(mod.read_record(record)['class_results'], {'review': 'candidate'})

    def test_invalid_class_declarations_rejected_and_public_example_parses(self):
        mod = self.module()
        for overrides in (dict(name='action'), dict(name='Bad name'), dict(required_fields=[]),
                          dict(search_before_proposing=[]), dict(workflow='')):
            self.declare_class(**overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                mod.proposal_classes(self.profile)
        self.profile.write_text(self.profile.read_text().split('```hippocampus-classes')[0] +
            (REPO / 'profiles/karpathy-wiki.example.md').read_text().split('## Example custom class:', 1)[1])
        self.assertEqual(set(mod.proposal_classes(self.profile)), {'writing'})

    def test_legacy_writing_record_remains_readable_without_declaration(self):
        # Existing contract-review fixture shape retained from the original route test.
        mod = self.module(); record = self.capture()
        state = mod.read_record(record)
        row = self.row(id='W0', kind='writing', opportunity='new',
            author='contract author', angle='Explain scoped compilation',
            addition='Add a source-linked note about the selected subset', privacy='public contract only',
            coverage={'ideas': 'searched', 'drafts': 'searched', 'published': 'unavailable'},
            search={'ideas': 'searched', 'drafts': 'searched', 'published': 'unavailable'},
            target='docs/writing-seeds.json', workflow='local writing workflow')
        row.update(scope=mod.row_scope(row))
        state.update(decisions=['D1'], rows=[row], writing_result='candidate retained')
        mod.save(record, state)
        prose = record.read_text().split('```hippocampus')[0]
        mod.set_plan(record, ['D1'], [row])
        self.assertEqual(mod.read_record(record)['rows'][0]['id'], 'W0')
        mod.execute(self.profile, record, {'writing': lambda req: self.fail('undeclared legacy execution')})
        self.assertEqual(mod.read_record(record)['rows'][0]['kind'], 'writing')
        self.assertEqual(record.read_text().split('```hippocampus')[0], prose)
        with self.assertRaises(ValueError):
            mod.set_plan(record, ['D1'], [dict(row, id='W-new')])

    def test_writing_routes_and_no_destination_preserve_authored_prose(self):
        mod = self.module(); record = self.capture()
        self.declare_class(name='writing', search_before_proposing=['ideas', 'drafts', 'published'],
            required_fields=['opportunity', 'author', 'angle', 'addition', 'privacy'], workflow='local writing workflow')
        authored = self.root / 'docs/draft.md'; authored.write_text('Authored draft unchanged.\n')
        rows = [self.row(id=f'W{i}', kind='writing', opportunity=kind,
            author='contract author', angle='Explain scoped compilation',
            addition='Add a source-linked note about the selected subset', privacy='public contract only',
            coverage={'ideas': 'searched', 'drafts': 'searched', 'published': 'unavailable'},
            search={'ideas': 'searched', 'drafts': 'searched', 'published': 'unavailable'},
            target='docs/writing-seeds.json', workflow='local writing workflow')
            for i, kind in enumerate(('new', 'enrich', 'published-followup'))]
        mod.set_plan(record, ['D1'], rows, profile=self.profile)
        seen = []
        def writing(req):
            seen.append(req['row']['opportunity'])
            destination = self.root / req['row']['target']
            seeds = json.loads(destination.read_text()) if destination.exists() else []
            if not any(seed['identity'] == req['idempotency_key'] for seed in seeds):
                seeds.append({'identity': req['idempotency_key'], 'kind': req['row']['opportunity'],
                              'addition': req['row']['addition'], 'author': req['row']['author']})
                destination.write_text(json.dumps(seeds))
            return dict(confirmed=True, receipt='writing:' + req['idempotency_key'], target=req['row']['target'])
        mod.execute(self.profile, record, {'local writing workflow': writing})
        mod.execute(self.profile, record, {'local writing workflow': writing})
        self.assertEqual(seen, ['new', 'enrich', 'published-followup'])
        self.assertEqual(len(json.loads((self.root / 'docs/writing-seeds.json').read_text())), 3)
        self.assertEqual(authored.read_text(), 'Authored draft unchanged.\n')
        rows[0]['id'] = 'W4'; rows[0]['target'] = ''; rows[0]['workflow'] = ''
        mod.set_plan(record, ['D1'], [rows[0]], profile=self.profile)
        mod.execute(self.profile, record, {'local writing workflow': writing})
        self.assertEqual(len(seen), 3)
        self.assertEqual(mod.read_record(record)['rows'][0]['state'], 'pending')
        rows[0]['authorization'] = 'declined'
        mod.set_plan(record, ['D1'], [rows[0]], profile=self.profile)
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
        self.attach_source(mod, meeting, transcript)
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

    def test_legacy_confirmed_research_results_are_adopted_without_reexecution(self):
        mod = self.module(); artifact = self.root / 'output/legacy.md'
        artifact.write_text('# Legacy research\n\n## How to Absorb\nD1: review public contract\n\n## Execution Appendix\nA1: task filed and read back\n')
        mod.initialize_research(artifact, [{'id': 'contract', 'path': 'raw/research/contract.md', 'primary': True, 'coverage': 'complete'}])
        self.assertIn('legacy_results', mod.set_plan.__code__.co_varnames, 'normalization must accept verified legacy receipts')
        result = dict(confirmed=True, receipt='existing task read-back', target='Test workflow')
        mod.set_plan(artifact, ['D1'], [self.row()], legacy_results={'A1': result})
        calls = []
        mod.execute(self.profile, artifact, {'action': lambda req: calls.append(req)})
        self.assertEqual(calls, [])
        self.assertEqual(mod.read_record(artifact)['rows'][0]['receipt']['receipt'], result['receipt'])
        self.assertIn('A1: task filed and read back', artifact.read_text())
        with self.assertRaises(ValueError):
            mod.set_plan(artifact, ['D1'], [self.row()], legacy_results={'unknown': result})

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
        self.attach_source(mod, record, transcript)
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
