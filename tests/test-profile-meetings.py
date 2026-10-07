#!/usr/bin/env python3
"""Exercise optional meeting inputs through the real profile CLI."""
import pathlib
import subprocess
import tempfile
import unittest

VALIDATOR = pathlib.Path(__file__).resolve().parents[1] / 'scripts/validate_profile.py'

class MeetingProfiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name) / 'knowledge'
        for name in ('raw', 'output', 'docs'):
            (self.root / name).mkdir(parents=True)
        for name in ('log.md', 'DECISIONS.md'):
            (self.root / 'docs' / name).touch()

    def validate(self, fields=''):
        profile = self.root.parent / 'profile.md'
        profile.write_text(f'---\nprofile_version: 4\nknowledge_root: {self.root}\nwiki_enabled: false\noperation_log_file: docs/log.md\ndecision_log_file: docs/DECISIONS.md\nartifact_followup_destination: Tasks\n{fields}---\n')
        return subprocess.run(['python3', str(VALIDATOR), str(profile)], capture_output=True, text=True)

    def test_existing_profile_remains_valid(self):
        self.assertEqual(self.validate().returncode, 0)

    def test_enabled_sources_and_missing_note_file_are_valid(self):
        result = self.validate('meeting_transcript_source: Wispr Flow\nmeeting_event_source: Google Calendar\nmeeting_note_path: daily/{date}.md\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sources_can_be_disabled_independently(self):
        for key in ('meeting_transcript_source', 'meeting_event_source', 'meeting_note_path'):
            with self.subTest(key=key):
                result = self.validate(f'{key}: disabled\n')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_blank_sources_are_rejected(self):
        for key in ('meeting_transcript_source', 'meeting_event_source', 'meeting_note_path'):
            with self.subTest(key=key):
                self.assertNotEqual(self.validate(f'{key}:\n').returncode, 0)

    def test_unsafe_or_ambiguous_note_paths_are_rejected(self):
        for value in ('../daily/{date}.md', 'daily/{person}/{date}.md', 'daily/{date}-{date}.md'):
            with self.subTest(value=value):
                self.assertNotEqual(self.validate(f'meeting_note_path: {value}\n').returncode, 0)

    def test_fixed_local_paths_and_google_docs_links_are_valid(self):
        for value in ('notes/project-review.md', str(self.root.parent / 'separate-notes' / '{date}.md'), 'https://docs.google.com/document/d/meeting-notes/edit?usp=sharing', 'https://docs.google.com/document/u/0/d/meeting-notes/edit'):
            with self.subTest(value=value):
                result = self.validate(f'meeting_note_path: {value}\n')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_or_deceptive_urls_are_rejected(self):
        for value in ('http://docs.google.com/document/d/meeting/edit', 'https://docs.google.com.evil.example/document/d/id/edit', 'https://docs.google.com/spreadsheets/d/id/edit', 'https://other.example/notes', 'https://user@docs.google.com/document/d/id/edit', 'https://docs.google.com:8443/document/d/id/edit'):
            with self.subTest(value=value):
                self.assertNotEqual(self.validate(f'meeting_note_path: {value}\n').returncode, 0)

    def test_old_daily_specific_field_names_replacement(self):
        result = self.validate('meeting_daily_note_path: daily/{date}.md\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('meeting_note_path', result.stderr)

    def test_relative_note_symlink_escape_is_rejected(self):
        (self.root / 'daily').symlink_to(self.root.parent, target_is_directory=True)
        result = self.validate('meeting_note_path: daily/{date}.md\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('escapes knowledge_root', result.stderr)

if __name__ == '__main__':
    unittest.main()
