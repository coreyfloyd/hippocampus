#!/usr/bin/env python3
"""Public diagrams keep user-facing scope separate from architecture detail."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import importlib.util
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = '{http://www.w3.org/2000/svg}'

class PublicDocs(unittest.TestCase):
    def test_research_diagram_is_simple_and_contains_no_shared_internals(self):
        svg = ET.parse(ROOT / 'docs/images/question-answer-action.svg').getroot()
        visible = ' '.join(' '.join(node.itertext()) for node in svg.iter(NS + 'text'))
        for stage in ('QUESTION', 'ANSWER', 'ACTION', 'Ask', 'Bring', 'RESEARCH REPORT'):
            self.assertIn(stage, visible)
        for internal in ('row authority', 'retention transitions', 'Legend:', 'Framed question', 'raw/derived'):
            self.assertNotIn(internal.casefold(), visible.casefold())
        self.assertEqual(svg.get('viewBox'), '0 0 1200 520')
        self.assertIn('font-size: 23px; font-weight: 750;', svg.find(NS + 'style').text)
        # one orange record only: Ask and Bring together are the question
        records = [node for node in svg.iter(NS + 'rect') if node.get('data-thing') == 'record']
        self.assertEqual(len(records), 1)

    def test_meeting_diagram_has_independent_inputs_and_bounded_user_outcomes(self):
        path = ROOT / 'docs/images/capture-meetings.svg'
        self.assertTrue(path.is_file(), 'meeting section requires its own diagram')
        svg = ET.parse(path).getroot()
        nodes = [node for node in svg.iter() if node.get('data-meeting-node')]
        self.assertLessEqual(len(nodes), 10)
        self.assertEqual({node.get('data-meeting-node') for node in nodes},
                         {'event', 'note', 'transcript', 'record', 'action'})
        visible = ' '.join(' '.join(node.itertext()) for node in svg.iter(NS + 'text'))
        for outcome in ('People', 'Documents', 'Wiki', 'Follow-up work', 'routes complete'):
            self.assertIn(outcome, visible)
        for internal in ('row authority', 'Legend:', 'Writing opportunities', 'Optional wiki'):
            self.assertNotIn(internal.casefold(), visible.casefold())
        research = ET.parse(ROOT / 'docs/images/question-answer-action.svg').getroot()
        self.assertEqual(svg.find(NS + 'style').text, research.find(NS + 'style').text)
        readme = (ROOT / 'README.md').read_text()
        meeting_section = readme.split('## Meetings', 1)[1].split('## ', 1)[0]
        self.assertIn('(docs/images/capture-meetings.svg)', meeting_section)

    def test_destination_boxes_match_and_retain_references_instead_of_discarding_reports(self):
        research = ET.parse(ROOT / 'docs/images/question-answer-action.svg').getroot()
        meeting = ET.parse(ROOT / 'docs/images/capture-meetings.svg').getroot()
        expected = ['People', 'Documents', 'Follow-up work', 'Wiki', 'Retained reference record']

        def destinations(svg):
            boxes = [node for node in svg.iter(NS + 'rect') if node.get('data-thing') == 'destination']
            labels = [node for node in svg.iter(NS + 'text') if node.get('data-outcome-label')]
            return boxes, labels

        research_boxes, research_labels = destinations(research)
        meeting_boxes, meeting_labels = destinations(meeting)
        self.assertEqual([node.text for node in research_labels], expected)
        self.assertEqual([node.text for node in meeting_labels], expected + ['Original transcript filed'])
        for box in research_boxes + meeting_boxes:
            self.assertEqual(box.get('class'), 'outcome')
        # shared destination boxes sit at identical positions with identical wording in both diagrams
        def panel_copy(svg, boxes):
            left = min(float(box.get('x')) for box in boxes)
            return [(node.get('x'), node.get('y'), node.get('class'), ' '.join(node.itertext()))
                    for node in svg.iter(NS + 'text')
                    if float(node.get('x')) > left and node.get('data-column') is None]
        research_copy = panel_copy(research, research_boxes)
        meeting_copy = panel_copy(meeting, meeting_boxes)
        self.assertEqual(meeting_copy[:len(research_copy)], research_copy,
                         'all shared destination wording and positions must match, including sublabels')
        for a, b in zip(research_boxes, meeting_boxes):
            for attribute in ('x', 'y', 'width', 'height', 'rx'):
                self.assertEqual(a.get(attribute), b.get(attribute))
        for svg in (research, meeting):
            self.assertNotIn('discard & close', ' '.join(svg.itertext()).casefold())
            self.assertIn('Individual proposals may be declined.', ' '.join(svg.itertext()))

    def test_meeting_input_order_and_skill_names_match_the_installed_vocabulary(self):
        research = ET.parse(ROOT / 'docs/images/question-answer-action.svg').getroot()
        meeting = ET.parse(ROOT / 'docs/images/capture-meetings.svg').getroot()
        inputs = sorted([node for node in meeting.iter(NS + 'rect')
                         if node.get('data-meeting-node') in {'event', 'note', 'transcript'}],
                        key=lambda node: float(node.get('y')))
        self.assertEqual([node.get('data-meeting-node') for node in inputs], ['event', 'note', 'transcript'])
        input_copy = [node.text or '' for node in meeting.iter(NS + 'text') if node.get('data-meeting-input')]
        self.assertFalse(any('optional' in copy.casefold() for copy in input_copy))
        for svg, expected in [(research, {'research-topic', 'research-sources', 'absorb', 'wiki-compile'}),
                              (meeting, {'meeting-capture', 'absorb', 'wiki-compile'})]:
            labels = [node for node in svg.iter(NS + 'text') if node.get('data-skill')]
            self.assertEqual({node.get('data-skill') for node in labels}, expected)
            for node in labels:
                self.assertEqual(node.get('class'), 'skill')
                self.assertEqual(node.text, node.get('data-skill'))
                self.assertTrue((ROOT / 'skills' / node.text / 'SKILL.md').is_file())
            self.assertRegex(svg.find(NS + 'style').text, r'\.skill\s*\{[^}]*font-family:\s*var\(--mono\)')

    def test_diagram_grammar_places_skills_on_arrows_and_colors_things(self):
        operations = {
            'question-answer-action': {'ask-report': ['research-topic'],
                                      'bring-report': ['research-sources'],
                                      'report-action': ['absorb']},
            'capture-meetings': {'inputs-record': ['meeting-capture'], 'record-action': ['absorb']},
        }
        columns = {'question-answer-action': ['QUESTION', 'ANSWER', 'ACTION'],
                   'capture-meetings': ['MEETING', 'RECORD', 'ACTION']}
        key = 'blue: what you bring · orange: what Hippocampus writes · green: where outcomes land'
        for name, expected in operations.items():
            svg = ET.parse(ROOT / ('docs/images/' + name + '.svg')).getroot()
            subtitle = next(node for node in svg.iter(NS + 'text') if node.get('data-diagram-key'))
            self.assertEqual(subtitle.text, key)
            self.assertEqual([node.text for node in svg.iter(NS + 'text') if node.get('data-column')], columns[name])
            arrows = {node.get('data-operation'): node for node in svg.iter(NS + 'g')
                      if node.get('data-operation')}
            self.assertEqual(set(arrows), set(expected))
            arrow_labels = []
            for operation, skills in expected.items():
                labels = [node for node in arrows[operation].iter(NS + 'text') if node.get('data-skill')]
                self.assertEqual([node.get('data-skill') for node in labels], skills)
                self.assertTrue(list(arrows[operation].iter(NS + 'path')))
                arrow_labels.extend(labels)
            all_labels = [node for node in svg.iter(NS + 'text') if node.get('data-skill')]
            self.assertEqual(len(all_labels), len(arrow_labels) + 1)
            self.assertEqual([node.get('data-skill') for node in all_labels if node not in arrow_labels], ['wiki-compile'])
            boxes = [node for node in svg.iter(NS + 'rect') if node.get('data-thing')]
            kinds = [box.get('data-thing') for box in boxes]
            self.assertEqual(kinds.count('record'), 1)
            self.assertEqual(kinds.count('input'), 2 if name == 'question-answer-action' else 3)
            self.assertEqual(kinds.count('destination'), 5 if name == 'question-answer-action' else 6)
            inputs = [box for box in boxes if box.get('data-thing') == 'input']
            self.assertEqual({box.get('width') for box in inputs}, {inputs[0].get('width')}, 'one blue box style')
            for box in boxes:
                kind = box.get('data-thing')
                if kind == 'input':
                    self.assertEqual(box.get('class'), 'input')
                elif kind == 'destination':
                    self.assertEqual(box.get('class'), 'outcome')
                else:
                    self.assertEqual(box.get('stroke'), 'var(--answer)')
                for label in arrow_labels:
                    x, y = float(label.get('x')), float(label.get('y'))
                    left, top = float(box.get('x')), float(box.get('y'))
                    self.assertFalse(left <= x <= left + float(box.get('width')) and
                                     top <= y <= top + float(box.get('height')), 'skill label inside a thing box')
            visible = ' '.join(svg.itertext())
            if name == 'question-answer-action':
                self.assertIn('Research report'.upper(), visible)
                self.assertNotIn('Framed question', visible)
                self.assertNotIn('Set the target', visible)
                self.assertNotIn('Ground the result', visible)

    def test_review_records_the_approved_diagram_conventions(self):
        inventory = (ROOT / 'docs/reviews/2026-10-09-public-documentation.md').read_text()
        self.assertIn('## Diagram conventions', inventory)
        for rule in ('Boxes are things', 'Skills label arrows', 'blue', 'orange', 'green', 'wiki-compile', 'Column headers', 'destination boxes'):
            self.assertIn(rule, inventory)

    def test_readme_leads_with_research_and_meetings_before_detailed_tables(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertLess(readme.index('## Research\n'), readme.index('## Meetings\n'))
        self.assertLess(readme.index('## Meetings\n'), readme.index('## Research skills\n'))
        self.assertEqual(readme.count('(docs/images/question-answer-action.svg)'), 1)
        self.assertEqual(readme.count('(docs/images/capture-meetings.svg)'), 1)
        introduction = readme.split('## Research\n', 1)[0]
        self.assertIn('meetings', introduction)
        self.assertIn('approved', introduction)
        research = readme.split('## Research\n', 1)[1].split('## Meetings\n', 1)[0]
        for skill in ('research-topic', 'research-sources', 'absorb', 'wiki-compile'):
            self.assertIn(skill, research)
        self.assertNotIn('raw/derived/', research)
        self.assertIn('reference record', research)
        self.assertNotIn('discard it and close', research)

    def test_adjusted_deck_and_architecture_share_the_corrected_public_assets(self):
        deck = (ROOT / 'docs/presentation.html').read_text()
        for number in (4, 5, 9):
            slide = re.search(r'<div class="slide" id="slide-' + str(number) + r'">(.*?)(?=<!-- Slide|</div>\s*</div>\s*<!-- Minimal)', deck, re.S)
            self.assertIsNotNone(slide)
            self.assertRegex(slide[1], r'images/(?:question-answer-action|capture-meetings)\.svg')
        viewer = (ROOT / 'docs/architecture/runtime.html').read_text()
        self.assertIn('../images/question-answer-action.svg', viewer)
        self.assertIn('../images/capture-meetings.svg', viewer)

    def test_deck_uses_original_palette_and_section_specific_assets(self):
        deck = (ROOT / 'docs/presentation.html').read_text()
        style = re.search(r'<style>(.*?)</style>', deck, re.S)[1]
        for token, value in {'bg': '#1c2024', 'cyan': '#38bdf8', 'tangerine': '#fb923c',
                             'emerald': '#34d399', 'crimson': '#f87171'}.items():
            self.assertRegex(style, r'--' + token + r':\s*' + value + r';')
        self.assertIn('images/question-answer-action.svg', deck)
        self.assertIn('images/capture-meetings.svg', deck)
        for internal in ('data-workflow-diagram', 'Row authority', 'executor scope', 'wiki-compile', 'file-source'):
            self.assertNotIn(internal, deck)

    def test_primary_evidence_reaches_local_destinations_with_contract_citation(self):
        model = json.loads((ROOT / 'docs/architecture/runtime.architecture.json').read_text())
        reached = {'primary'}
        while True:
            more = reached | {edge['to'] for edge in model['connections'] if edge['from'] in reached}
            if more == reached:
                break
            reached = more
        self.assertIn('targets', reached, 'approved document/action/writing rows carry source evidence')
        node = next(node for node in model['components'] if node['id'] == 'primary')
        self.assertTrue(any(ref['path'] == 'skills/absorb/references/distribution-contract.md'
                            for ref in node['sources']))

    @unittest.skipUnless(importlib.util.find_spec('markdown'), 'render-public-review.py needs the markdown module (uv run --with markdown)')
    def test_comparison_render_preserves_public_assets_and_before_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / 'docs', root / 'docs')
            (root / 'scripts').mkdir()
            shutil.copy(ROOT / 'scripts/render-public-review.py', root / 'scripts/render-public-review.py')
            shutil.copy(ROOT / 'README.md', root / 'README.md')
            protected = list((root / 'docs/reviews/2026-10-09-public-before').rglob('*'))
            protected += [root / 'docs/images/question-answer-action.svg',
                          root / 'docs/images/capture-meetings.svg', root / 'docs/presentation.html']
            before = {path: path.read_bytes() for path in protected if path.is_file()}
            result = subprocess.run([sys.executable, str(root / 'scripts/render-public-review.py')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content, str(path.relative_to(root)))
            page = (root / 'docs/reviews/2026-10-09-public-documentation.html').read_text()
            self.assertIn('docs/images/capture-meetings.svg', page)
            self.assertNotIn('data-workflow-diagram', page)
            viewer = root / 'docs/architecture/runtime.html'
            first_render = viewer.read_bytes()
            repeated = subprocess.run([sys.executable, str(root / 'scripts/render-public-review.py')],
                                      capture_output=True, text=True)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(viewer.read_bytes(), first_render, 'architecture overview must not accumulate whitespace on rerender')

if __name__ == '__main__':
    unittest.main()
