"""Aiven PostgreSQL: schema + small helpers. The fact table is Scout's long-term memory."""
from __future__ import annotations

import base64
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  key TEXT UNIQUE NOT NULL,
  website TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  last_checked_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS runs (
  id SERIAL PRIMARY KEY,
  company_id INT REFERENCES companies(id),
  started_at TIMESTAMPTZ DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT DEFAULT 'running',
  stage INT DEFAULT 0,
  stats JSONB DEFAULT '{}'::jsonb,
  error TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  id SERIAL PRIMARY KEY,
  run_id INT REFERENCES runs(id),
  n INT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  snippet TEXT,
  published_at TEXT,
  acquired_at TEXT,
  source_type TEXT,
  query TEXT,
  from_memory BOOLEAN DEFAULT false
);
CREATE TABLE IF NOT EXISTS facts (
  id SERIAL PRIMARY KEY,
  company_id INT REFERENCES companies(id),
  run_id INT REFERENCES runs(id),
  category TEXT,
  claim TEXT,
  source_ns INT[],
  status TEXT,
  confidence REAL,
  note TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memos (
  run_id INT PRIMARY KEY REFERENCES runs(id),
  content JSONB
);
"""


def _ssl_params() -> dict:
    # On Aiven Runtime, PROJECT_CA_CERT (base64) lets us verify the server certificate
    ca = os.environ.get("PROJECT_CA_CERT")
    if not ca:
        return {}
    path = "/tmp/aiven-ca.pem"
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(base64.b64decode(ca).decode())
    return {"sslmode": "verify-full", "sslrootcert": path}


@contextmanager
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True,
                         connect_timeout=15, **_ssl_params()) as c:
        yield c


def init():
    with conn() as c:
        c.execute(SCHEMA)


def q(sql: str, params=(), one=False):
    with conn() as c:
        cur = c.execute(sql, params)
        if cur.description is None:
            return None
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows


def upsert_company(name: str, website: str | None) -> dict:
    key = name.strip().lower()
    return q(
        """INSERT INTO companies (name, key, website) VALUES (%s, %s, %s)
           ON CONFLICT (key) DO UPDATE SET website = COALESCE(EXCLUDED.website, companies.website)
           RETURNING *""",
        (name.strip(), key, website),
        one=True,
    )


def jsonb(v):
    return Jsonb(v)
