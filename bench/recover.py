"""Rebuild benchmark results from PreDiligence runs already stored in production (no new analysis).
Usage: python3 recover.py bench_truth_2.json results_2.json"""
import json
import sys
import time

import bench

truth = json.load(open(bench.HERE / sys.argv[1]))
out_file = bench.HERE / sys.argv[2]
companies = {c["name"].lower(): c for c in bench.http(f"{bench.APP}/api/companies")}
results = []
for s in truth:
    c = companies.get(s["name"].lower())
    if not c or c["status"] != "done":
        print("no finished run for", s["name"], c and c["status"], flush=True)
        continue
    d = bench.http(f"{bench.APP}/api/runs/{c['run_id']}")
    secs = round((time.mktime(time.strptime(d["run"]["finished_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                  - time.mktime(time.strptime(d["run"]["started_at"][:19], "%Y-%m-%dT%H:%M:%S"))))
    ans = bench.http(f"{bench.APP}/api/runs/{c['run_id']}/ask",
                     {"question": f"Answer these about {s['name']}, one line each, prefixed Q1..Q4, citing [n]. "
                                  f"Say 'unknown' if the evidence does not say.\n{bench.qblock()}"})["answer"]
    pre = {"run_id": c["run_id"], "status": "done", "seconds": secs, "stats": d["run"]["stats"],
           "n_sources": len(d["sources"]), "n_facts": len(d["facts"]), "answer": ans}
    base = bench.run_baseline(s)
    try:
        g = bench.judge(s, pre["answer"], base["answer"])
    except Exception as e:
        print("judge failed for", s["name"], e, flush=True)
        continue
    results.append({"startup": s, "prediligence": dict(pre, grades=g["A"]), "baseline": dict(base, grades=g["B"])})
    json.dump({"summary": {"date": time.strftime("%Y-%m-%d %H:%M")}, "results": results}, open(out_file, "w"), indent=1)
    print("done", s["name"], g, flush=True)
