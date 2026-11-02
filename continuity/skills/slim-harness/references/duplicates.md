# Duplicate-rule detection

Run `python3 <slim-harness-dir>/scripts/harness.py duplicates <manifest.json>`.
Use the measurement manifest documented in `../SKILL.md`; the caller attests the
running session's actual loaded files. This is the same stdlib-only helper in
Claude Code and Codex. No model call, file discovery, source edit, journal,
generator execution, or git mutation occurs.

## Scope and sentence spans

Only `full` and `auto` instruction bodies participate. Listed-only skills,
`other` entries, and Codex output styles are excluded. Parent-supplied agent
`role_paths` participate, resolved relative to the agent file. Missing files are
reported in `unresolved`. Symlinks resolve to one physical source; repeated
manifest entries and aliases do not create self-matches. Comparisons are across
different sources only, with one row per matching sentence pair.

The extractor skips initial YAML frontmatter, Markdown headings, pipe tables,
HTML-comment lines, and fenced backtick/tilde code. Tables are recognized by a
header and a separator row with matching cell counts; outer pipes are optional.
Escaped pipes stay in their cells. Table bodies end at blank lines or a new
Markdown block (heading, list, quote, fence, comment, or thematic break).
Blank lines and list-item starts break prose blocks; soft-wrapped lines stay
together. Within each block,
a period, question mark, or exclamation mark followed by whitespace or end of
block ends a sentence. A final fragment also counts. Every span retains its text
and its original inclusive, one-based physical line range, including soft wraps.

## Deterministic threshold (chosen 2026-10-17)

Normalize Unicode with NFKC, case-fold, fold curly apostrophes to straight ones,
and tokenize words (including internal apostrophes). Punctuation, Markdown
emphasis, and whitespace are not tokens. Keep sentences with **at least 2 tokens
and 10 normalized characters** (tokens joined by single spaces), so short exact
boundaries such as “Do not commit.” remain eligible. Near matching requires
**at least 8 tokens and 40 normalized characters on each side** to reduce noise.

- **Exact:** identical normalized token sequences.
- **Near:** `difflib.SequenceMatcher(None, tokens_a, tokens_b, autojunk=False)`
  ratio **at least 0.90**, inclusive, with sources ordered by resolved path.
  Ratio is `2 * matching_tokens / (tokens_a + tokens_b)`. The token-count upper
  bound eliminates impossible pairs before comparison; there is no corpus cap.
- Near pairs must have the same ordered sequence of these boundary words:
  `not`, `no`, `never`, `always`, `only`, `cannot`, `can't`, `don't`, `without`.
  This screens obvious polarity changes; it is not a semantic equivalence check.

The 0.90 threshold permits small wording changes while requiring most words in
the same order. Tests use shipped skill prose and a one-word insertion, plus
exclusions and an opposite instruction. Similarity is rounded to four decimals
only for output; classification uses the unrounded ratio.

## Result and review boundary

JSON contains `duplicates` and `unresolved`. A finding has `type: duplicate-rule`,
`match: exact|near`, `similarity`, two `spans`, and an `action`. Each span has
`path` (the loaded name), `source` (resolved path), `start_line`, `end_line`, and
`text`. A successful command exits 0 even with findings or unresolved files;
invalid manifests or read/decode errors exit 2 with a diagnostic.

Improve-harness displays these as independent rows beside size findings, including
unattended delivery. The action asks for `/slim-harness` on the file that does not
own the rule. The helper cannot infer ownership, loading from a transcript,
canonical/generated provenance, or whether repetition is intentional. It never
chooses a file to cut. Different contexts, numbers, paths, and small exceptions
can matter even in a high-scoring pair; review both spans before any trimming.

This is a lexical Markdown heuristic, not a Markdown parser or a contradiction
detector: abbreviations can split sentences, inline code/link tokens participate,
and semantic paraphrases, very short rules, and differently segmented prose can
be missed. Generated copies remain separate candidates unless they resolve to
the same source. For N candidate sentences, pair comparison is quadratic in the
worst case; this command targets the explicit session set, not entire catalogs.
