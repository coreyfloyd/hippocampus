# Session package snapshot

Imported for [hippocampus#58](https://github.com/coreyfloyd/hippocampus/issues/58)
from source commit `5198d0567840694e71ddc20877c9a2c3415b0d80`.
The source repository had no open pull requests when queried on 2026-11-01.
The owner approved a single snapshot import without source history, superseding
the parent specification's original history requirement.

The parent specification does not prescribe a staging directory. `continuity/`
is the temporary prefix; the rename slice moves its contents into the final
package layout. Existing installers and runtime behavior are unchanged here.
The only source adjustment makes architecture documentation tests distinguish
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
