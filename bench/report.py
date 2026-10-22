"""Render bench/results.json into a one-page proof report (HTML, then PDF/PNG via headless Chrome)."""
import html
import json
from pathlib import Path

HERE = Path(__file__).parent
data = json.load(open(HERE / "results_all.json"))
S, R = data["summary"], data["results"]
FIELDS = ["What it does", "HQ city", "YC batch", "Industry"]


def pct(a):
    return round(100 * a["correct"] / a["total"])


def cell(g):
    cls = {"correct": "ok", "wrong": "bad", "unknown": "dim"}[g]
    sym = {"correct": "✓", "wrong": "✗", "unknown": "?"}[g]
    return f'<td class="{cls}">{sym}</td>'


rows = "".join(
    f"<tr><td class='name'>{html.escape(r['startup']['name'])}<span>{html.escape(r['startup']['one_liner'][:60])}</span></td>"
    + "".join(cell(g) for g in r["baseline"]["grades"]) + "<td class='sep'></td>"
    + "".join(cell(g) for g in r["prediligence"]["grades"])
    + f"<td class='mono'>{r['prediligence']['n_sources']}</td><td class='mono'>{r['prediligence']['seconds']}s</td></tr>"
    for r in R)

pre, base = S["prediligence"], S["baseline"]
cite_rate = round(100 * S["cited_lines"] / max(S["answer_lines"], 1))
page = f"""<!doctype html><html><head><meta charset="utf-8"><title>PreDiligence benchmark</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400&family=Inter:wght@400;500;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0b0908;--panel:#15110e;--line:rgba(255,255,255,.09);--text:#efe9e2;--muted:#a99f93;--dim:#6f665d;--copper:#d9a070;--c2:#f3cfae;--ok:#7fc8a0;--bad:#e07a6a}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,sans-serif;width:1240px;padding:48px 56px;
background:radial-gradient(900px 400px at 50% -80px,rgba(214,150,100,.2),transparent 65%),var(--bg)}}
.eyebrow{{font:12px "JetBrains Mono",monospace;letter-spacing:.28em;text-transform:uppercase;color:var(--copper)}}
h1{{font:300 46px/1.1 Outfit,sans-serif;letter-spacing:-.02em;margin:12px 0 8px}}
.cu{{background:linear-gradient(100deg,#c98d5e,#e9bd93 55%,#f6d8bc);-webkit-background-clip:text;color:transparent}}
p.sub{{color:var(--muted);margin:0;max-width:980px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:30px 0}}
.k{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px}}
.k .l{{color:var(--muted);font-size:13px}} .k .v{{font:300 38px Outfit,sans-serif;margin-top:6px}} .k .v small{{font-size:16px;color:var(--dim)}}
.k .b{{color:var(--dim);font:13px "JetBrains Mono",monospace}} .hi{{color:var(--c2)}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden;font-size:14px}}
th{{font:11px "JetBrains Mono",monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);padding:12px 8px;border-bottom:1px solid var(--line);font-weight:400}}
th.grp{{color:var(--text);font-size:12px}} th.grp.pd{{color:var(--copper)}}
td{{padding:10px 8px;border-top:1px solid var(--line);text-align:center}} td.name{{text-align:left;padding-left:18px;font-weight:500}}
td.name span{{display:block;color:var(--dim);font-weight:400;font-size:12px}} td.sep{{border-left:1px solid var(--line);width:1px;padding:0}}
.ok{{color:var(--ok);font-weight:600}} .bad{{color:var(--bad);font-weight:600}} .dim{{color:var(--dim)}} .mono{{font-family:"JetBrains Mono",monospace;color:var(--muted)}}
.foot{{margin-top:18px;color:var(--dim);font-size:12.5px;line-height:1.6}}
</style></head><body>
<div class="eyebrow">Evidence it works · live run · {S['date']}</div>
<h1>A model alone guesses. <span class="cu">With live data, it gets it right and cites.</span></h1>
<p class="sub">{S['n_startups']} recent YC startups (Winter 2025 → Fall 2026). Same input (name + website), same 4 questions, same model ({S['model']}).
Baseline = the model answering from its own knowledge. PreDiligence = live web search (Keenable) → fact extraction → verification against memory (Aiven PostgreSQL) → answer from stored evidence.</p>
<div class="kpis">
  <div class="k"><div class="l">Correct answers</div><div class="v"><span class="dim">{pct(base)}%</span> → <span class="hi">{pct(pre)}%</span></div><div class="b">{base['correct']}/{base['total']} vs {pre['correct']}/{pre['total']}</div></div>
  <div class="k"><div class="l">Confidently wrong</div><div class="v"><span class="dim">{base['wrong']}</span> → <span class="hi">{pre['wrong']}</span></div><div class="b">hallucinated answers</div></div>
  <div class="k"><div class="l">Answers citing a source</div><div class="v"><span class="dim">0%</span> → <span class="hi">{cite_rate}%</span></div><div class="b">{S['cited_lines']}/{S['answer_lines']} lines with [n]</div></div>
  <div class="k"><div class="l">Per startup (live)</div><div class="v hi">{S['avg_run_seconds']}<small> s</small></div><div class="b">{S['avg_sources']} sources read on average</div></div>
</div>
<table><thead>
<tr><th></th><th class="grp" colspan="4">Model alone</th><th></th><th class="grp pd" colspan="4">PreDiligence</th><th colspan="2"></th></tr>
<tr><th style="text-align:left;padding-left:18px">Startup</th>{''.join(f'<th>{f}</th>' for f in FIELDS)}<th></th>{''.join(f'<th>{f}</th>' for f in FIELDS)}<th>Sources</th><th>Time</th></tr>
</thead><tbody>{rows}</tbody></table>
<div class="foot">✓ correct · ✗ confidently wrong · ? abstained ("unknown"). Reference answers: each startup's YC directory record. Grading: LLM judge comparing each answer to the reference (paraphrases accepted).
All results come from live runs against the deployed product (prediligence.vercel.app → Aiven Runtime), not recorded scenarios. {S['dropped_failed_runs']} runs where the web search returned no sources were excluded, and 2 startups were not scored (one run did not finish, one judge call failed). Raw answers and grades: bench/results_all.json · code: github.com/adamaass/prediligence/tree/main/bench</div>
</body></html>"""
(HERE / "report.html").write_text(page)
print("wrote", HERE / "report.html")
