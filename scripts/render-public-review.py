"""Render the dated public-documentation comparison. Run with markdown installed."""
from pathlib import Path
import xml.etree.ElementTree as ET
import markdown
import html

root = Path(__file__).resolve().parents[1]
review = root / 'docs/reviews'
before = review / '2026-10-09-public-before'
css = ET.parse(root / 'docs/images/question-answer-action.svg').getroot().find('{http://www.w3.org/2000/svg}style').text

import json
import re
from textwrap import wrap
model = json.loads((root / 'docs/architecture/runtime.architecture.json').read_text())
roles = {'backend':'process','frontend':'record','database':'store','security':'control','external':'input'}
labels = {'process':'COMMAND','record':'RECORD','store':'STORE','control':'CONTROL','input':'SOURCE INPUT'}
panels = {'capture':(130,430),'execution':(480,905),'retention':(975,1345)}
def tag(name, attrs, content=''):
    return '<'+name+' '+ ' '.join(f'{k}="{html.escape(str(v),quote=True)}"' for k,v in attrs.items())+'>'+content+'</'+name+'>'
def text(x,y,value,cls='wf-sub',anchor=None):
    a={'x':x,'y':y,'class':cls}
    if anchor:a['text-anchor']=anchor
    return tag('text',a,html.escape(value))
def shape(role,x,y,w,h):
    attrs={'class':'wf-node wf-'+role}
    if role=='control':
        return tag('path',dict(attrs,d=f'M{x},{y+h/2} L{x+w/2},{y} L{x+w},{y+h/2} L{x+w/2},{y+h} Z'))
    if role=='record':
        return tag('path',dict(attrs,d=f'M{x},{y} L{x+w-16},{y} L{x+w},{y+16} L{x+w},{y+h} L{x},{y+h} Z'))+tag('path',{'d':f'M{x+w-16},{y} L{x+w-16},{y+16} L{x+w},{y+16}','class':'wf-edge'})
    body=tag('rect',dict(attrs,x=x,y=y,width=w,height=h,rx=12 if role=='process' else 20 if role=='input' else 3))
    if role=='store':body+=tag('path',{'d':f'M{x+7},{y+3} V{y+h-3} M{x+w-7},{y+3} V{y+h-3}','class':'wf-node wf-store','fill':'none'})
    return body

def legend(y):
    out=text(30,y,'Legend: workflow roles, not running/completed status','wf-note')
    for x,role,label in [(30,'process','Command'),(255,'record','Durable record'),(500,'store','Destination / store'),(805,'control','Approval / control'),(1050,'input','Source / input')]:
        kind=next(kind for kind,value in roles.items() if value==role)
        out+=tag('g',{'data-legend-kind':kind,'data-legend-semantic-kind':kind,'data-legend-label':label,'data-legend-x':x,'data-legend-baseline':y+29,'data-legend-width':200},shape(role,x,y+12,30,23)+text(x+40,y+29,label,'wf-sub'))
    out+=text(30,y+46,'Shapes/colors: violet rounded = command; neutral fold = record; blue double-edge = store; amber diamond = control; neutral pill = input','wf-edge-label')
    out+=text(30,y+64,'Solid → record / read / create   ·   Dashed → authorized execution or terminal retention   ·   Dotted → selected PRIMARY evidence','wf-note')
    return tag('g',{'data-legend':'','data-legend-bridge':'','aria-label':'Workflow role and line legend'},out)

def workflow_svg(panel=None,prefix='workflow'):
    top,bottom=panels[panel] if panel else (0,1380)
    height=bottom-top+130 if panel else 1380
    out=tag('title',{'id':prefix+'-title'},'Capture creates both records before approved absorption; primary evidence and retention are separate')
    out+=tag('desc',{'id':prefix+'-desc'},'Research reports in output and meeting records in their configured folder carry proposed rows into authority checks and absorb. Wiki compilation reads selected primary evidence and supports direct authorized scope. Terminal research reports are excluded references; separately authorized transcript filing preserves primary sources. Meeting records stay in place.')
    out+=tag('style',{},css)
    out+=tag('defs',{},'<marker id="'+prefix+'-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="var(--dim)"/></marker>')
    out+=tag('rect',{'width':1240,'height':height,'fill':'var(--bg)','rx':12})
    if panel:out+=legend(15)
    else:out+=text(30,33,'Capture → review → approved execution; retention follows terminal rows','wf-heading')+legend(59)
    headings=[('capture',155,'1 · Capture output and row authority'),('execution',485,'2 · Approved routes and independent compiler scope'),('retention',965,'3 · Separate retention transitions after distribution')]
    content=''
    for key,y,title in headings:
        if panel is None or panel==key:content+=text(30,y,title,'wf-heading')
    nodes=[n for n in model['components'] if not panel or top<=n['pos'][1]<bottom]
    ids={n['id'] for n in nodes}
    label_at={'research-read':(232,213),'report-create':(500,213),'meeting-read':(232,358),'meeting-create':(500,358),'report-review':(779,247),'meeting-review':(779,352),'approved':(961,283),'local-rows':(255,545),'delegate':(380,628),'primary-subset':(375,718),'direct-compile':(554,855),'wiki-write':(963,718),'report-terminal-check':(276,1032),'finalize-report':(545,1032),'retained-report':(846,1032),'source-terminal-check':(276,1207),'file-authorized':(540,1207),'source-retained':(853,1207)}
    for e in model['connections']:
        if e['from'] not in ids or e['to'] not in ids:continue
        source=next(n for n in model['components'] if n['id']==e['from'])
        target=next(n for n in model['components'] if n['id']==e['to'])
        sx,sy=source['pos'];sw,sh=source['size'];tx,ty=target['pos'];tw,th=target['size']
        ports={'right':[sx+sw-1,sy+sh/2],'left':[sx+1,sy+sh/2],'top':[sx+sw/2,sy+1],'bottom':[sx+sw/2,sy+sh-1]}
        target_ports={'right':[tx+tw-1,ty+th/2],'left':[tx+1,ty+th/2],'top':[tx+tw/2,ty+1],'bottom':[tx+tw/2,ty+th-1]}
        pts=[ports[e.get('fromSide','right')],*e['via'],target_ports[e.get('toSide','left')]]
        d='M'+' L'.join(f'{x},{y}' for x,y in pts)
        attrs={'d':d,'class':'wf-edge '+e.get('variant','default'),'marker-end':f'url(#{prefix}-arrow)','data-edge-from':e['from'],'data-edge-to':e['to'],'data-edge-key':e['id']}
        content+=tag('g',{'data-edge-from':e['from'],'data-edge-to':e['to'],'data-edge-key':e['id']},tag('path',attrs)+tag('title',{},html.escape(e['label'])))
        x,y=label_at[e['id']]
        label='rows' if e['id'].endswith('-review') else 'create' if e['id']=='meeting-create' else e['label']
        content+=text(x,y,label,'wf-edge-label')
    for n in nodes:
        x,y=n['pos'];w,h=n['size'];role=roles[n['type']]
        body=shape(role,x,y,w,h)
        if role=='control':
            body+=text(x+w/2,y+h/2-30,labels[role],'wf-tag','middle')+text(x+w/2,y+h/2-5,n['label'],'wf-label','middle')
            for i,line in enumerate(wrap(n['sublabel'],19)):body+=text(x+w/2,y+h/2+15+i*14,line,'wf-sub','middle')
        else:
            body+=text(x+16,y+21,labels[role],'wf-tag')+text(x+16,y+46,n['label'],'wf-label')
            for i,line in enumerate(wrap(n['sublabel'],int((w-32)/6.3),break_long_words=False,break_on_hyphens=False)):body+=text(x+16,y+66+i*14,line,'wf-sub')
        content+=tag('g',{'id':'node-'+n['id'],'data-node-id':n['id'],'data-node-kind':n['type'],'data-node-label':n['label'],'data-node-sublabel':n['sublabel'],'data-node-context':labels[role],'data-workflow-role':role,'data-bounds':f'{x},{y},{w},{h}','tabindex':'0' if prefix=='architecture' else '-1','role':'button' if prefix=='architecture' else 'group','aria-label':labels[role]+': '+n['label']+'; '+n['sublabel'],'aria-pressed':'false'},body)
    notes=[(435,'Both records carry proposed rows. Existing authority carries through; pending facts or uncovered scope block execution.'),(915,'Compiler scope may come from absorb or a direct authorized request. Reports are synthesis, never primary compiler evidence.'),(1320,'Meeting record: same path after processing. Repeated nodes show the same command/object in a detail panel.'),(1342,'Primary transcript archive ≠ excluded report archive. Pending rows retain intake/output; ingestion status is separate.')]
    for y,value in notes:
        if panel is None or top<=y<=bottom:content+=text(30,y,value,'wf-note')
    if panel:out+=tag('g',{'transform':f'translate(0,{100-top})'},content)
    else:out+=content
    return tag('svg',{'xmlns':'http://www.w3.org/2000/svg','viewBox':f'0 0 1240 {height}','role':'img','aria-labelledby':prefix+'-title '+prefix+'-desc','data-preset':'classic','data-reader-fit':'intrinsic-height','data-reader-min-text':'11','data-reader-primary-text':'16','data-workflow-diagram':panel or 'all'},out)

(root/'docs/images/question-answer-action.svg').write_text(workflow_svg()+'\n')
# The source and hand-built SVG share one model. Preserve the existing viewer
# controls; replace its diagram, not its interaction implementation.
architecture=root/'docs/architecture/runtime.html'
page=architecture.read_text()
page,count=re.subn(r'<svg (?=[^>]*(?:data-workflow-diagram="all"|aria-labelledby="archify-diagram-title))[^>]*>.*?</svg>',lambda _:workflow_svg(prefix='architecture'),page,count=1,flags=re.S)
if count!=1:raise ValueError('architecture viewer must contain one primary SVG')
page=page.replace('Hippocampus: capture, approved absorption and retention',model['meta']['title'])
revision=model['meta']['repository']['revision']
repository={'url':'https://github.com/coreyfloyd/hippocampus','revision':revision,'shortRevision':revision[:7],'label':'coreyfloyd/hippocampus','href':'https://github.com/coreyfloyd/hippocampus/tree/'+revision}
evidence={'schemaVersion':1,'verified':True,'repository':repository,'referenceCount':sum(len(n['sources']) for n in model['components']),'nodes':{}}
for n in model['components']:
    evidence['nodes'][n['id']]=[dict(ref,href=repository['url']+'/blob/'+revision+'/'+ref['path']+'#L'+str(ref['line'])) for ref in n['sources']]
page=re.sub(r'(<script id="archify-source-evidence-data" type="application/json">).*?(</script>)',lambda m:m[1]+json.dumps(evidence,separators=(',',':'))+m[2],page,count=1,flags=re.S)
# Cards explain scope, rather than reintroducing deployment or completion colors.
card_html='<div class="cards">'+''.join('<div class="card"><h3>'+html.escape(card['title'])+'</h3><ul>'+''.join('<li>'+html.escape(item)+'</li>' for item in card['items'])+'</ul></div>' for card in model['cards'])+'</div>'
page=re.sub(r'<div class="cards">.*?(?=\n    <nav class="node-outline)',lambda _:card_html,page,count=1,flags=re.S)
architecture.write_text(page)
# Replace complete current workflow visuals, leaving all dated before files intact.
deck=root/'docs/presentation.html';page=deck.read_text()
for number,panel,title,message in [(4,'capture','Capture Creates a Plan, Before Any Execution','Research creates a report in output. Meeting capture creates its record directly in the configured folder. Both feed scoped absorption.'),(5,'capture','Different Inputs, the Same Approval Boundary','A question or supplied research sources and independent meeting inputs create distinct source-linked records. Capture does not authorize target writes.'),(6,'execution','Primary Evidence Stays Separate from Synthesis','Wiki rows delegate selected primary evidence. Direct wiki-compile is also available when its scope is authorized; generated reports are not compiler evidence.'),(7,'retention','Processing Does Not Relocate a Meeting Record','Research finalize retains a terminal report as an excluded reference. Separately authorized file-source retains original transcripts under raw policy.'),(8,'execution','Execute Approved Rows Through Their Workflows','Named docs, context, projects, owned tasks and writing use local rules. Confirmed receipts support retries; pending routes remain in the record.')]:
    replacement=f'<div class="slide workflow-slide" id="slide-{number}"><div><h2>{title}</h2><p class="message">{message}</p></div><div class="scroll workflow-visual">'+workflow_svg(panel,prefix='slide'+str(number))+'</div><p class="src">source: shared distribution contract, absorb, wiki-compile and capture helpers. Workflow contract, not production status.</p></div>\n\n'
    page,count=re.subn(r'<div class="slide(?: active)?(?: workflow-slide)?" id="slide-'+str(number)+r'".*?(?=    <!-- Slide '+str(number+1)+r':)',lambda _:replacement,page,count=1,flags=re.S)
    if count!=1:raise ValueError('missing slide '+str(number))
# Wiki retrieval illustration uses typed store/record shapes and a relationship legend.
match=re.search(r'<svg viewBox="0 0 460 (?:250|280|300)".*?</svg>',page,re.S)
if not match:raise ValueError('missing wiki link diagram')
start,end=match.span()
wiki_svg='<svg viewBox="0 0 460 300" role="img" aria-label="Wiki store links compiled records; these are reference links, not execution"><style>'+css+'</style>'+shape('store',180,105,110,80)+text(196,129,'STORE','wf-tag')+text(196,154,'wiki/','wf-label')
for x,y,name in [(15,30,'topic.md'),(320,30,'_index.md'),(15,200,'sources.md'),(320,200,'hot.md')]:
    wiki_svg+=tag('line',{'x1':235,'y1':145,'x2':x+55,'y2':y+30,'class':'wf-edge'})+shape('record',x,y,125,60)+text(x+12,y+23,'RECORD','wf-tag')+text(x+12,y+45,name,'wf-sub')
wiki_svg+=text(15,275,'Legend: blue double-edge = store; neutral fold = record','wf-sub')+text(15,291,'Lines = reference links, not execution; wiki is optional','wf-sub')+'</svg>'
page=page[:start]+wiki_svg+page[end:]
# The deck shares the canonical palette; introductory prose remains unchanged.
if 'Static workflow roles:' not in page:page=page.replace('  <style>','  <style>\n'+css+'\n',1)
page=page.replace('body {\n      background: #0f1215;','body {\n      background: var(--bg);')
if not page.startswith('<meta charset='):page='<meta charset="utf-8">\n'+page
page=re.sub(r'    :root \{\n      --bg: #1c2024;.*?\n    \}', '''    :root {--cyan:var(--host);--cyan-glow:transparent;--tangerine:var(--daemon);--tangerine-glow:transparent;--emerald:var(--host);--emerald-glow:transparent;--crimson:var(--hot);--crimson-glow:transparent;}''',page,count=1,flags=re.S)
deck.write_text(page)
def rendered(path, before=False):
    text = path.read_text()
    if before:
        text = text.replace('docs/images/question-answer-action.svg', 'docs/reviews/2026-10-09-public-before/question-answer-action.svg')
    rendered = markdown.markdown(text, extensions=['tables','fenced_code'])
    if not before:
        rendered = re.sub(r'<img[^>]+src="docs/images/question-answer-action.svg"[^>]*>', lambda _:'<div class="scroll">'+workflow_svg(prefix='readme-review')+'</div>', rendered)
    return rendered
extra = '''
article{max-width:1040px;margin:auto;padding:18px}article img{max-width:100%;height:auto}
.scroll{max-width:100%}.scroll svg{min-width:950px}section table{display:block;overflow-x:auto}article h2{margin-top:28px}a{color:var(--host)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--offbg);padding:16px}
summary{cursor:pointer;font-size:18px;font-weight:600;padding:12px}.notice{border:2px solid var(--warn);padding:16px;border-radius:10px}
iframe{width:100%;height:720px;border:1px solid var(--line);border-radius:12px;background:var(--bg)}
button{padding:8px 16px;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px}
'''
text = '''<meta charset="utf-8">
<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1">
<base href="../../"><title>Capture and absorption: public documentation candidate</title><style>'''+css+extra+'''</style></head>
<body><main class="wrap"><h1>Capture, absorption and writing</h1>
<p class="notice">Candidate review · Public-communication approval pending. No release or publication approved.</p>
<button onclick="document.documentElement.dataset.theme='light'">Light</button>
<button onclick="document.documentElement.dataset.theme='dark'">Dark</button>
<section><h2>Current lifecycle</h2><div class="scroll">'''+workflow_svg(prefix='review-current')+'''</div>
<p class="src">Sources: meeting-capture, absorb, wiki-compile and their shared distribution contract; helper behavior exercised in isolated tests. External workflows are configured adapters.</p></section>
<section>'''+rendered(review/'2026-10-09-public-documentation.md')+'''</section>
<section><h2>README comparison</h2><details open><summary>After: full current README</summary><article>'''+rendered(root/'README.md')+'''</article></details>
<details><summary>Before: full README at ae82e49</summary><article>'''+rendered(before/'README.md',True)+'''</article></details></section>
<section><h2>Referenced image comparison</h2><details open><summary>After</summary><div class="scroll">'''+workflow_svg(prefix='comparison-after')+'''</div></details>
<details><summary>Before</summary><img style="width:100%" src="docs/reviews/2026-10-09-public-before/question-answer-action.svg" alt="Prior research lifecycle"></details></section>
<section><h2>Presentation comparison</h2><p>Use the deck's arrow controls to review every slide, including corrected workflow slides 4–9.</p>
<details open><summary>After: current presentation</summary><iframe src="docs/presentation.html" title="Current public presentation"></iframe></details>
<details><summary>Before: presentation at ae82e49</summary><iframe src="docs/reviews/2026-10-09-public-before/presentation.html" title="Prior public presentation"></iframe></details></section>
<section><h2>Architecture</h2><p><a href="docs/architecture/runtime.html">Open the regenerated interactive map</a>. Maintainer review remains separate from generator verification.</p></section>
</main></body></html>'''
(review/'2026-10-09-public-documentation.html').write_text(text)
print('Rendered full before/after README, diagram and presentation review')
