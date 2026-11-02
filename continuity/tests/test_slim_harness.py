"""Deterministic workflow boundaries exercised with redacted captured instructions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/slim-harness'
FIX = ROOT / 'tests/fixtures/slim-harness'


@pytest.mark.parametrize('configured', [True, False])
def test_enforcement_reference_config_present_or_absent(configured, tmp_path):
    example = json.loads((ROOT / 'docs/examples/config.json').read_text())
    reference = example['harness_enforcement_reference']
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'harness_enforcement_reference': reference} if configured else {}))
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'config-get',
         'harness_enforcement_reference'],
        env=dict(os.environ, CONTINUITY_CONFIG=str(config)), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (reference + '\n' if configured else '')


@pytest.mark.parametrize('path_kind', ['absolute', 'home', 'relative'])
def test_enforcement_reference_path_contract_is_independent_of_cwd(path_kind, tmp_path):
    reference = {'absolute': str(tmp_path / 'enforcement.md'),
                 'home': '~/state/harness/enforcement.md',
                 'relative': 'enforcement.md'}[path_kind]
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'harness_enforcement_reference': reference}))
    other = tmp_path / 'other'
    other.mkdir()
    for cwd in [tmp_path, other]:
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'config-get',
             'harness_enforcement_reference'], cwd=cwd,
            env=dict(os.environ, CONTINUITY_CONFIG=str(config)), capture_output=True, text=True)
        if path_kind == 'relative':
            assert result.returncode == 2
            assert 'harness_enforcement_reference must be an absolute or ~/ path' in result.stderr
            assert result.stdout == ''
        else:
            assert result.returncode == 0, result.stderr
            assert result.stdout == reference + '\n'

@pytest.mark.parametrize('count', [0, 1, 2])
def test_enforcement_reference_rejects_list_values(count, tmp_path):
    example = json.loads((ROOT / 'docs/examples/config.json').read_text())
    reference = example['harness_enforcement_reference']
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'harness_enforcement_reference': [reference] * count}))
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'config-get',
         'harness_enforcement_reference'],
        env=dict(os.environ, CONTINUITY_CONFIG=str(config)), capture_output=True, text=True)
    assert result.returncode == 2
    assert 'continuity config' in result.stderr
    assert 'harness_enforcement_reference must be a non-empty string' in result.stderr
    assert result.stdout == ''


@pytest.mark.parametrize('count', [0, 1, 2])
def test_config_get_preserves_other_list_values(count, tmp_path):
    example = json.loads((ROOT / 'docs/examples/config.json').read_text())
    values = [example['harness_enforcement_reference']] * count
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'checklist_surfaces': values}))
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/lib/handoff.py'), 'config-get',
         'checklist_surfaces'],
        env=dict(os.environ, CONTINUITY_CONFIG=str(config)), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == '\n'.join(values) + '\n'


def helper():
    path = SKILL / 'scripts/harness.py'
    assert path.is_file(), 'shared measurement and edit helper must ship'
    spec = importlib.util.spec_from_file_location('slim_helper', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def entry(path, kind='rules', loaded='full', **kwargs):
    return dict(path=str(path), kind=kind, loaded=loaded, **kwargs)

@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_loaded_over_limit_and_listed_only_scope(tool):
    m = helper()
    result = m.measure(dict(tool=tool, files=[entry(FIX/'rules.md'), entry(FIX/'SKILL.md','skill'),
        entry(FIX/'roles/core.md'), entry(FIX/'rules.md',loaded='other')]))
    assert {r['path'] for r in result['over_limit']} == {str(FIX/'rules.md'), str(FIX/'SKILL.md')}
    for row in result['over_limit']:
        assert row['size']['words'] > 0 and row['size']['bytes'] > 0
        assert row['action'] == 'run /slim-harness on `' + row['path'] + '`'
    listed = m.measure(dict(tool=tool, files=[entry(FIX/'SKILL.md','skill','listed')]))
    assert listed['over_limit'] == []


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('loaded', ['full', 'auto'])
def test_long_line_skill_body_exceeds_byte_limit(tool,loaded,tmp_path):
    m=helper(); fields,body=m.frontmatter((FIX/'SKILL.md').read_text())
    body=' '.join(body.split())
    assert len(body.splitlines()) < 500 and len(body.encode('utf-8')) > 20000
    assert len(body) < len(body.encode('utf-8'))
    target=tmp_path/'SKILL.md'
    target.write_text('---\ndescription: '+json.dumps(fields['description'])+'\n---\n'+body,
                      encoding='utf-8')
    result=m.measure(dict(tool=tool,files=[entry(target,'skill',loaded)]))
    assert len(result['over_limit'])==1
    row=result['over_limit'][0]
    assert row['limits']==[dict(unit='body bytes',measured=len(body.encode('utf-8')),limit=20000)]
    assert row['action']=='run /slim-harness on `'+str(target)+'`'
    assert m.measure(dict(tool=tool,files=[entry(target,'skill','listed')]))['over_limit']==[]


@pytest.mark.parametrize('tool', ['claude', 'codex'])
def test_skill_byte_boundary_excludes_frontmatter_and_counts_utf8(tool,tmp_path):
    m=helper(); _,body=m.frontmatter((FIX/'SKILL.md').read_text())
    body=' '.join(body.split())
    # Slice captured instructions at a UTF-8 boundary, then fill with captured spaces.
    body=body.encode('utf-8')[:20000].decode('utf-8',errors='ignore')
    body+=' '*(20000-len(body.encode('utf-8')))
    target=tmp_path/'SKILL.md'
    header='---\ndescription: captured\n---\n'
    target.write_text(header+body,encoding='utf-8')
    assert m.measure(dict(tool=tool,files=[entry(target,'skill')]))['over_limit']==[]
    target.write_text(header+body+' ',encoding='utf-8')
    row=m.measure(dict(tool=tool,files=[entry(target,'skill')]))['over_limit'][0]
    assert row['limits']==[dict(unit='body bytes',measured=20001,limit=20000)]

@pytest.mark.parametrize('tool,kind,name', [('claude','agent','agents/task.md'),('codex','agent','agents/task.toml'),
    ('claude','role','roles/core.md'),('claude','output-style','output-styles/style.md'),('codex','rules','chain/AGENTS.md')])
def test_200_line_types_from_captured_files(tool,kind,name,tmp_path):
    m=helper(); text=(FIX/name).read_text()
    # Expand only blank-line spacing in captured text: no invented instruction records.
    target=tmp_path/Path(name).name; target.write_text(text.replace('\n', '\n' * 40))
    result=m.measure(dict(tool=tool,files=[entry(target,kind)]))
    if len(target.read_text().splitlines()) <= 200:
        assert result['over_limit'] == []
    else:
        assert result['over_limit'][0]['limits'] == [{'unit':'lines','measured':len(target.read_text().splitlines()),'limit':200}]
    assert m.measure(dict(tool=tool,files=[entry(FIX/name,kind)]))['over_limit'] == []

@pytest.mark.parametrize('tool', ['claude','codex'])
def test_description_character_limits_and_listing_budget(tool,tmp_path):
    m=helper(); text=(FIX/'SKILL.md').read_text(); body=text.split('---',2)[2]
    target=tmp_path/'SKILL.md'; description=' '.join(body.split())[:1100]
    target.write_text('---\nname: captured\ndescription: '+json.dumps(description)+'\nwhen_to_use: '+json.dumps(description)+'\n---\n'+body)
    result=m.measure(dict(tool=tool, files=[entry(target,'skill','listed')],shortened_descriptions=True))
    limits=result['over_limit'][0]['limits']
    assert {'unit':'description characters','measured':1100,'limit':1024} in limits
    assert any(l['limit']==1536 for l in limits) == (tool=='claude')
    if tool=='codex':
        assert result['listing']['budget']==8000 and result['listing']['largest'][0]['characters']==1100
        assert m.measure(dict(tool=tool,files=[],shortened_descriptions=True,context_window=100000))['listing']['budget']==2000


def test_codex_chain_under_line_limit_but_over_bytes():
    m=helper();paths=[FIX/'chain/AGENTS.md', FIX/'chain/area/AGENTS.md']
    result=m.measure(dict(tool='codex',files=[entry(p) for p in paths],chain=list(map(str,paths))))
    assert len(result['over_limit'])==1
    row=result['over_limit'][0]
    assert row['path']=='AGENTS.md chain' and row['limits'][0]['limit']==32768
    assert row['size']['lines'] < 200


def test_missing_role_is_reported_not_measured():
    m=helper(); missing=FIX/'roles/missing.md'
    result=m.measure(dict(tool='claude',files=[entry(FIX/'agents/task.md','agent',role_paths=[str(FIX/'roles/core.md'),str(missing)])]))
    assert str(missing) in result['unresolved']
    assert str(missing) not in [r['path'] for r in result['measured']]
    assert str(FIX/'roles/core.md') in [r['path'] for r in result['measured']]


def test_dead_references_existing_and_missing(tmp_path):
    script=SKILL/'scripts/dead_references.py'
    assert script.exists()
    result=subprocess.run([sys.executable,str(script),'--base',str(FIX),'--path','roles/core.md',
        '--path','roles/missing.md','--command',sys.executable,'--command','missing-captured-command'],capture_output=True,text=True)
    assert result.returncode==1
    assert json.loads(result.stdout)=={'missing_paths':['roles/missing.md'],'missing_commands':['missing-captured-command']}


def test_edit_and_numbered_revert_preserve_dirty_tree_and_symlink(tmp_path):
    m=helper(); repo=tmp_path/'repo';repo.mkdir()
    subprocess.run(['git','init','-q',str(repo)],check=True)
    target=repo/'rules.md'; original=(FIX/'rules.md').read_text();target.write_text(original)
    subprocess.run(['git','-C',str(repo),'add','rules.md'],check=True)
    subprocess.run(['git','-C',str(repo),'-c','user.name=Test','-c','user.email=test@example.org','commit','-qm','Captured baseline'],check=True)
    old=original.splitlines()[0]; before=original+'\n'+(FIX/'roles/task.md').read_text();target.write_text(before)
    link=tmp_path/'link.md';link.symlink_to(target); journal=tmp_path/'changes.json'
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'])
    assert m.edit(link,old,'# Reviewed instructions',journal,mode='unattended')['needs_user']
    assert target.read_text()==before and not journal.exists()
    changed=m.edit(link,old,'# Reviewed instructions',journal)
    assert changed['source']==str(target.resolve()) and changed['number']==1
    assert str(repo) in changed['dirty_repositories']
    m.revert(journal,1)
    assert target.read_text()==before
    assert subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'])==head
    assert subprocess.check_output(['git','-C',str(repo),'status','--short']).startswith(b' M')
    assert m.edit(target,old,old,journal)['changed'] is False


def test_revert_refuses_ambiguous_or_changed_own_lines(tmp_path):
    m=helper();target=tmp_path/'rules.md';target.write_text((FIX/'rules.md').read_text())
    journal=tmp_path/'changes.json';old=target.read_text().splitlines()[0]
    m.edit(target,old,'# Unique revised instruction heading',journal)
    target.write_text(target.read_text().replace('# Unique revised instruction heading','# Unique later instruction heading'))
    with pytest.raises(ValueError): m.revert(journal,1)
    assert target.read_text().startswith('# Unique later instruction heading')


def test_skill_review_contract_and_source_routing():
    # Instruction contract, not a claim that a live model performed semantic review.
    assert (SKILL/'SKILL.md').exists()
    text=(SKILL/'SKILL.md').read_text()
    phases=['Redundancy','Unneeded context','Conflicts','Extraction','Compression']
    assert [text.index('### '+p) for p in phases]==sorted(text.index('### '+p) for p in phases)
    for clause in ['intent, goals, audience', 'one-line why', 'judgment criterion', 'older models',
        'double-check', 'think hard', 'delete, propose a hook, or keep', 'both tools', 'before any edit',
        'number', 'own lines only', 'never commits', 'no findings', 'every repository',
        'one level deep', '100 lines', "skill’s own rule", 'Produced surfaces', 'regeneration command',
        'block of examples', 'keeps at most a pointer', 'no entry', 'source only', 'generated surface', 'resolved source', 'loaded beside', 'full diff']:
        assert clause in text,clause
    improve=(ROOT/'skills/improve-harness/SKILL.md').read_text()
    for clause in ['Over-limit files','lesson','Produced surfaces','regeneration command','exempt','runs nothing', 'listed']:
        assert clause in improve,clause
    claude=(SKILL/'references/claude.md').read_text();codex=(SKILL/'references/codex.md').read_text()
    assert 'paths:' in claude and 'confirms' in codex and 'start' in codex
    assert 'no known output-style equivalent' in codex
    for ref in [claude,codex]:
        assert '2026-10-12' in ref and 'https://' in ref


def test_package_installer_registers_skill():
    path=ROOT/'scripts/install-codex.py'
    spec=importlib.util.spec_from_file_location('installer',path)
    sys.path.insert(0,str(ROOT/'scripts'))
    try:
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        assert 'slim-harness' in module.SKILLS
    finally: sys.path.pop(0)
    assert (SKILL/'references/claude.md').exists() and (SKILL/'references/codex.md').exists()


def test_edit_preserves_unrelated_line_endings(tmp_path):
    m=helper(); target=tmp_path/'rules.md'
    captured=(FIX/'rules.md').read_text().replace('\n','\r\n').encode()
    target.write_bytes(captured);old=captured.decode().split('\r\n')[0]
    measured=m.measure(dict(tool='codex',files=[entry(target)]))
    assert measured['measured'][0]['size']['bytes']==len(captured)
    journal=tmp_path/'changes.json'
    m.edit(target,old,'# Unique replacement heading',journal)
    assert target.read_bytes()==captured.replace(old.encode(),b'# Unique replacement heading',1)
    m.revert(journal,1)
    assert target.read_bytes()==captured


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('field', ['description', 'when_to_use'])
def test_multiline_plain_discovery_scalar_is_not_silently_undercounted(tool,field,tmp_path):
    m=helper(); body=(FIX/'SKILL.md').read_text().split('---',2)[2]
    # Continuations are real captured prose; the first line alone is below the limit.
    prose=' '.join(word for word in body.split() if word.isalpha())[:1100]
    target=tmp_path/'SKILL.md'
    target.write_text('---\nname: captured\n'+field+': '+prose[:100]+'\n  '+prose[100:600]+'\n  '+prose[600:]+'\n---\n')
    assert len(prose[:100]) < 1024 < len(prose)
    # Explicit refusal naming the field is supported; silently measuring 100 is not.
    with pytest.raises(ValueError,match='unsupported.*'+field):
        m.measure(dict(tool=tool,files=[entry(target,'skill','listed')]))


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('loads', [('listed','full'), ('full','listed')])
def test_listed_and_full_skill_merge_retains_all_sizes_and_limits(tool,loads,tmp_path):
    m=helper();body=(FIX/'SKILL.md').read_text().split('---',2)[2]
    description=' '.join(body.split())[:1100]
    target=tmp_path/'SKILL.md'
    text='---\nname: captured\ndescription: '+json.dumps(description)+'\n---\n'+body
    target.write_text(text)
    result=m.measure(dict(tool=tool,files=[entry(target,'skill',load) for load in loads]))
    assert len(result['over_limit'])==1
    row=result['over_limit'][0]
    assert row['size']==dict(lines=len(text.splitlines()),words=len(text.split()),
                             bytes=len(text.encode()),description_characters=len(description))
    assert {item['unit']:item['measured'] for item in row['limits']}=={
        'description characters':1100, 'body lines':len(body.splitlines()),
        'body bytes':len(body.encode('utf-8'))}
    assert {item['unit']:item['limit'] for item in row['limits']}=={
        'description characters':1024, 'body lines':500, 'body bytes':20000}
