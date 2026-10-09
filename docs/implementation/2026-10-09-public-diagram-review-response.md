# Public diagram review response

Tracking: [hippocampus#31](https://github.com/coreyfloyd/hippocampus/issues/31).
Primary review: [public diagram changes required](https://github.com/coreyfloyd/hippocampus/issues/31#issuecomment-6088162347).
Starting candidate: `7f47af8`, branch `codex/meeting-absorb-compile`.
Scope: current public diagram semantics, captions, deck visuals, architecture source/render and comparison rendering. Skills, distribution behavior, runtime, package/install files and installed releases are unchanged.

## Diagnosis from primary evidence

Read the current ticket and its named comment through authenticated GitHub API reads, then the approved five-story specification, capture frontends, shared distribution contract, compiler and retention implementation.

At the starting candidate, `question-answer-action.svg` drew `M745,297 L745,491` from the absorb box to the research-report box. Its meeting-record node had no outgoing edge. Both the capture command and meeting record used the same violet rounded box, while the report and destinations borrowed green execution colors. There was no legend. These are documentation defects, not evidence of changed distribution behavior. (validated: starting SVG, approved specification S1–S3 and helper `capture`/`execute`/`finalize`)

The related deck used an undifferentiated capture convergence, a colored funnel, a shared report mockup and direct report-to-target connectors; it merged writing with retention and used a trash icon for that category. The architecture source reversed the research-plan input (`absorb` → artifact), represented command/record/store roles with generic component colors, and described a retained report as “excluded primary evidence.” The record is an excluded **reference**, not primary evidence. The README text flow also visually chained actions into compilation and source filing. (validated: starting deck slides 4–9, architecture connections/cards and README text diagram)

The cause was a diagram model organized around stages and loose boxes rather than typed objects, operations and control boundaries; it combined capture output with later retention. Arrow directions then mixed data flow with reader-to-file relationships. That allowed documentation to drift from the implemented contract. (inferred: contrasting those authored placements/connections with the primary implementation)

The correction rebuilds the entire related visual from one shared source model, with three panels: capture/approval, execution/compiler detail and terminal retention. Both record kinds now exist before absorb. The existing viewer implementation is retained; only its graph, evidence bindings and dependent captions/cards change. Repeated absorb/report nodes are explicitly marked as detail views of the same command/object; route exploration follows drawn edges within each panel.

## Taxonomy and palette

The diagramming skill's craft baseline and complete `atlas-base.css` are copied verbatim, including OS dark mode and explicit light/dark overrides. Its prose lists runtime status meanings, while the canonical CSS actually assigns `--sess` violet, `--host` blue, `--daemon` amber and `--job` green. This document depicts a static contract, so those hues are consciously assigned to **roles**, with an explicit legend saying they do not denote running/completed status. No green completion encoding is used. The legacy architecture schema slots are retained for compatibility and relabelled through its legend; the hand-built renderer maps them to the workflow roles below.

| Workflow role | Color/token | Shape and non-color affordance | Source slot |
|---|---|---|---|
| Process / command | Violet `--sess` | Rounded rectangle, COMMAND label, monospace command name | backend |
| Durable record | Neutral `--nodeline` | Folded document outline, RECORD label | frontend |
| Destination / store | Blue `--host` | Double-edged rectangle, STORE label | database |
| Approval / control | Amber `--daemon` | Diamond, CONTROL label and stated condition | security |
| Source / input | Neutral `--nodeline` | Pill outline, SOURCE INPUT label; primary status stated separately | external |

Every current SVG panel has a role/shape/color legend and line legend. Solid arrows mean read/create/record handoff; dashed arrows mean scoped execution or terminal retention; dotted arrows carry selected PRIMARY evidence. Diagram labels and prose, rather than color, identify authority, pending conditions and primary-versus-synthesis provenance. The deck's wiki relationship illustration separately labels its unarrowed lines as reference links, not execution.

Research retention is `finalize`, not `file-source`: the helper moves terminal research reports from output to excluded raw/derived. Separately authorized `file-source` files original primary transcripts under raw policy. Neither transition creates the report; neither relocates the meeting record. Default research retention is already part of the approved absorption contract; the diagram does not invent another generic approval gate. Existing row authority carries through, and required confirmations remain binding. (validated: absorb finish/retain contract; helper terminal/finalize/file_source)

## Complete node inventory

Each source below was read this pass. Aliases are explicitly named; they are not extra commands or new copies of a source.

| Node ID | Label and role | Source support |
|---|---|---|
| `research-input` | Question + sources — Source / input | `skills/research-sources/SKILL.md:8` |
| `research` | Research capture — Process / command | `skills/research-topic/SKILL.md:30` |
| `report` | Research report — Durable record | `skills/research-topic/SKILL.md:30` |
| `meeting-input` | Meeting inputs — Source / input | `skills/knowledge-capture/references/meetings.md:15` |
| `capture` | meeting-capture — Process / command | `skills/knowledge-capture/references/meetings.md:33` |
| `meeting` | Meeting record — Durable record | `skills/absorb/scripts/distribution.py:131` |
| `approval` | Row authority — Approval / control | `skills/absorb/SKILL.md:29` |
| `absorb` | absorb — Process / command | `skills/absorb/SKILL.md:14` |
| `absorb-detail` | absorb — Process / command | `skills/absorb/SKILL.md:14` |
| `targets` | Local destinations — Destination / store | `skills/absorb/SKILL.md:38` |
| `primary` | Primary raw evidence — Source / input | `skills/wiki-compile/SKILL.md:12` |
| `direct` | Compiler authority — Approval / control | `skills/wiki-compile/SKILL.md:18` |
| `compile` | wiki-compile — Process / command | `skills/wiki-compile/SKILL.md:12` |
| `wiki` | wiki/ — Destination / store | `skills/wiki-compile/SKILL.md:50` |
| `report-retention` | Same research report — Durable record | `skills/absorb/SKILL.md:65` |
| `report-terminal` | All rows terminal — Approval / control | `skills/absorb/scripts/distribution.py:375` |
| `finalize` | finalize — Process / command | `skills/absorb/scripts/distribution.py:451` |
| `derived` | raw/derived/ — Destination / store | `skills/absorb/scripts/distribution.py:459` |
| `transcript` | Original transcript — Source / input | `skills/absorb/SKILL.md:72` |
| `filing-authority` | Terminal + filing — Approval / control | `skills/absorb/SKILL.md:75` |
| `file-source` | file-source — Process / command | `skills/absorb/scripts/distribution.py:443` |
| `source-archive` | Raw source archive — Destination / store | `skills/absorb/SKILL.md:72` |

## Complete edge inventory

All 18 source-model edges have source support below. The renderer attaches each endpoint inside its actual rectangle, pill or diamond; the mechanical checker tests diamonds geometrically rather than treating their whole bounding rectangle as a node. There is no report-as-primary compiler edge.

| Edge ID | Relationship | Source support |
|---|---|---|
| `research-read` | `research-input` → `research`: read | `skills/research-sources/SKILL.md:8` |
| `report-create` | `research` → `report`: create | `skills/research-topic/SKILL.md:30` |
| `meeting-read` | `meeting-input` → `capture`: read | `skills/knowledge-capture/references/meetings.md:15` |
| `meeting-create` | `capture` → `meeting`: create / reuse | `skills/absorb/scripts/distribution.py:156` |
| `report-review` | `report` → `approval`: rows | `skills/absorb/SKILL.md:29` |
| `meeting-review` | `meeting` → `approval`: rows | `skills/absorb/SKILL.md:29` |
| `approved` | `approval` → `absorb`: authorized | `skills/absorb/SKILL.md:29` |
| `local-rows` | `absorb-detail` → `targets`: approved rows | `skills/absorb/SKILL.md:38` |
| `delegate` | `absorb-detail` → `compile`: approved wiki row scope | `skills/absorb/SKILL.md:33` |
| `primary-subset` | `primary` → `compile`: selected PRIMARY evidence | `skills/wiki-compile/SKILL.md:12` |
| `direct-compile` | `direct` → `compile`: direct invocation: no report required | `skills/wiki-compile/SKILL.md:18` |
| `wiki-write` | `compile` → `wiki`: synthesize | `skills/wiki-compile/SKILL.md:50` |
| `report-terminal-check` | `report-retention` → `report-terminal`: check | `skills/absorb/SKILL.md:65` |
| `finalize-report` | `report-terminal` → `finalize`: terminal | `skills/absorb/scripts/distribution.py:453` |
| `retained-report` | `finalize` → `derived`: move + exclude | `skills/absorb/scripts/distribution.py:470` |
| `source-terminal-check` | `transcript` → `filing-authority`: check | `skills/absorb/SKILL.md:75` |
| `file-authorized` | `filing-authority` → `file-source`: authorized | `skills/absorb/SKILL.md:75` |
| `source-retained` | `file-source` → `source-archive`: file original | `skills/absorb/scripts/distribution.py:443` |

The main fan-in now routes both research report and meeting record into row approval and then absorb. Compiler delegation sends scope; the separately selected primary evidence sends content. A direct compiler authority path bypasses absorb and both records. Report and transcript retention each have a terminal/control check and a distinct command/store. The source graph is split into readable panels rather than suggesting a single unconditional chain.

## Whole-artifact sweep and verification

On the MacBook, the final source contains 22 drawn model nodes (including detail aliases) and 18 edges. The image, five workflow slides plus the wiki relationship illustration, architecture graph and three current comparison instances contain 11 current diagrams. All 120 marker arrows across the rendered instances passed endpoint checks; every current diagram has an explicit legend. Category mapping, XML, relative assets/links, source reference bounds and unchanged dated snapshots also passed. (validated: mechanical checker below)

The three README text flows have legends, and the meeting flow now labels input/command/record/store/control roles, approved wiki scope, separate primary input and separate terminal filing. Direct compilation explicitly requires authorized scope. The directory tree and example request blocks are inventories/examples, not extra execution diagrams.

| Surface | Correction / check |
|---|---|
| README image and captions | Both capture outputs, approval, primary evidence, direct compile and distinct retention; misleading ASCII action→compile→filing chain replaced |
| `docs/images/question-answer-action.svg` | Three panels, 22 typed nodes, 18 labelled edges, explicit shape/color/line legend, accessible SVG and canonical palette |
| `docs/presentation.html` | Slides 4–8 share the corrected panels; slide 9 uses store/record shapes and link legend; 11 slides retained; Light/Dark controls added |
| Current architecture source/render | Same semantic model and evidence pinned to 7f47af8; approval gate, correctly directed report input, direct compiler route and distinct archives; prior viewer controls retained |
| Comparison generator/output | Same diagram across current image, README and comparison; unique marker/title IDs; internal scroll wrappers preserve a narrow document while allowing diagram reading; current deck embedded; before snapshots unchanged |
| Historical review material | Dated public-before SVG/README/deck and earlier reports unchanged; native capture and receipt hashes match their round-one values; no admission or evaluator record edited |

Exact checks:

- `gh api repos/coreyfloyd/hippocampus/issues/31` and `gh api repos/coreyfloyd/hippocampus/issues/comments/6088162347`: current primary ticket and comment read; no issue mutation.
- `uv run --with markdown python scripts/render-public-review.py`: exit 0; four generated artifacts remained byte-identical on a subsequent regeneration.
- `python3 /tmp/hippocampus31-diagram-check.py`: exit 0; XML, 11 legends, 120 actual arrow endpoints, node-role consistency, relative assets/links, source references and protected-path diffs passed. Reproducible checker is included below.
- `node /tmp/hippocampus31-deck-navigation.cjs`: exit 0; executes the actual deck script against a DOM stub built from its 11 actual IDs. Keyboard forward and Previous counters pass, including first-slide clamping. This is JavaScript logic evidence, not browser layout evidence.
- `node "$HOME/.codex/skills/archify/bin/archify.mjs" render architecture docs/architecture/runtime.architecture.json /tmp/hippocampus31-architecture-validated.html --quality showcase --repo-root .`: exit 0 on final source. Initial checks caught schema/route/label constraints; corrected them before regenerating the viewer graph. This renderer check is not Archify finalize or isolated evaluator PASS.
- `uv run --with cairosvg python /tmp/hippocampus31-static-raster.py`: exit 0; static light/dark raster inspection with canonical CSS variables resolved into SVG attributes. The rasterizer cannot execute browser CSS/theme/interaction logic. Both palette renders were inspected through the image tool. That static inspection did not establish diamond text containment; the later Chromium measurement below supersedes its label-fit assessment. The first raw CSS raster attempt was transparent; attribute resolution supplied usable static evidence.
- Canonical palette prefix equality, current public artifact private-path scan and absence of external deck scripts/styles: passed.
- `bash tests/test-contracts.sh`: exit 0, including public-path leakage checks.
- `git diff --check`: exit 0.
- `shasum -a 256 docs/implementation/review-r1-4692da10a47bae2dd8b9f35e.txt docs/implementation/review-r1-4692da10a47bae2dd8b9f35e-handoff.json`: unchanged `adfab75aeb91cbb5f9ec77b0c668500ff7bd5dee91aeb4d867c3964e46cfca37` and `da76a950a2276b2b5555fd507949eee7988d934b94146c62c64a5aaba30af992`.

## Post-render label correction

Root's actual Chromium rendering of the SVG embedded in HTML on MacBook, light theme at 1280×1500, exposed title boxes crossing the diamond outlines. The normalized corner test `|dx|/(w/2) + |dy|/(h/2)` exceeded 1 for Row authority (1.03685), Compiler authority (1.16715), All rows terminal (1.16209) and Terminal + filing (1.16209). Root's browser-only scoped 13px rule eliminated all four violations. (validated: root's supplied Chromium `getBBox` measurements and screenshot.)

The shared renderer now emits `[data-workflow-role="control"] .wf-label{font-size:13px}` in every generated workflow diagram. This preserves complete titles and accessible labels while changing only control-title size. The model and node inventory use **Row authority** consistently. Node positions, dimensions, polygon shapes, semantic IDs, source references and all 18 edge routes remain unchanged. The earlier edge-label shortening to **approved rows** is preserved; root confirmed it no longer clips in slide 8. Primary evidence, retention, taxonomy and legends are unchanged.

For this narrow correction, regeneration, the existing mechanical arrow/legend checker and regeneration stability were rerun successfully. The checker validates XML, all 11 current diagram legends and 120 marker-end arrow endpoints against true node shapes, including diamond polygons. A comparison against candidate `501a490` confirms unchanged node geometry and edge routes, and verifies the scoped control-title rule in every generated workflow SVG. These are source and geometry checks; final rendered text containment on this regenerated candidate remains root's browser check. No package/runtime checks were rerun because those files and contracts did not change.

Exact continuation checks on MacBook:

- `uv run --with markdown python scripts/render-public-review.py`: exit 0.
- `python3 /tmp/hippocampus31-diagram-check.py`: exit 0; 22 nodes, 18 edges, 11 legends and 120 marker arrows; protected files unchanged.
- `node /tmp/hippocampus31-deck-navigation.cjs`: exit 0; 11-slide navigation logic unchanged (DOM stub).
- `uv run --with markdown python -` with the assertions below: exit 0; only the model title changed, arrow attributes unchanged, scoped rule present exactly once in all 10 workflow SVGs (the eleventh diagram is the wiki relationship illustration), four generated files byte-stable.
- `git diff --check`: exit 0. Native capture/receipt SHA-256 values remain those listed above.

```python
from pathlib import Path
import hashlib, json, re, subprocess, xml.etree.ElementTree as ET
paths = ['docs/images/question-answer-action.svg', 'docs/presentation.html',
         'docs/architecture/runtime.html', 'docs/reviews/2026-10-09-public-documentation.html']
old = json.loads(subprocess.check_output(['git', 'show',
    '501a490:docs/architecture/runtime.architecture.json'], text=True))
for node in old['components']:
    if node['label'] == 'Row approval': node['label'] = 'Row authority'
assert old == json.loads(Path('docs/architecture/runtime.architecture.json').read_text())
ns = '{http://www.w3.org/2000/svg}'
def arrows(svg):
    return [p.attrib for p in ET.fromstring(svg).iter(ns + 'path') if 'marker-end' in p.attrib]
assert arrows(subprocess.check_output(['git', 'show', '501a490:' + paths[0]], text=True)) == arrows(Path(paths[0]).read_text())
count = 0
for path in paths:
    content = Path(path).read_text()
    for svg in ([content] if path.endswith('.svg') else re.findall(r'<svg\b.*?</svg>', content, re.S)):
        if 'data-workflow-diagram' in svg:
            css = ET.fromstring(svg).find(ns + 'style').text
            assert css.count('[data-workflow-role="control"] .wf-label{font-size:13px}') == 1
            count += 1
assert count == 10
before = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
subprocess.run(['python', 'scripts/render-public-review.py'], check=True)
assert before == {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
```

## Remaining limits and gates

The earlier generator command `uv run --with playwright python /tmp/hippocampus31-visual.py` exited 1 because its sandbox denied Chromium's Mach-port bootstrap (`bootstrap_check_in`, Permission denied 1100). That failure is scoped to the generator sandbox. Root subsequently rendered HTML-embedded SVG successfully on this MacBook; the direct standalone SVG screenshot timed out. Root supplied `/tmp/hippo31-diagram-corrected-light.png`, reported no review JavaScript errors, responsive document width 390/390 and legends on deck slides 7/8. Transitions were disabled only in the QA DOM. (validated: root's supplied browser evidence.)

Root will perform hosted Light/Dark, responsive and full actual browser QA on the final regenerated candidate outside this sandbox. The generator made no further browser launch attempts. Root's successful earlier render established the defects and measured repair; it does not substitute for final-candidate browser verification or maintainer approval.

No native reviewer/evaluator/agent was launched. Independent evaluation remains ESCALATE due the existing transport limitation, not converted to PASS by these root checks. [admin-panel#455](https://github.com/coreyfloyd/admin-panel/issues/455) remains an unapproved separate blocker; [hippocampus#32](https://github.com/coreyfloyd/hippocampus/issues/32) remains a separately filed package-rubric follow-up. Maintainer public-documentation/public-communication approval remains pending. No merge, install, release, publication, live capture/backfill or task write occurred. Other worktrees and historical/native evidence are preserved.

## Reproducible mechanical checker

```python
from pathlib import Path
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
import json,re,subprocess,hashlib
root=Path.cwd();ns='{http://www.w3.org/2000/svg}'
model=json.loads((root/'docs/architecture/runtime.architecture.json').read_text());nodes={n['id']:n for n in model['components']}
class Assets(HTMLParser):
 def __init__(self):super().__init__();self.assets=[];self.base=None
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='base':self.base=a.get('href')
  if tag in ('img','iframe','script','link','a'):
   for k in ['src','href']:
    if a.get(k):self.assets.append(a[k])

def inside(n,x,y):
 nx,ny=n['pos'];w,h=n['size']
 if n['type']=='security':return abs(x-(nx+w/2))/(w/2)+abs(y-(ny+h/2))/(h/2)<=1.00001
 return nx<=x<=nx+w and ny<=y<=ny+h
count=0;diagram_count=0
paths=['docs/images/question-answer-action.svg','docs/presentation.html','docs/architecture/runtime.html','docs/reviews/2026-10-09-public-documentation.html']
for filename in paths:
 text=(root/filename).read_text()
 svgs=[text] if filename.endswith('.svg') else re.findall(r'<svg\b.*?</svg>',text,re.S)
 for svg in svgs:
  # The owned workflow panels and the wiki relationship illustration are XML.
  if 'data-workflow-diagram' not in svg and 'Wiki store links' not in svg:continue
  tree=ET.fromstring(svg);diagram_count+=1
  assert tree.get('role')=='img'
  assert tree.get('aria-label') or tree.get('aria-labelledby')
  assert 'Legend:' in ''.join(tree.itertext())
  for p in tree.iter(ns+'path'):
   if not p.get('marker-end'):continue
   a=p.get('data-edge-from');b=p.get('data-edge-to');assert a in nodes and b in nodes
   numbers=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',p.get('d'))));x,y=numbers[:2];tx,ty=numbers[-2:]
   assert inside(nodes[a],x,y),(filename,a,x,y)
   assert inside(nodes[b],tx,ty),(filename,b,tx,ty)
   count+=1
  for n in tree.iter(ns+'g'):
   if not n.get('data-node-id'):continue
   original=nodes[n.get('data-node-id')]
   expected={'backend':'process','frontend':'record','database':'store','security':'control','external':'input'}[original['type']]
   assert n.get('data-workflow-role')==expected
 if filename.endswith('.html'):
  parser=Assets();parser.feed(text);base=(root/filename).parent
  if parser.base:base=(base/parser.base).resolve()
  for asset in parser.assets:
   if asset.startswith(('http:','https:','data:','#','javascript:')):continue
   asset=asset.split('#')[0].split('?')[0]
   assert (base/asset).exists(),(filename,asset)
# README relative Markdown image/link targets (exclude request examples).
for asset in re.findall(r'\]\(([^)]+)\)',(root/'README.md').read_text()):
 if asset.startswith(('http:','https:','#')):continue
 assert (root/asset.split('#')[0]).exists(),asset
before='docs/reviews/2026-10-09-public-before'
assert not subprocess.check_output(['git','diff','7f47af8','--',before])
assert not subprocess.check_output(['git','diff','7f47af8','--','skills','contracts','profiles','install.sh','tests'])
for n in nodes.values():
 for source in n['sources']:
  lines=(root/source['path']).read_text().splitlines();assert 1<=source['line']<=len(lines)
print(f'PASS: {len(nodes)} typed model nodes; {len(model["connections"])} supported model edges; {diagram_count} current diagrams; {count} marker arrows have both endpoints in actual nodes; legends, role parity, assets and source references valid')
print('PASS: dated before snapshots and all runtime/skills/package behavior files unchanged')
```

## Deck script check (DOM stub, not browser layout)

```javascript
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('docs/presentation.html','utf8');
const ids=[...html.matchAll(/class="slide(?: active)?(?: workflow-slide)?" id="(slide-\d+)"/g)].map(m=>m[1]);
assert.equal(ids.length,11);assert.equal(new Set(ids).size,11);
const slides=ids.map((id,i)=>({id,classList:{active:i===0,add(){this.active=true},remove(){this.active=false}}}));
const elements={prevBtn:{},nextBtn:{},slideCounter:{textContent:'1 / 11'}};const events={};
vm.runInNewContext([...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1],{
 document:{querySelectorAll:()=>slides,getElementById:id=>elements[id]},
 window:{addEventListener:(event,callback)=>events[event]=callback}
});
for(let i=2;i<=11;i++){events.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(elements.slideCounter.textContent,`${i} / 11`);assert(slides[i-1].classList.active);}
for(let i=10;i>=1;i--){elements.prevBtn.onclick();assert.equal(elements.slideCounter.textContent,`${i} / 11`);assert(slides[i-1].classList.active);}
elements.prevBtn.onclick();assert.equal(elements.slideCounter.textContent,'1 / 11');
console.log('PASS: real deck script, 11 parsed slide IDs, keyboard forward and Previous button counters; DOM stub only, no layout/browser claim');
```
