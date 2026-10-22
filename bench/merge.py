"""Merge benchmark batches, drop runs whose search returned no sources, and re-grade every
stored answer with the current judge so all startups are scored by the same rule."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import bench

batches = ["results.json", "results_2.json"]
results = [r for b in batches for r in json.load(open(bench.HERE / b))["results"]
           if r["prediligence"]["n_sources"] > 0]
dropped = sum(len(json.load(open(bench.HERE / b))["results"]) for b in batches) - len(results)


def regrade(r):
    g = bench.judge(r["startup"], r["prediligence"]["answer"], r["baseline"]["answer"])
    r["prediligence"]["grades"], r["baseline"]["grades"] = g["A"], g["B"]
    parts = [x for x in re.split(r"\*{0,2}Q\d[.):]", r["prediligence"]["answer"]) if x.strip()][-4:]
    r["prediligence"]["answer_lines"] = len(parts)
    r["prediligence"]["cited_lines"] = sum(bool(re.search(r"\[\d+", x)) for x in parts)
    return r


with ThreadPoolExecutor(4) as ex:
    results = list(ex.map(regrade, results))


def agg(key):
    g = [x for r in results for x in r[key]["grades"]]
    return {"correct": g.count("correct"), "wrong": g.count("wrong"), "unknown": g.count("unknown"), "total": len(g)}


summary = {"prediligence": agg("prediligence"), "baseline": agg("baseline"),
           "cited_lines": sum(r["prediligence"]["cited_lines"] for r in results),
           "answer_lines": sum(r["prediligence"]["answer_lines"] for r in results),
           "avg_run_seconds": round(sum(r["prediligence"]["seconds"] for r in results) / len(results)),
           "avg_sources": round(sum(r["prediligence"]["n_sources"] for r in results) / len(results)),
           "n_startups": len(results), "dropped_failed_runs": dropped, "model": bench.MODEL,
           "date": json.load(open(bench.HERE / "results_2.json"))["summary"]["date"]}
json.dump({"summary": summary, "results": results}, open(bench.HERE / "results_all.json", "w"), indent=1)
print(json.dumps(summary, indent=1))
