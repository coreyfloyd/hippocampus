# Session package snapshot

Imported for [hippocampus#58](https://github.com/coreyfloyd/hippocampus/issues/58)
from source commit `5198d0567840694e71ddc20877c9a2c3415b0d80`.
The source repository had no open pull requests when queried on 2026-11-01.
The owner approved a single snapshot import without source history, superseding
the parent specification's original history requirement.

The parent specification does not prescribe a staging directory. `continuity/`
is the temporary prefix; the rename slice moves its contents into the final
package layout. Existing installers and runtime behavior are unchanged here.
The initial source adjustment makes architecture documentation tests distinguish
a staged snapshot from a source checkout: file and line checks still run, but
source-history checks require the original repository root.

`continuity-inventory.tsv` records case-insensitive occurrences in both agreed
input trees, including content, filenames and the temporary prefix. Line and
column coordinates refer to the original revisions, before the test adjustment.
The generated inventory and this import record are retained historical cutover
evidence; their own references and the generator's pinned source name are
intended exclusions. Temporary prefix components on each imported path are
represented by the single `staging-prefix` entry.

Regenerate from a local source clone containing the pinned commit:

```sh
python3 scripts/generate-fold-inventory.py --source-repo /path/to/source-clone
```

Each row assigns its disposition to a later slice: 59 handles package names,
configuration, documentation and fixtures; 62 handles installation and plugin
surfaces; 64 handles release and signing surfaces. Immutable source links stay
as historical attribution under slice 59. These assignments track naming work;
semantic checklist and composer changes remain in their own planned slices.

Review repairs keep the staged release builder from archiving the enclosing
repository: it refuses before signing or writing output and directs release
work to hippocampus issue 64. Standalone fixture copies retain the historical
release tests. The source workflow now lives at `.github/workflows/continuity.yml`
with its run steps rooted in the staging directory, so GitHub discovers it.
The pinned inventory remains an input-tree inventory; slice 62 owns the moved
workflow's naming references, and slice 64 owns the release-script references.

## Rename slice

The runtime, hooks, skills and tests now live at the package root. The session
guide is `docs/session-guide.md`, the interface is `INTERFACE.md`, and the shared
glossary is `docs/glossary.md`. The imported architecture's source citations
remain pinned to their source repository. Release-only scripts, signing material
and their tests remain isolated in `tests/fixtures/session-release/` for issue 64;
the fixture builder still refuses to release the enclosing repository.

Run `python3 scripts/check-fold-names.py --write` to regenerate
`docs/fold-name-dispositions.tsv`. It audits the pinned inventory and current
tracked or new files, rejects unhandled source-package names, and records the
reason for every retained occurrence. The original input inventory stays intact.
