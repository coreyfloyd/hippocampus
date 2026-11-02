#!/usr/bin/env python3
"""Report references to a private setup in files that are meant to ship.

The terms come from a file the caller names, so this module carries none of
them. Matching is case-insensitive and otherwise literal, except that a
separator (``-``, ``_``, ``.``, or whitespace) between two letters or digits of
a term matches any run of separators or none: ``example-host`` also reports
``Example Host``, ``example_host``, and ``examplehost``. A term matches whole
words only: where a term starts or ends with a letter or digit, the text
beside the match must not continue the word. A camel-case join is a word
boundary (``ExampleHostLogs`` reports ``example-host``, ``exampleHostname``
does not), and a trailing plural ``s`` or ``es`` is part of the match.
The repository's own public slug (``coreyfloyd/continuity``, also inside its
GitHub URL) is allowed. In a provenance file (``PROVENANCE.md``), lines that
describe the upstream source are exempt unless they also name a fork or
carry a ticket link.

Usage:
    reference_check.py --terms TERMS_FILE PATH [PATH ...]
    REFERENCE_CHECK_TERMS=TERMS_FILE reference_check.py PATH [PATH ...]

A PATH may be a file or a directory, which is scanned recursively, skipping
``.git`` and files that are not UTF-8 text. Each finding prints one line,
``path:line:column: term: text``. Exit status: 0 clean, 1 findings, 2 usage
error (no terms file, an empty terms file, or a missing path).

Terms file: one term per line. Blank lines and lines starting with ``#`` are
ignored; write ``\\#`` to start a term with ``#`` (``\\#channel``).
"""
import argparse
import os
import re
import sys

TERMS_ENV = "REFERENCE_CHECK_TERMS"
PROVENANCE_NAME = "provenance.md"
SKIPPED_DIRS = {".git"}
TICKET_LINK = re.compile(r"#\d+|/(issues|pull)/\d+")
SEPARATORS = "-_. \t"
SEPARATOR_RUN = r"[-_.\s]*"
PLURAL_SUFFIXES = ("", "s", "es")
# The repository's own public slug, which its install commands and links must name.
# It may end with ``.git``; after that only a URL continuation or punctuation may
# follow, so ``.private`` or ``-fork`` names a different repository and still counts.
OWN_REPOSITORY = re.compile(r"(?<![\w.-])coreyfloyd/continuity(?:\.git)?(?![\w-])(?!\.\w)", re.IGNORECASE)


class UsageError(Exception):
    pass


def entries(lines):
    """The stripped lines that are not blank and not ``#`` comments."""
    stripped = (line.strip() for line in lines)
    return [line for line in stripped if line and not line.startswith("#")]


def unescape(entry):
    """A leading ``\\#`` stands for ``#``, which would otherwise start a comment."""
    return entry[1:] if entry.startswith("\\#") else entry


def load_terms(path):
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        raise UsageError(f"cannot read terms file {path}: {exc.strerror}")
    terms = [unescape(term) for term in entries(lines)]
    if not terms:
        raise UsageError(f"terms file {path} lists no terms")
    return terms


def term_pattern(term):
    """Compile a term so each separator between two alphanumerics matches any separator run."""
    parts = []
    for index, char in enumerate(term):
        inner = 0 < index < len(term) - 1
        if inner and char in SEPARATORS and term[index - 1].isalnum() and term[index + 1].isalnum():
            parts.append(SEPARATOR_RUN)
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts), re.IGNORECASE)


def continues_word(before, after):
    """True when ``after`` carries on the word ``before`` ends, so the two are not split by a word boundary."""
    if not after.isalnum() or not before.isalnum():
        return False
    return not (before.islower() and after.isupper())


def is_whole_word(term, line, start, end, starts, ends):
    """True when the match ``line[start:end]`` of ``term`` is not part of a longer word.

    A side that runs straight into another term's match (in ``starts`` or
    ``ends``) is a boundary, so two terms written as one word still count.
    """
    if term[0].isalnum() and start > 0 and start not in ends and continues_word(line[start - 1], line[start]):
        return False
    if not term[-1].isalnum() or end in starts:
        return True
    for suffix in PLURAL_SUFFIXES:
        stop = end + len(suffix)
        if line[end:stop].lower() == suffix and (
            stop == len(line) or not continues_word(line[stop - 1], line[stop])
        ):
            return True
    return False


def allowed_spans(line):
    return [match.span() for match in OWN_REPOSITORY.finditer(line)]


def iter_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
                for name in sorted(files):
                    yield os.path.join(root, name)
        elif os.path.isfile(path):
            yield path
        else:
            raise UsageError(f"no such file or directory: {path}")


def is_provenance(path):
    return os.path.basename(path).lower() == PROVENANCE_NAME


def is_upstream_line(line):
    """True for a provenance line that only describes the upstream source."""
    lowered = line.lower()
    return (
        "upstream" in lowered
        and "fork" not in lowered
        and not TICKET_LINK.search(line)
    )


def check_text(path, text, terms):
    """Return (line, column, term, text) for each term occurrence."""
    findings = []
    patterns = [(term, term_pattern(term)) for term in terms]
    provenance = is_provenance(path)
    for number, line in enumerate(text.splitlines(), start=1):
        if provenance and is_upstream_line(line):
            continue
        allowed = allowed_spans(line)
        matches = []
        for term, pattern in patterns:
            match = pattern.search(line)
            while match:
                matches.append((term, match.start(), match.end()))
                match = pattern.search(line, match.start() + 1)
        kept = [(term, start, end) for term, start, end in matches
                if not any(low <= start and end <= high for low, high in allowed)]
        # A match that leans on a neighbour for its boundary counts only while that neighbour does.
        while True:
            starts = {start for _, start, _ in kept}
            ends = {end for _, _, end in kept}
            whole = [m for m in kept if is_whole_word(m[0], line, m[1], m[2], starts, ends)]
            if len(whole) == len(kept):
                break
            kept = whole
        hits = [(start + 1, term) for term, start, _ in kept]
        for column, term in sorted(hits):
            findings.append((number, column, term, line.strip()))
    return findings


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError:
        return None


def run(paths, terms):
    findings = []
    for path in iter_files(paths):
        text = read_text(path)
        if text is None:
            continue
        for number, column, term, line in check_text(path, text, terms):
            findings.append(f"{path}:{number}:{column}: {term}: {line}")
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Report references to a private setup in files meant to ship."
    )
    parser.add_argument(
        "--terms",
        default=os.environ.get(TERMS_ENV),
        help=f"terms file, one term per line (default: ${TERMS_ENV})",
    )
    parser.add_argument("paths", nargs="+", help="files or directories to check")
    args = parser.parse_args(argv)
    try:
        if not args.terms:
            raise UsageError(f"no terms file: pass --terms or set {TERMS_ENV}")
        findings = run(args.paths, load_terms(args.terms))
    except UsageError as exc:
        print(f"reference_check: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    if findings:
        print(f"reference_check: {len(findings)} reference(s) found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
