"""Scout API: live, sourced diligence memos for early-stage VCs."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import agents  # noqa: E402
import db  # noqa: E402

app = FastAPI(title="Scout")
STATIC = Path(__file__).parent / "static"
_tasks: set = set()


@app.on_event("startup")
def startup():
    db.init()


class AnalyzeIn(BaseModel):
    name: str
    website: Optional[str] = None


class AskIn(BaseModel):
    question: str


@app.get("/")
def landing():
    return FileResponse(STATIC / "landing.html")


@app.get("/app")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/analyze")
async def analyze(body: AnalyzeIn):
    company = db.upsert_company(body.name, body.website or None)
    run = db.q("INSERT INTO runs (company_id) VALUES (%s) RETURNING id", (company["id"],), one=True)
    task = asyncio.create_task(agents.run_pipeline(run["id"], company))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"run_id": run["id"]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = db.q("SELECT * FROM runs WHERE id=%s", (run_id,), one=True)
    if not run:
        raise HTTPException(404)
    company = db.q("SELECT * FROM companies WHERE id=%s", (run["company_id"],), one=True)
    n_runs = db.q("SELECT count(*) AS c FROM runs WHERE company_id=%s AND id<=%s", (company["id"], run_id), one=True)["c"]
    sources = db.q("SELECT n, url, title, snippet, published_at, acquired_at, source_type, from_memory FROM sources WHERE run_id=%s ORDER BY n", (run_id,))
    facts = db.q("SELECT category, claim, source_ns, status, confidence, note FROM facts WHERE run_id=%s ORDER BY id", (run_id,))
    memo = db.q("SELECT content FROM memos WHERE run_id=%s", (run_id,), one=True)
    return {
        "run": {**run, "number": n_runs, "stages": agents.STAGES},
        "company": company,
        "sources": {s["n"]: s for s in sources},
        "facts": facts,
        "memo": memo["content"] if memo else None,
    }


@app.get("/api/companies")
def companies():
    return db.q("""
        SELECT c.id, c.name, c.website, c.last_checked_at, r.id AS run_id, r.status,
               m.content->'alert'->>'title' AS alert
        FROM companies c
        LEFT JOIN LATERAL (SELECT id, status FROM runs WHERE company_id=c.id ORDER BY id DESC LIMIT 1) r ON true
        LEFT JOIN memos m ON m.run_id = r.id
        ORDER BY c.last_checked_at DESC NULLS LAST, c.id DESC""")


@app.post("/api/runs/{run_id}/ask")
async def ask(run_id: int, body: AskIn):
    return await agents.ask(run_id, body.question)


@app.get("/health")
def health():
    return {"ok": True, "model": agents.MODEL, "db": bool(os.environ.get("DATABASE_URL"))}
