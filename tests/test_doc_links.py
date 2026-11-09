"""Execute the runbook's link check against controlled Markdown documents."""
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def check(tmp_path, target, links):
    (tmp_path / 'README.md').write_text(links)
    (tmp_path / 'RELEASE_CANDIDATE.md').write_text(target)
    (tmp_path / 'INSTALLATION.md').write_text('')
    # Exercise exactly the documented command, including its script wiring.
    section = (ROOT / 'RELEASING.md').read_text().split('5. **Stale links and paths.**', 1)[1]
    command = re.search(r'```bash\n(.*?)\n\s*```', section, re.S)[1]
    command = '\n'.join(line.removeprefix('   ') for line in command.splitlines())
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, text=True, capture_output=True)
    assert not result.stderr, result.stderr
    assert result.returncode == (1 if result.stdout else 0)
    return result


@pytest.mark.parametrize('anchor', ['sco!pe', 'Scope', 'scope-99'])
def test_fragment_is_not_normalized_into_an_existing_anchor(tmp_path, anchor):
    result = check(tmp_path, '# Scope\n', f'[x](RELEASE_CANDIDATE.md#{anchor})')
    assert f'missing anchor: RELEASE_CANDIDATE.md#{anchor}' in result.stdout


@pytest.mark.parametrize('opening,closing', [('```sh', '```'), ('~~~sh', '~~~'), ('````sh', '````')])
@pytest.mark.parametrize('prefix,indent', [('', ''), ('- Example\n\n', '    ')])
def test_fenced_code_has_no_heading_anchors(tmp_path, opening, closing, prefix, indent):
    target = prefix + '\n'.join(indent + line for line in [opening, '# Only in code', closing, ''])
    result = check(tmp_path, target, '[x](RELEASE_CANDIDATE.md#only-in-code)')
    assert 'missing anchor: RELEASE_CANDIDATE.md#only-in-code' in result.stdout


def test_indented_code_and_html_comments_have_no_heading_anchors(tmp_path):
    result = check(tmp_path, '    # Indented code\n\n<!--\n# Comment\n-->\n',
                   '[x](RELEASE_CANDIDATE.md#indented-code)\n[x](RELEASE_CANDIDATE.md#comment)')
    assert 'missing anchor: RELEASE_CANDIDATE.md#indented-code' in result.stdout
    assert 'missing anchor: RELEASE_CANDIDATE.md#comment' in result.stdout


@pytest.mark.parametrize('target,anchors', [
    ('# Scope\n## Scope\n# Scope-1\n# Scope\n', ['scope', 'scope-1', 'scope-1-1', 'scope-2']),
    ('# **Bold** and [a link](https://example.test/target) with `code`\n', ['bold-and-a-link-with-code']),
    ('# ~~Deleted~~ and <em>HTML</em> &amp; text\n', ['deleted-and-html--text']),
    ('# Héllo_world:  two spaces!\n', ['héllo_world--two-spaces']),
    ('Setext heading\n===\n\n### Closing hashes ###\n', ['setext-heading', 'closing-hashes']),
    ('- Item\n\n    ## Nested heading\n', ['nested-heading']),
])
def test_real_heading_anchors_resolve(tmp_path, target, anchors):
    result = check(tmp_path, target, '\n'.join(f'[x](RELEASE_CANDIDATE.md#{a})' for a in anchors))
    assert result.stdout == ''
    assert result.returncode == 0


def test_missing_files_and_local_fragments(tmp_path):
    result = check(tmp_path, '', '# Local\n[x](#local)\n[x](missing.md#local)\n[x](#absent)')
    assert result.stdout.splitlines() == ['missing: missing.md#local', 'missing anchor: #absent']


def test_reference_links_checked_but_code_examples_ignored(tmp_path):
    result = check(tmp_path, '# Scope\n', '[x][ref]\n\n[ref]: RELEASE_CANDIDATE.md#absent\n\n'
                   '```md\n[x](example.md#example)\n```\n\n`[x](inline.md)`\n')
    assert result.stdout.splitlines() == ['missing anchor: RELEASE_CANDIDATE.md#absent']


@pytest.mark.parametrize('wrapper', ['{}', '<div>\n{}\n</div>'])
@pytest.mark.parametrize('tag,attribute', [('a', 'href'), ('img', 'src')])
def test_raw_html_missing_destinations_are_reported(tmp_path, wrapper, tag, attribute):
    html = wrapper.format(f'<{tag} {attribute}="missing.svg">')
    result = check(tmp_path, '# Scope\n', html)
    assert result.stdout.splitlines() == ['missing: missing.svg']


@pytest.mark.parametrize('anchor,missing', [('scope', False), ('sco!pe', True), ('absent', True)])
def test_raw_html_fragments_use_the_same_exact_heading_check(tmp_path, anchor, missing):
    result = check(tmp_path, '# Scope\n', f'<a href="RELEASE_CANDIDATE.md#{anchor}">link</a>')
    expected = f'missing anchor: RELEASE_CANDIDATE.md#{anchor}\n' if missing else ''
    assert result.stdout == expected


def test_raw_html_existing_and_external_destinations_are_valid(tmp_path):
    (tmp_path / 'image.svg').write_text('<svg/>')
    result = check(tmp_path, '', '<div>\n<A HREF="INSTALLATION.md">install</A>\n'
                   '<IMG SRC="image.svg"/>\n<a href="https://example.test/missing">external</a>\n'
                   '<img src="//example.test/missing.svg">\n</div>')
    assert result.stdout == ''


def test_raw_html_in_comments_and_code_is_not_a_rendered_link(tmp_path):
    result = check(tmp_path, '', '<!-- <a href="comment.md">comment</a> -->\n\n'
                   '```html\n<a href="fenced.md">fenced</a>\n```\n\n'
                   '~~~html\n<img src="tilde.svg">\n~~~\n\n'
                   '`<a href="inline.md">inline</a>`\n\n'
                   '    <img src="indented.svg">\n')
    assert result.stdout == ''
