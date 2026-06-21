"""gbrain · Scrappa search adapter (enrichment).

Uses Scrappa's documented Google Search endpoint:
    GET https://scrappa.co/api/search?query=...   (header X-API-KEY, 1 credit)
→ { organic_results: [{title, link, snippet, ...}], knowledge_graph, ... }

PRIVACY: only public identifiers (company / person NAMES) are ever sent to
Scrappa — never confidential deal details (revenue, ask, valuation, POC).
"""

from __future__ import annotations

import json
import os
import re

import httpx

BASE = os.environ.get("SCRAPPA_API_URL", "https://scrappa.co/api").rstrip("/")
_LINKEDIN = re.compile(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/[^\s?#)\"']+", re.I)


def _key() -> str:
    k = os.environ.get("SCRAPPA_API_KEY", "").strip()
    if not k:
        raise RuntimeError("SCRAPPA_API_KEY not set in /opt/gbrain/.env")
    return k


def search(query: str) -> dict:
    """One Google search via Scrappa (1 credit). Returns the JSON response."""
    r = httpx.get(f"{BASE}/search", params={"query": query},
                  headers={"X-API-KEY": _key()}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"scrappa search {r.status_code}: {r.text[:200]}")
    return r.json()


def find_linkedin(name: str, company: str = "") -> str | None:
    """Best-effort LinkedIn /in/ profile URL for a person (1 credit)."""
    if not name:
        return None
    data = search(f'{name} {company} site:linkedin.com/in'.strip())
    for res in data.get("organic_results") or []:
        m = _LINKEDIN.search(res.get("link") or "")
        if m:
            return m.group(0).rstrip("/")
    m = _LINKEDIN.search(json.dumps(data))   # fallback: scan snippets/knowledge graph
    return m.group(0).rstrip("/") if m else None
