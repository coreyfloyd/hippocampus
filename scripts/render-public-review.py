"""Render the dated public-documentation comparison. Run with markdown installed."""
from pathlib import Path
import xml.etree.ElementTree as ET
import markdown
import html

root = Path(__file__).resolve().parents[1]
review = root / 'docs/reviews'
before = review / '2026-10-09-public-before'
css = ET.parse(root / 'docs/images/question-answer-action.svg').getroot().find('{http://www.w3.org/2000/svg}style').text
def rendered(path, before=False):
    text = path.read_text()
    if before:
        text = text.replace('docs/images/question-answer-action.svg', 'docs/reviews/2026-10-09-public-before/question-answer-action.svg')
    return markdown.markdown(text, extensions=['tables','fenced_code'])
extra = '''
article{max-width:1040px;margin:auto;padding:18px}article img{max-width:100%;height:auto}
article h2{margin-top:28px}a{color:var(--host)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--offbg);padding:16px}
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
<section><h2>Current lifecycle</h2>'''+(root/'docs/images/question-answer-action.svg').read_text()+'''
<p class="src">Sources: meeting-capture, absorb, wiki-compile and their shared distribution contract; helper behavior exercised in isolated tests. External workflows are configured adapters.</p></section>
<section>'''+rendered(review/'2026-10-09-public-documentation.md')+'''</section>
<section><h2>README comparison</h2><details open><summary>After: full current README</summary><article>'''+rendered(root/'README.md')+'''</article></details>
<details><summary>Before: full README at ae82e49</summary><article>'''+rendered(before/'README.md',True)+'''</article></details></section>
<section><h2>Referenced image comparison</h2><details open><summary>After</summary><img style="width:100%" src="docs/images/question-answer-action.svg" alt="Current shared capture lifecycle"></details>
<details><summary>Before</summary><img style="width:100%" src="docs/reviews/2026-10-09-public-before/question-answer-action.svg" alt="Prior research lifecycle"></details></section>
<section><h2>Presentation comparison</h2><p>Use the deck's arrow controls to review every slide, including changed slides 5–8.</p>
<details open><summary>After: current presentation</summary><iframe src="docs/presentation.html" title="Current public presentation"></iframe></details>
<details><summary>Before: presentation at ae82e49</summary><iframe src="docs/reviews/2026-10-09-public-before/presentation.html" title="Prior public presentation"></iframe></details></section>
<section><h2>Architecture</h2><p><a href="docs/architecture/runtime.html">Open the regenerated interactive map</a>. Maintainer review remains separate from generator verification.</p></section>
</main></body></html>'''
(review/'2026-10-09-public-documentation.html').write_text(text)
print('Rendered full before/after README, diagram and presentation review')
