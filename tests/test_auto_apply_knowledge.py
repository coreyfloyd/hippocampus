"""Knowledge capture at a wrap with the auto-apply setting on, driven through the checklist's command line."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path

import pytest

from test_auto_apply_lessons import SESSION, Wrap


@pytest.fixture(params=['claude', 'codex'])
def tool(request):
    return request.param


def knowledge(text='Pickup reads sibling worktrees before transcripts.', **changes):
    return {'type': 'knowledge', 'session_id': SESSION, 'produced_at': '2026-11-06T12:00:00Z',
            'disposition': 'route through knowledge-capture', 'context': text, **changes}


class KnowledgeWrap(Wrap):
    """A wrap with a temporary knowledge root and its knowledge profile."""

    def __init__(self, tmp_path, tool, wiki=True, **options):
        super().__init__(tmp_path, tool, **options)
        self.root = tmp_path / 'knowledge'
        for folder in ('raw/research', 'raw/derived', 'output', 'docs', 'wiki'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for name in ('docs/log.md', 'docs/DECISIONS.md', 'wiki/hot.md', 'wiki/index.md', 'context/rules.md'):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text('# Start\n')
            # Written before this wrap started.
            os.utime(self.root / name, (1_000_000_000, 1_000_000_000))
        fields = ['profile_version: 4', f'knowledge_root: {self.root}', 'operation_log_file: docs/log.md',
                  'decision_log_file: docs/DECISIONS.md', 'artifact_followup_destination: "Task list"']
        fields += (['hot_file: wiki/hot.md', 'wiki_followup_destination: "Wiki backlog"'] if wiki
                   else ['wiki_enabled: false'])
        self.knowledge_profile = tmp_path / 'knowledge-profile.md'
        self.knowledge_profile.write_text('---\n' + '\n'.join(fields) + '\n---\n')

    def write(self, relative, text='# Article\n'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def capture(self, items, rows, session_items=(), expect=0):
        result = self.run('apply-knowledge', '--knowledge-profile', self.knowledge_profile,
                          '--handoff', self.save('items.json', self.payload(items, session_items)),
                          '--knowledge', self.save('knowledge.json', rows))
        assert result.returncode == expect, result.stderr
        return json.loads(result.stdout) if expect == 0 else result


def test_wiki_capture_is_compiled_without_an_approval_and_listed(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    assert wrap.plan()['auto_apply']['knowledge'] == 'apply'
    wrap.write('wiki/pickup.md')
    wrap.write('raw/research/pickup-source.md')
    wrap.write('wiki/index.md', '# Index\n- pickup\n')
    # wiki-compile finishes by updating the session cache and appending to the operation log.
    wrap.write('wiki/hot.md', '# Hot\n- pickup\n')
    wrap.write('docs/log.md', '# Start\n- compiled pickup\n')
    item = knowledge(choices=['approve', 'decline'])
    data = wrap.capture([item], [{'index': 0, 'capture': 'wiki',
                                  'created': ['wiki/pickup.md', 'raw/research/pickup-source.md'],
                                  'updated': [str(wrap.root / 'wiki/index.md'), 'wiki/hot.md', 'docs/log.md']}])
    assert data['resume']['open_loops'] == [] and data['knowledge_asks'] == []
    filed = wrap.file(data)
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    [captured] = report['knowledge']['captured']
    assert captured['capture'] == 'wiki' and captured['context'] == item['context']
    assert captured['created'] == ['wiki/pickup.md', 'raw/research/pickup-source.md']
    assert captured['updated'] == ['wiki/index.md', 'wiki/hot.md', 'docs/log.md']
    assert report['asks'] == [] and report['report'] == 'ok'
    assert handoff['resume']['open_loops'] == []
    assert wrap.plan()['handoff']['resume']['open_loops'] == []


@pytest.mark.parametrize('capture,relative', [('source', 'raw/derived/synthesis.md'),
                                              ('output', 'output/report.md')])
def test_retained_sources_and_outputs_apply_the_same_way(tmp_path, tool, capture, relative):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    wrap.write(relative)
    found = knowledge('Found during the wrap.')
    data = wrap.capture([], [{'index': 0, 'capture': capture, 'created': [relative]}], session_items=[found])
    assert data['session_items'] == []
    report, check, handoff = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    assert report['knowledge']['captured'][0]['created'] == [relative]
    assert report['asks'] == [] and handoff['resume']['open_loops'] == []


def test_a_fact_about_the_user_is_an_ordinary_ask_that_never_resolves_on_its_own(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    item = knowledge('The user reviews work from a phone.')
    fact = {'index': 0, 'capture': 'user_fact', 'text': 'Reviews work from a phone.',
            'destination': 'context/preferences.md', 'source': 'Said in this session at 14:02.',
            'choices': ['save it', 'edit it', 'discard it'], 'approve': 'save it'}
    data = wrap.capture([item], [fact])
    [ask] = data['knowledge_asks']
    for text in ('Reviews work from a phone.', 'context/preferences.md', 'Said in this session at 14:02.'):
        assert text in ask['text']
    assert ask['choices'] == fact['choices'] and 'default' not in ask
    assert not (wrap.root / 'context/preferences.md').exists()
    [carried] = data['resume']['open_loops']
    filed = wrap.file(data, [{'index': 0, 'rule': 'R4', 'status': 'filed', 'destination': 'ask',
                              'choices': fact['choices']}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    assert [raised['text'] for raised in report['asks']] == [ask['text']]
    assert report['asks'][0]['choices'] == fact['choices']
    assert report['knowledge']['asked'][0]['destination'] == 'context/preferences.md'
    assert handoff['resume']['open_loops'] == [carried]
    assert wrap.plan()['handoff']['resume']['open_loops'] == [carried]
    refused = wrap.capture([item], [{**fact, 'default': 'save it'}], expect=1)
    assert 'has no default' in refused.stderr
    refused = wrap.capture([item], [{**fact, 'approve': 'maybe'}], expect=1)
    assert 'names which choice approves the save' in refused.stderr


def test_capture_outside_the_knowledge_root_keeps_its_approval(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    elsewhere = tmp_path / 'elsewhere/notes.md'
    elsewhere.parent.mkdir()
    elsewhere.write_text('notes\n')
    item = knowledge(choices=['approve', 'decline'])
    data = wrap.capture([item], [{'index': 0, 'capture': 'output', 'created': [str(elsewhere)]}])
    assert data['resume']['open_loops'] == [item]
    filed = wrap.file(data, [{'index': 0, 'rule': 'R4', 'status': 'filed', 'destination': 'ask',
                              'choices': item['choices']}])
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    [failed] = report['knowledge']['failed']
    assert 'outside the knowledge root' in failed['error'] and 'keeps its approval' in failed['error']
    assert [raised['choices'] for raised in report['asks']] == [['approve', 'decline']]
    assert handoff['resume']['open_loops'] == [item]


def test_a_capture_in_the_wrong_place_or_a_disabled_wiki_is_not_applied(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool, wiki=False)
    wrap.plan()
    wrap.write('wiki/pickup.md')
    item = knowledge()
    data = wrap.capture([item], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/pickup.md']}])
    assert data['resume']['open_loops'] == [item]
    assert 'wiki is disabled' in data['knowledge_outcomes'][0]['error']
    data = wrap.capture([item], [{'index': 0, 'capture': 'source', 'created': ['wiki/pickup.md']}])
    assert 'outside raw/' in data['knowledge_outcomes'][0]['error']
    # Only a compile writes the operation log; a retained source naming it is not one.
    wrap.write('docs/log.md', '# Start\n- retained\n')
    wrap.write('raw/research/a.md')
    data = wrap.capture([item], [{'index': 0, 'capture': 'source', 'created': ['raw/research/a.md'],
                                  'updated': ['docs/log.md']}])
    assert 'docs/log.md is outside raw/ in the knowledge root' in data['knowledge_outcomes'][0]['error']
    data = wrap.capture([item], [{'index': 0, 'capture': 'source', 'created': ['raw/missing.md']}])
    assert 'was not written' in data['knowledge_outcomes'][0]['error']


def test_every_file_of_a_capture_is_in_its_folders_and_written_this_wrap(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    wrap.write('wiki/a.md')
    wrap.write('context/rules.md', '# Changed\n')
    item = knowledge()
    data = wrap.capture([item], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/a.md'],
                                  'updated': ['context/rules.md']}])
    assert data['resume']['open_loops'] == [item]
    error = data['knowledge_outcomes'][0]['error']
    assert 'context/rules.md is outside wiki/, raw/' in error and 'keeps its approval' in error
    assert "the profile's wiki/hot.md, docs/log.md" in error
    data = wrap.capture([item], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/a.md'],
                                  'updated': ['wiki/index.md']}])
    assert data['resume']['open_loops'] == [item]
    assert 'wiki/index.md was not written during this wrap' in data['knowledge_outcomes'][0]['error']


def test_apply_knowledge_needs_the_wrap_to_have_started(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.write('wiki/a.md')
    refused = wrap.capture([knowledge()], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/a.md']}], expect=1)
    assert "run the checklist's plan first" in refused.stderr


def test_the_routing_file_governs_lessons_only(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool, routing='lesson-policy: propose\n')
    assert wrap.plan()['auto_apply']['knowledge'] == 'apply'
    wrap.write('output/report.md')
    data = wrap.capture([knowledge()], [{'index': 0, 'capture': 'output', 'created': ['output/report.md']}])
    assert data['resume']['open_loops'] == []


def test_setting_off_changes_nothing(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool, setting=False)
    assert 'auto_apply' not in wrap.plan()
    wrap.write('wiki/pickup.md')
    item = knowledge(choices=['approve', 'decline'])
    refused = wrap.capture([item], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/pickup.md']}], expect=1)
    assert 'setting is off' in refused.stderr
    filed = wrap.file(wrap.payload([item]), [{'index': 0, 'rule': 'R4', 'status': 'pending',
                                              'reason': 'Awaiting approval'}])
    assert 'knowledge' not in filed['filing']
    report, _, handoff = wrap.finish(filed)
    assert 'knowledge' not in report
    assert handoff['resume']['open_loops'] == [item]
    assert [ask['text'] for ask in report['asks']] == [item['context']]


def test_a_row_naming_the_knowledge_root_fails_alone(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    wrap.write('output/report.md')
    bad, good = knowledge('Named the root.'), knowledge('Named a file.')
    data = wrap.capture([bad, good], [{'index': 0, 'capture': 'wiki', 'created': ['.']},
                                      {'index': 1, 'capture': 'output', 'created': [str(wrap.root / 'output/report.md')]}])
    failed, captured = data['knowledge_outcomes']
    assert failed['status'] == 'failed' and 'names the knowledge root itself' in failed['error']
    assert captured['status'] == 'captured' and captured['created'] == ['output/report.md']
    assert data['resume']['open_loops'] == [bad]
    data = wrap.capture([bad], [{'index': 0, 'capture': 'wiki', 'created': [str(wrap.root)]}])
    assert 'names the knowledge root itself' in data['knowledge_outcomes'][0]['error']


def fact_row(index=0):
    return {'index': index, 'capture': 'user_fact', 'text': 'Reviews work from a phone.',
            'destination': 'context/preferences.md', 'source': 'Said in this session at 14:02.',
            'choices': ['save it', 'edit it', 'discard it'], 'approve': 'save it'}


@pytest.mark.parametrize('rule,row', [
    ('R1', {'rule': 'R1', 'status': 'dropped', 'reason': 'Already known', 'information_only': True}),
    ('R6', {'rule': 'R6', 'status': 'dropped', 'reason': 'Not worth keeping'}),
    ('R4', {'rule': 'R4', 'status': 'filed', 'destination': 'context/preferences.md'})])
def test_a_filing_row_cannot_settle_a_fact_about_the_user_without_the_users_answer(tmp_path, tool, rule, row):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    item = knowledge('The user reviews work from a phone.')
    data = wrap.capture([item], [fact_row()])
    [carried] = data['resume']['open_loops']
    other = {'type': 'progress', 'session_id': SESSION, 'produced_at': '2026-11-06T12:00:00Z',
             'disposition': 'drop', 'context': 'Done already.'}
    data['resume']['open_loops'].append(other)
    filed = wrap.file(data, [{'index': 0, **row},
                             {'index': 1, 'rule': 'R1', 'status': 'dropped', 'reason': 'Information only',
                              'information_only': True}])
    first, second = filed['filing']['items']
    assert first['status'] == 'failed' and 'leaves only through its ask' in first['error']
    assert second['status'] == 'dropped'
    assert filed['resume']['open_loops'] == [carried]
    # A mis-filed fact fails the wrap, with the ask still raised in full.
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 1 and 'leaves only through its ask' in check.stderr
    assert [raised['choices'] for raised in report['asks']] == [carried['choices']]
    assert handoff['resume']['open_loops'] == [carried]
    # With the user's answer recorded, the same row settles the fact.
    answered = wrap.file(data, [{'index': 0, **row, 'answer': 'discard it' if rule != 'R4' else 'save it'},
                                {'index': 1, 'rule': 'R1', 'status': 'dropped', 'reason': 'Information only',
                                 'information_only': True}])
    assert answered['filing']['items'][0]['status'] == row['status']
    assert answered['resume']['open_loops'] == []
    report, check, handoff = wrap.finish(answered)
    assert check.returncode == 0, check.stderr
    assert report['asks'] == [] and handoff['resume']['open_loops'] == []


def test_a_capture_row_cannot_settle_a_fact_about_the_user_without_the_users_answer(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    item = knowledge('The user reviews work from a phone.')
    [carried] = wrap.capture([item], [fact_row()])['resume']['open_loops']
    wrap.write('wiki/phone.md')
    wrap.write('raw/research/phone.md')
    data = wrap.capture([carried], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/phone.md', 'raw/research/phone.md']}])
    assert data['resume']['open_loops'] == [carried]
    assert 'leaves only through its ask' in data['knowledge_outcomes'][0]['error']
    data = wrap.capture([carried], [{'index': 0, 'capture': 'wiki', 'answer': 'yes',
                                     'created': ['wiki/phone.md', 'raw/research/phone.md']}])
    assert data['resume']['open_loops'] == [carried]
    data = wrap.capture([carried], [{'index': 0, 'capture': 'wiki', 'answer': 'save it',
                                     'created': ['wiki/phone.md', 'raw/research/phone.md']}])
    assert data['resume']['open_loops'] == []
    assert data['knowledge_outcomes'][0]['status'] == 'captured' and data['knowledge_outcomes'][0]['answer'] == 'save it'
    report, check, _ = wrap.finish(wrap.file(data))
    assert check.returncode == 0, check.stderr
    assert report['knowledge']['captured'][0]['answer'] == 'save it' and report['asks'] == []


def load_knowledge_module():
    spec = importlib.util.spec_from_file_location('knowledge', Path(__file__).resolve().parents[1] / 'scripts/lib/knowledge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('rule,row,answer,reason', [
    ('R4', {'rule': 'R4', 'status': 'filed', 'destination': 'context/preferences.md'}, 'discard it',
     'saved only on its approving choice'),
    ('R4', {'rule': 'R4', 'status': 'filed', 'destination': 'context/preferences.md'}, 'edit it',
     'saved only on its approving choice'),
    ('R6', {'rule': 'R6', 'status': 'dropped', 'reason': 'The user declined'}, 'save it',
     'approving the save; the fact is not dropped')])
def test_only_the_approving_answer_saves_a_fact_and_only_another_drops_it(tmp_path, tool, rule, row, answer, reason):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    data = wrap.capture([knowledge('The user reviews work from a phone.')], [fact_row()])
    [carried] = data['resume']['open_loops']
    assert carried['approve'] == 'save it' and data['knowledge_asks'][0]['approve'] == 'save it'
    filed = wrap.file(data, [{'index': 0, **row, 'answer': answer}])
    [entry] = filed['filing']['items']
    assert entry['status'] == 'failed' and reason in entry['error']
    assert filed['resume']['open_loops'] == [carried]


def test_a_declined_fact_is_dropped_with_nothing_written(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    data = wrap.capture([knowledge('The user reviews work from a phone.')], [fact_row()])
    [carried] = data['resume']['open_loops']
    dropped = wrap.file(data, [{'index': 0, 'rule': 'R6', 'status': 'dropped', 'reason': 'The user declined',
                                'answer': 'discard it'}])
    assert dropped['filing']['items'][0]['status'] == 'dropped' and dropped['resume']['open_loops'] == []
    assert not (wrap.root / 'context/preferences.md').exists()
    # A capture row with a declining answer writes nothing either, whatever the agent compiled.
    wrap.write('wiki/phone.md')
    data = wrap.capture([carried], [{'index': 0, 'capture': 'wiki', 'answer': 'discard it', 'created': ['wiki/phone.md']}])
    assert data['resume']['open_loops'] == [carried]
    assert 'saved only on its approving choice' in data['knowledge_outcomes'][0]['error']


def test_a_misplaced_compile_file_fails_only_the_rows_that_need_it(tmp_path):
    knowledge_module = load_knowledge_module()
    root = tmp_path / 'knowledge'
    for name in ('wiki/a.md', 'raw/research/a.md', 'context/rules.md'):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('# A\n')
    since = datetime.fromtimestamp(0, timezone.utc)
    profile_files = {'hot_file': "the profile's hot_file (../hot.md) is outside the knowledge root",
                     'operation_log_file': Path('docs/log.md')}
    captured = knowledge_module._captured({'capture': 'wiki', 'created': ['wiki/a.md', 'raw/research/a.md']},
                                          root, True, profile_files, since)
    assert captured == {'created': ['wiki/a.md', 'raw/research/a.md'], 'updated': []}
    with pytest.raises(ValueError) as failed:
        knowledge_module._captured({'capture': 'wiki', 'created': ['wiki/a.md'], 'updated': ['context/rules.md']},
                                   root, True, profile_files, since)
    assert "context/rules.md is outside wiki/, raw/ and the profile's docs/log.md" in str(failed.value)
    assert "the profile's hot_file (../hot.md) is outside the knowledge root" in str(failed.value)


def test_running_plan_again_keeps_files_already_compiled_this_wrap(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    wrap.write('wiki/pickup.md')
    os.utime(wrap.root / 'wiki/pickup.md', None)
    import time
    time.sleep(1.1)
    wrap.plan()
    data = wrap.capture([knowledge()], [{'index': 0, 'capture': 'wiki', 'created': ['wiki/pickup.md']}])
    assert data['knowledge_outcomes'][0]['status'] == 'captured', data['knowledge_outcomes'][0]
    assert data['resume']['open_loops'] == []


def test_a_capture_value_that_is_not_text_is_a_clear_error(tmp_path, tool):
    wrap = KnowledgeWrap(tmp_path, tool)
    wrap.plan()
    for capture in (['wiki'], {}, 7):
        refused = wrap.capture([knowledge()], [{'index': 0, 'capture': capture, 'created': ['wiki/a.md']}], expect=1)
        assert 'capture must be one of' in refused.stderr and 'Traceback' not in refused.stderr, refused.stderr
