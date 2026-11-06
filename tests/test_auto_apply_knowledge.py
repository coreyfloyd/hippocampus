"""Knowledge capture at a wrap with the auto-apply setting on, driven through the checklist's command line."""
import json

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
        for name in ('docs/log.md', 'docs/DECISIONS.md', 'wiki/hot.md', 'wiki/index.md'):
            (self.root / name).write_text('# Start\n')
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
    item = knowledge(choices=['approve', 'decline'])
    data = wrap.capture([item], [{'index': 0, 'capture': 'wiki',
                                  'created': ['wiki/pickup.md', 'raw/research/pickup-source.md'],
                                  'updated': [str(wrap.root / 'wiki/index.md')]}])
    assert data['resume']['open_loops'] == [] and data['knowledge_asks'] == []
    filed = wrap.file(data)
    report, check, handoff = wrap.finish(filed)
    assert check.returncode == 0, check.stderr
    [captured] = report['knowledge']['captured']
    assert captured['capture'] == 'wiki' and captured['context'] == item['context']
    assert captured['created'] == ['wiki/pickup.md', 'raw/research/pickup-source.md']
    assert captured['updated'] == ['wiki/index.md']
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
            'choices': ['save it', 'edit it', 'discard it']}
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
    assert 'writes under raw/' in data['knowledge_outcomes'][0]['error']
    data = wrap.capture([item], [{'index': 0, 'capture': 'source', 'created': ['raw/missing.md']}])
    assert 'was not written' in data['knowledge_outcomes'][0]['error']


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
