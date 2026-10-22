"""Keenable web search client (live web + X)."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

API = "https://api.keenable.ai/v1/search"

DATABASES = ("ycombinator.com/companies", "tracxn", "pitchbook", "crunchbase", "dealroom", "cbinsights",
             "ycstartups", "equityflow", "yctierlist", "startupintros", "platoseed", "lemstudio", "toolbit",
             "rightaichoice", "altss", "extruct", "welcome.ai", "zerogtalent", "startuply", "7wdata", "g2.com")
PRESS = ("techcrunch", "forbes", "bloomberg", "reuters", "theinformation", "businessinsider", "sifted",
         "wsj", "ft.com", "venturebeat", "axios", "cnbc", "fortune")
SOCIAL = ("x.com", "twitter.com", "linkedin.com", "reddit.com", "news.ycombinator.com", "youtube.com")


async def search(client: httpx.AsyncClient, query: str, max_results: int = 6, site: str | None = None,
                 published_after: str | None = None) -> list[dict]:
    body = {"query": query, "max_results": max_results}
    if site:
        body["site"] = site
    if published_after:
        body["published_after"] = published_after
    try:
        r = await client.post(API, json=body, headers={"X-API-Key": os.environ["KEENABLE_API_KEY"]}, timeout=30)
        r.raise_for_status()
        return [dict(res, query=query) for res in r.json().get("results", [])]
    except Exception:
        return []


def domain(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def source_type(url: str, company_domain: str) -> str:
    u = url.lower()
    if company_domain and domain(url).endswith(company_domain):
        return "primary"
    if "ycombinator.com/launches" in u:
        return "primary"
    if any(d in u for d in DATABASES):
        return "database"
    if any(d in u for d in SOCIAL):
        return "social"
    if any(d in u for d in PRESS):
        return "press"
    return "web"
