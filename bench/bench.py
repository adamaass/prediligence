"""Benchmark: Claude alone vs PreDiligence (live web + fact memory) on YC Fall 2026 startups.

Reference answers come from the YC directory record of each startup (bench_truth.json).
Both systems get the same input (name + website) and the same 4 questions; an LLM judge
grades every answer against the reference as correct / wrong / unknown.
Stdlib only, so it runs on any Python 3.
"""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
APP = os.environ.get("APP_URL", "https://prediligence.vercel.app")
MODEL = "claude-sonnet-5-5"
QUESTIONS = [
    "What does the company do (one sentence)?",
    "Which city is the company headquartered in?",
    "Which Y Combinator batch is the company from?",
    "Which industry or sector is it in?",
]
FIELDS = ["one_liner", "location", "batch", "industry"]

for line in (HERE.parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def http(url, body=None, headers=None, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def claude(system, user, max_tokens=1200):
    out = http("https://api.anthropic.com/v1/messages",
               {"model": MODEL, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]},
               {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in out["content"])


def qblock():
    return "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(QUESTIONS))


def run_prediligence(s):
    t0 = time.time()
    run_id = http(f"{APP}/api/analyze", {"name": s["name"], "website": s["website"]})["run_id"]
    while True:
        time.sleep(5)
        d = http(f"{APP}/api/runs/{run_id}")
        if d["run"]["status"] in ("done", "error"):
            break
        if time.time() - t0 > 420:
            break
    secs = round(time.time() - t0)
    ans = http(f"{APP}/api/runs/{run_id}/ask",
               {"question": f"Answer these about {s['name']}, one line each, prefixed Q1..Q4, citing [n]. "
                            f"Say 'unknown' if the evidence does not say.\n{qblock()}"})["answer"]
    return {"run_id": run_id, "status": d["run"]["status"], "seconds": secs, "stats": d["run"]["stats"],
            "n_sources": len(d["sources"]), "n_facts": len(d["facts"]), "answer": ans}


def run_baseline(s):
    t0 = time.time()
    ans = claude("You are a helpful analyst. Answer from your own knowledge only.",
                 f"Startup: {s['name']} ({s['website']})\n{qblock()}\n"
                 "Answer one line each, prefixed Q1..Q4. Say 'unknown' if you do not know.")
    return {"seconds": round(time.time() - t0, 1), "answer": ans}


def judge(s, pre, base):
    for _ in range(3):  # the judge occasionally answers without JSON; retry
        try:
            return _judge(s, pre, base)
        except (AttributeError, ValueError):
            pass
    return _judge(s, pre, base)


def _judge(s, pre, base):
    truth = "\n".join(f"Q{i + 1}: {s[f]}" for i, f in enumerate(FIELDS))
    out = claude("You grade answers against reference answers. Be strict but accept paraphrases and "
                 "equivalent wording (e.g. 'Fall 2026' = 'F26', 'SF' = 'San Francisco'). "
                 "The Q4 reference is a broad YC category (B2B, Consumer, Healthcare...): a more specific "
                 "sector consistent with that category counts as correct. "
                 "Respond with JSON only.",
                 f"Startup: {s['name']}\nREFERENCE:\n{truth}\n\nANSWER A:\n{pre}\n\nANSWER B:\n{base}\n\n"
                 'Return {"A": [4 grades], "B": [4 grades]} where each grade is "correct", "wrong" '
                 '(a confident but incorrect claim) or "unknown" (abstained).', 400)
    return json.loads(re.search(r"\{.*\}", out, re.S).group(0))


def one(s):
    with ThreadPoolExecutor(2) as ex:
        fp, fb = ex.submit(run_prediligence, s), ex.submit(run_baseline, s)
        pre, base = fp.result(), fb.result()
    g = judge(s, pre["answer"], base["answer"])
    lines = [l for l in pre["answer"].splitlines() if re.match(r"\s*\**Q\d", l)]
    cited = sum(bool(re.search(r"\[\d+", l)) for l in lines)
    print(f"done {s['name']}: pre={g['A']} base={g['B']}", flush=True)
    return {"startup": s, "prediligence": dict(pre, grades=g["A"], cited_lines=cited, answer_lines=len(lines)),
            "baseline": dict(base, grades=g["B"])}


if __name__ == "__main__":
    truth = json.load(open(sys.argv[1] if len(sys.argv) > 1 else HERE / "bench_truth.json"))
    out_file = HERE / (sys.argv[2] if len(sys.argv) > 2 else "results.json")
    with ThreadPoolExecutor(int(os.environ.get("BENCH_PARALLEL", "4"))) as ex:
        results = list(ex.map(one, truth))

    def agg(key):
        g = [x for r in results for x in r[key]["grades"]]
        return {"correct": g.count("correct"), "wrong": g.count("wrong"), "unknown": g.count("unknown"), "total": len(g)}

    summary = {"prediligence": agg("prediligence"), "baseline": agg("baseline"),
               "cited_lines": sum(r["prediligence"]["cited_lines"] for r in results),
               "answer_lines": sum(r["prediligence"]["answer_lines"] for r in results),
               "avg_run_seconds": round(sum(r["prediligence"]["seconds"] for r in results) / len(results)),
               "avg_sources": round(sum(r["prediligence"]["n_sources"] for r in results) / len(results)),
               "n_startups": len(results), "model": MODEL, "date": time.strftime("%Y-%m-%d %H:%M")}
    json.dump({"summary": summary, "results": results}, open(out_file, "w"), indent=1)
    print(json.dumps(summary, indent=1))
