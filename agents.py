"""Scout's agent pipeline: Planner -> Search -> Extract -> Verify -> Memo.

Every stage reads from / writes to Aiven Postgres, so each run builds on the facts
remembered from previous runs (that is how stale data and changes are detected).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date

import httpx

import db
import keenable

MODEL = os.environ.get("SCOUT_MODEL", "claude-sonnet-5-5")
CATEGORIES = ["Status", "Funding", "Team", "Product", "Traction", "Competition"]
STAGES = ["Planner", "Search", "Extract", "Verify", "Memo"]


# ---------------------------------------------------------------- LLM helper
async def llm(client: httpx.AsyncClient, system: str, user: str, max_tokens: int = 4000) -> dict:
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    body = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system + "\nRespond with a single JSON object only. No prose, no markdown fences.",
        "messages": [{"role": "user", "content": user}],
    }
    r = await client.post("https://api.anthropic.com/v1/messages", json=body, headers=headers, timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"LLM error {r.status_code}: {r.text[:300]}")
    text = "".join(b.get("text", "") for b in r.json()["content"])
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


# ---------------------------------------------------------------- stages
async def plan(client, name: str, website: str | None) -> list[dict]:
    today = date.today().isoformat()
    try:
        out = await llm(client,
            "You are the research planner of a VC due-diligence agent. Write web search queries that "
            "describe the ideal page (natural language, not keywords).",
            f"Startup: {name}\nWebsite: {website or 'unknown'}\nToday: {today}\n"
            "Return {\"queries\": [6 strings]} covering: founders & backgrounds, funding rounds & investors, "
            "product & customers, competitors, recent news incl. acquisition/shutdown/pivot, traction metrics.",
            max_tokens=800)
        queries = [{"query": s} for s in out["queries"][:6]]
    except Exception:
        queries = [{"query": f"{name} startup {t}"} for t in
                   ("founders background", "funding round investors", "product customers",
                    "competitors alternatives", "acquired news announcement", "revenue ARR growth")]
    queries.append({"query": f"{name} announcement", "site": "x.com"})
    dom = keenable.domain(website)
    if dom:
        queries.append({"query": f"{name} blog news announcement", "site": dom})
    return queries


async def search_all(client, queries: list[dict]) -> list[dict]:
    results = await asyncio.gather(*[
        keenable.search(client, q["query"], max_results=6, site=q.get("site")) for q in queries])
    seen, pages = set(), []
    for batch in results:
        for p in batch:
            url = p.get("url", "").split("#")[0].rstrip("/")
            if url and url not in seen:
                seen.add(url)
                pages.append(p)
    return pages


def sources_block(sources: list[dict]) -> str:
    return "\n\n".join(
        f"[{s['n']}] {s['title']} | {s['url']} | type={s['source_type']} | published={s['published_at'] or '?'} "
        f"| fetched={s['acquired_at'] or '?'}{' | FROM MEMORY' if s.get('from_memory') else ''}\n{(s['snippet'] or '')[:900]}"
        for s in sources)


async def extract(client, name: str, sources: list[dict]) -> list[dict]:
    out = await llm(client,
        "You extract atomic, checkable facts about one startup from web sources for a VC. "
        "Only use what the sources say. Every fact must cite source numbers. Ignore pages about other companies.",
        f"Startup: {name}\n\nSOURCES:\n{sources_block(sources)}\n\n"
        f"Return {{\"facts\": [{{\"category\": one of {CATEGORIES}, \"claim\": short factual sentence, "
        "\"sources\": [source numbers]}}]}. Extract 15-35 facts. Keep conflicting claims as separate facts "
        "(e.g. different funding totals, 'Active' vs 'Acquired'). Include company status (active/acquired/shut down).",
        max_tokens=5000)
    return [f for f in out.get("facts", []) if f.get("sources")]


async def verify(client, name: str, sources: list[dict], facts: list[dict], memory: list[dict]) -> dict:
    mem = "\n".join(f"- [{m['category']}] {m['claim']} (status={m['status']}, sources={m['source_ns']}, "
                    f"remembered from run #{m['run_id']})" for m in memory) or "(no previous run)"
    new = "\n".join(f"{i}. [{f['category']}] {f['claim']} (sources={f['sources']})" for i, f in enumerate(facts))
    return await llm(client,
        "You are the verification agent of a VC diligence tool. You cross-check facts across sources and against memory.\n"
        "Trust ranking: primary (company-owned site/blog, official launch post) > press > social > web > database "
        "(databases like YC directory, Tracxn, PitchBook are often stale). A newer primary source overrides older databases. "
        "Company-reported metrics are 'reported'. Pages written by a competitor are 'biased'.",
        f"Startup: {name}\nToday: {date.today().isoformat()}\n\nSOURCES:\n{sources_block(sources)}\n\n"
        f"NEW FACTS:\n{new}\n\nMEMORY (facts from previous runs):\n{mem}\n\n"
        "Return JSON:\n"
        "{\"facts\": [{\"i\": index of new fact, \"status\": confirmed|conflict|stale|single|reported|biased, "
        "\"confidence\": 0-1, \"note\": optional short reason}],\n"
        " \"merged\": [indices of duplicate facts to drop],\n"
        " \"conflicts\": [{\"question\": e.g. 'How much has X raised?', \"facts\": [indices], \"verdict\": one sentence resolution or best guess}],\n"
        " \"changes\": [{\"field\": category, \"before\": value in memory or '—', \"after\": new value, \"sources\": [n], \"level\": red|amber|gray}],\n"
        " \"alert\": null or {\"title\": critical finding e.g. acquisition/shutdown, \"body\": one sentence with [n] citations}}\n"
        "Rules: confirmed = 2+ independent sources agree. stale = superseded by newer/more trustworthy info. "
        "conflict = sources disagree and it is unresolved. single = one source only. "
        "changes: only real differences vs memory; if memory is empty, return []. Max 4 conflicts.",
        max_tokens=5000)


async def write_memo(client, name: str, sources: list[dict], facts: list[dict], verdicts: dict) -> dict:
    fl = "\n".join(f"- [{f['category']}] {f['claim']} | status={f['status']} | conf={f['confidence']:.2f} | sources={f['source_ns']}"
                   + (f" | note={f['note']}" if f.get('note') else '') for f in facts)
    src = "\n".join(f"[{s['n']}] {s['title']} ({s['source_type']}, fetched {s['acquired_at'] or '?'})" for s in sources)
    return await llm(client,
        "You write one-page pre-call investment memos for early-stage VCs, in the style of Bessemer memos: crisp, skeptical, factual.",
        f"Startup: {name}\n\nVERIFIED FACTS:\n{fl}\n\nSOURCES:\n{src}\n\n"
        f"CONFLICTS:\n{json.dumps(verdicts.get('conflicts', []))}\n\n"
        "Return {\"tagline\": one line, \"sections\": [{\"h\": \"Summary\"|\"Team\"|\"Product\"|\"Traction\"|\"Market & competition\", "
        "\"body\": 2-4 sentences}], \"recommendation\": \"Take the call\"|\"Dig deeper\"|\"Pass\", "
        "\"questions\": [5 sharp questions for the founder, aimed at the conflicts and gaps]}.\n"
        "Cite sources inline as [n] right after each claim. Never state stale facts as true. "
        "Flag self-reported numbers and biased sources. Use only the facts above.",
        max_tokens=3000)


# ---------------------------------------------------------------- orchestration
def set_stage(run_id: int, stage: int, **stats):
    db.q("UPDATE runs SET stage=%s, stats = stats || %s WHERE id=%s", (stage, db.jsonb(stats), run_id))


async def run_pipeline(run_id: int, company: dict):
    name, website = company["name"], company["website"]
    try:
        async with httpx.AsyncClient() as client:
            # Memory: facts + sources from the latest finished run of this company
            prev = db.q("SELECT id FROM runs WHERE company_id=%s AND status='done' AND id<>%s ORDER BY id DESC LIMIT 1",
                        (company["id"], run_id), one=True)
            memory, mem_sources = [], []
            if prev:
                memory = db.q("SELECT * FROM facts WHERE run_id=%s AND status<>'stale'", (prev["id"],))
                cited = sorted({n for m in memory for n in (m["source_ns"] or [])})
                if cited:
                    mem_sources = db.q("SELECT * FROM sources WHERE run_id=%s AND n = ANY(%s) ORDER BY n", (prev["id"], cited))

            set_stage(run_id, 0)
            queries = await plan(client, name, website)
            set_stage(run_id, 1, queries=len(queries))

            pages = await search_all(client, queries)
            dom = keenable.domain(website)
            sources, n_of_url = [], {}
            for s in mem_sources:  # remembered sources keep a stable number in the new run
                n = len(sources) + 1
                n_of_url[s["url"]] = n
                sources.append(dict(s, n=n, from_memory=True, old_n=s["n"]))
            for p in pages:
                url = p["url"]
                if url in n_of_url:
                    continue
                n = len(sources) + 1
                n_of_url[url] = n
                sources.append({"n": n, "url": url, "title": p.get("title"), "snippet": p.get("snippet") or p.get("description"),
                                "published_at": (p.get("published_at") or "")[:10] or None,
                                "acquired_at": (p.get("acquired_at") or "")[:10] or None,
                                "source_type": keenable.source_type(url, dom), "query": p.get("query"), "from_memory": False})
            for s in sources:
                db.q("""INSERT INTO sources (run_id, n, url, title, snippet, published_at, acquired_at, source_type, query, from_memory)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (run_id, s["n"], s["url"], s["title"], s["snippet"], s["published_at"], s["acquired_at"],
                      s["source_type"], s.get("query"), s["from_memory"]))
            # Remap memory facts onto the new source numbers
            old_to_new = {s["old_n"]: s["n"] for s in sources if s.get("from_memory")}
            for m in memory:
                m["source_ns"] = [old_to_new[n] for n in (m["source_ns"] or []) if n in old_to_new]
            set_stage(run_id, 2, pages=len(sources), memory_sources=len(mem_sources))

            raw = await extract(client, name, sources)
            set_stage(run_id, 3, facts=len(raw))

            v = await verify(client, name, sources, raw, memory)
            drop = set(v.get("merged") or [])
            by_i = {f.get("i"): f for f in v.get("facts", [])}
            facts = []
            for i, f in enumerate(raw):
                if i in drop:
                    continue
                vf = by_i.get(i, {})
                fact = {"category": f["category"], "claim": f["claim"],
                        "source_ns": [int(n) for n in f["sources"] if str(n).isdigit() and int(n) in n_of_url.values()],
                        "status": vf.get("status", "single"), "confidence": float(vf.get("confidence", 0.5)),
                        "note": vf.get("note"), "i": i}
                facts.append(fact)
                fact["id"] = db.q("""INSERT INTO facts (company_id, run_id, category, claim, source_ns, status, confidence, note)
                                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                                  (company["id"], run_id, fact["category"], fact["claim"], fact["source_ns"],
                                   fact["status"], fact["confidence"], fact["note"]), one=True)["id"]
            idx = {f["i"]: k for k, f in enumerate(facts)}
            conflicts = [dict(c, facts=[idx[i] for i in c.get("facts", []) if i in idx]) for c in v.get("conflicts", [])]
            n_conf = sum(f["status"] == "conflict" for f in facts)
            n_stale = sum(f["status"] == "stale" for f in facts)
            set_stage(run_id, 4, facts=len(facts), conflicts=len(conflicts), stale=n_stale, conflict_facts=n_conf)

            memo = await write_memo(client, name, sources, facts, v)
            memo.update(conflicts=conflicts, changes=v.get("changes", []), alert=v.get("alert"),
                        prev_run=prev["id"] if prev else None)
            db.q("INSERT INTO memos (run_id, content) VALUES (%s, %s)", (run_id, db.jsonb(memo)))
            db.q("UPDATE runs SET stage=5, status='done', finished_at=now() WHERE id=%s", (run_id,))
            db.q("UPDATE companies SET last_checked_at=now() WHERE id=%s", (company["id"],))
    except Exception as e:  # surface the error in the UI instead of hanging
        db.q("UPDATE runs SET status='error', error=%s, finished_at=now() WHERE id=%s", (str(e)[:500], run_id))
        raise


async def ask(run_id: int, question: str) -> dict:
    facts = db.q("SELECT category, claim, status, source_ns FROM facts WHERE run_id=%s", (run_id,))
    sources = db.q("SELECT n, title, url, source_type, acquired_at, snippet FROM sources WHERE run_id=%s ORDER BY n", (run_id,))
    async with httpx.AsyncClient() as client:
        return await llm(client,
            "You answer a VC's follow-up question about a startup using ONLY the stored facts and sources. "
            "Cite [n] after each claim. If the evidence is insufficient, say so.",
            "FACTS:\n" + "\n".join(f"- [{f['category']}] {f['claim']} ({f['status']}, sources {f['source_ns']})" for f in facts)
            + "\n\nSOURCES:\n" + sources_block([dict(s, published_at=None) for s in sources])
            + f"\n\nQUESTION: {question}\n\nReturn {{\"answer\": \"2-5 sentences with [n] citations\"}}",
            max_tokens=1200)
