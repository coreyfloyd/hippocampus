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
        for stage in ('QUESTION', 'ANSWER', 'ACTION'):
            self.assertIn(stage, visible)
        for internal in ('row authority', 'retention transitions', 'Legend:'):
            self.assertNotIn(internal.casefold(), visible.casefold())
        self.assertEqual(svg.get('viewBox'), '0 0 1200 520')
        self.assertIn('font-size: 23px; font-weight: 750;', svg.find(NS + 'style').text)

    def test_meeting_diagram_has_independent_inputs_and_bounded_user_outcomes(self):
        path = ROOT / 'docs/images/capture-meetings.svg'
        self.assertTrue(path.is_file(), 'meeting section requires its own diagram')
        svg = ET.parse(path).getroot()
        nodes = [node for node in svg.iter() if node.get('data-meeting-node')]
        self.assertLessEqual(len(nodes), 8)
        self.assertEqual({node.get('data-meeting-node') for node in nodes},
                         {'event', 'note', 'transcript', 'record', 'action'})
        visible = ' '.join(' '.join(node.itertext()) for node in svg.iter(NS + 'text'))
        for outcome in ('People', 'documents', 'wiki', 'Follow-up work', 'Writing opportunities', 'routes complete'):
            self.assertIn(outcome, visible)
        for internal in ('row authority', 'Legend:'):
            self.assertNotIn(internal.casefold(), visible.casefold())
        research = ET.parse(ROOT / 'docs/images/question-answer-action.svg').getroot()
        self.assertEqual(svg.find(NS + 'style').text, research.find(NS + 'style').text)
        readme = (ROOT / 'README.md').read_text()
        meeting_section = readme.split('## Meetings', 1)[1].split('## ', 1)[0]
        self.assertIn('(docs/images/capture-meetings.svg)', meeting_section)

    def test_symmetric_outcomes_retain_references_instead_of_discarding_reports(self):
        research = ET.parse(ROOT / 'docs/images/question-answer-action.svg').getroot()
        meeting = ET.parse(ROOT / 'docs/images/capture-meetings.svg').getroot()
        panels = [next((node for node in svg.iter() if node.get('data-outcome-panel')), None)
                  for svg in (research, meeting)]
        self.assertTrue(all(panel is not None for panel in panels), 'both diagrams need matching action panels')
        for attribute in ('x', 'y', 'width', 'height', 'fill', 'stroke', 'rx'):
            self.assertEqual(panels[0].get(attribute), panels[1].get(attribute))
        labels = [[' '.join(' '.join(node.itertext()).split()) for node in svg.iter(NS + 'text') if node.get('data-outcome-label')]
                  for svg in (research, meeting)]
        expected = ['People & documents', 'Follow-up work', 'Writing opportunities',
                    'Optional wiki', 'Retained reference record']
        shared_panel_copy = []
        for svg, panel in zip((research, meeting), panels):
            shared_panel_copy.append([
                (node.get('x'), node.get('y'), node.get('class'), ' '.join(node.itertext()))
                for node in svg.iter(NS + 'text')
                if float(node.get('x')) > float(panel.get('x'))
                and node.get('data-outcome-label') != 'transcript'
            ])
        self.assertEqual(shared_panel_copy[0], shared_panel_copy[1],
                         'all shared ACTION wording and positions must match, including sublabels')
        self.assertEqual(labels[0], expected)
        self.assertEqual(labels[1], expected + ['Original transcript filed, after approved routes complete'])
        for svg in (research, meeting):
            self.assertNotIn('discard & close', ' '.join(svg.itertext()).casefold())
        self.assertIn('raw/derived/', ' '.join(research.itertext()))
        # The final transcript destination is inside the shared right-hand panel.
        transcript = next(node for node in meeting.iter(NS + 'text')
                          if node.get('data-outcome-label') == 'transcript')
        self.assertGreater(float(transcript.get('x')), float(panels[1].get('x')))
        self.assertLess(float(transcript.get('y')), float(panels[1].get('y')) + float(panels[1].get('height')))

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
            'question-answer-action': {'ask-question': ['research-topic'],
                                      'bring-question': ['research-sources'],
                                      'question-answer': [], 'answer-action': ['absorb']},
            'capture-meetings': {'inputs-record': ['meeting-capture'], 'record-action': ['absorb']},
        }
        key = 'blue: what you bring · orange: what Hippocampus writes · green: where outcomes land'
        for name, expected in operations.items():
            svg = ET.parse(ROOT / ('docs/images/' + name + '.svg')).getroot()
            subtitle = next(node for node in svg.iter(NS + 'text') if node.get('data-diagram-key'))
            self.assertEqual(subtitle.text, key)
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
            self.assertEqual(len(boxes), 5)
            for box in boxes:
                kind = box.get('data-thing')
                if kind == 'input':
                    self.assertEqual(box.get('class'), 'input')
                else:
                    self.assertEqual(box.get('stroke'), 'var(--answer)' if kind == 'record' else 'var(--action)')
                for label in arrow_labels:
                    x, y = float(label.get('x')), float(label.get('y'))
                    left, top = float(box.get('x')), float(box.get('y'))
                    self.assertFalse(left <= x <= left + float(box.get('width')) and
                                     top <= y <= top + float(box.get('height')), 'skill label inside a thing box')
            visible = ' '.join(svg.itertext())
            if name == 'question-answer-action':
                self.assertIn('Framed question', visible)
                self.assertIn('Research report', visible)
                self.assertNotIn('Set the target', visible)
                self.assertNotIn('Ground the result', visible)

    def test_review_records_the_approved_diagram_conventions(self):
        inventory = (ROOT / 'docs/reviews/2026-10-09-public-documentation.md').read_text()
        self.assertIn('## Diagram conventions', inventory)
        for rule in ('Boxes are things', 'Skills label arrows', 'blue', 'orange', 'green', 'wiki-compile'):
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
        self.assertIn('raw/derived/', research)
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
