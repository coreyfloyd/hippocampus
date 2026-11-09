#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["markdown-it-py==4.0.0"]
# ///
"""Check relative documentation links and GitHub heading fragments.

Run with uv so the pinned Markdown parser is available. CommonMark block and
inline tokens keep examples out of the check and formatting out of heading text.
"""
from html.parser import HTMLParser
from pathlib import Path
import sys
import unicodedata
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


class RenderedContent(HTMLParser):
    """Read rendered text and link destinations, including raw HTML."""

    def __init__(self, rendered):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.feed(rendered)

    def handle_starttag(self, tag, attrs):
        attribute = {'a': 'href', 'img': 'src'}.get(tag)
        if attribute:
            for name, value in attrs:
                if name == attribute and value is not None:
                    self.links.append(value)

    def handle_data(self, data):
        self.parts.append(data)


def document(path):
    parser = MarkdownIt('commonmark').enable(['strikethrough', 'table'])
    tokens = parser.parse(path.read_text())
    anchors = set()
    for index, token in enumerate(tokens):
        if token.type != 'inline':
            continue
        if index and tokens[index - 1].type == 'heading_open':
            rendered = parser.renderer.renderInline(token.children, parser.options, {})
            text = ''.join(RenderedContent(rendered).parts).lower()
            # GitHub keeps letters, numbers, combining marks, underscores and
            # hyphens. Each space becomes a hyphen; runs are not collapsed.
            base = ''.join(c for c in text if c in ' -_' or
                           unicodedata.category(c)[0] in 'LNM').replace(' ', '-')
            anchor, suffix = base, 0
            while anchor in anchors:
                suffix += 1
                anchor = f'{base}-{suffix}'
            anchors.add(anchor)
    # Rendering escapes code examples while preserving actual HTML links.
    # One collector therefore handles both Markdown and raw HTML destinations.
    rendered = parser.renderer.render(tokens, parser.options, {})
    return anchors, RenderedContent(rendered).links


def main(sources):
    documents = {}

    def read(path):
        path = path.resolve()
        if path not in documents:
            documents[path] = document(path)
        return documents[path]

    missing = False
    for source in map(Path, sources):
        for link in read(source)[1]:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            destination = source.parent / unquote(url.path) if url.path else source
            if not destination.exists():
                print(f'missing: {link}')
                missing = True
            elif url.fragment and unquote(url.fragment) not in read(destination)[0]:
                # URL decoding handles encoded Unicode, but never slugify a
                # supplied fragment: punctuation and case must match exactly.
                print(f'missing anchor: {link}')
                missing = True
    return int(missing)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
