"""gbrain · investor & co-investment graph.

Promotes extraction.existing_investors (plain strings) into first-class investor
entities + `invests_in` edges (investor → portfolio company), powering
"all <Investor>-backed companies", co-investor patterns, and sector activity.
Deterministic, zero LLM tokens.

  link(conn, company_id, names, envelope_id)  — used by extract.fan_out (forward)
  backfill(conn)                              — one-time from already-indexed notes
  python -m workers.investors backfill
"""

from __future__ import annotations

import re
import sys

from workers.lib.db import connect

# generic, non-identifying "investors" that should NOT become entities
_JUNK = {
    "angels", "angel", "angel investor", "angel investors", "angel network",
    "angel networks", "angel group", "angel groups", "hni", "hnis", "hnwi", "hnwis",
    "undisclosed", "various", "various investors", "other", "others", "na", "n/a",
    "tbd", "unknown", "none", "friends and family", "friends & family", "f&f",
    "existing investors", "existing investor", "promoters", "promoter", "public",
    "retail", "strategic investors", "institutional investors", "family offices",
    "family office", "syndicate", "angel syndicate",
}
_GENERIC = re.compile(r"^\s*\d*\s*(hnwis?|hnis?|angels?|investors?|family offices?|"
                      r"angel investors?|angel networks?)\s*$", re.I)


def is_investor_name(name: str) -> bool:
    n = (name or "").strip().strip(".")
    if len(n) < 2 or "@" in n:
        return False
    low = n.lower()
    return low not in _JUNK and not _GENERIC.match(low)


def _upsert_investor(conn, name: str):
    return conn.execute(
        """insert into gb_entity (type, canonical, attrs)
             values ('investor', %s, '{"is_investor": true}'::jsonb)
           on conflict (type, canonical) do update set attrs = gb_entity.attrs || excluded.attrs
           returning id""",
        (name.strip(),)).fetchone()["id"]


def link(conn, company_id, names, envelope_id=None) -> int:
    """investor-name strings → investor entities + invests_in edges. Idempotent."""
    if not company_id:
        return 0
    if isinstance(names, str):
        names = [names]
    n = 0
    for raw in names or []:
        nm = str(raw).strip()
        if not is_investor_name(nm):
            continue
        iid = _upsert_investor(conn, nm)
        conn.execute(
            "insert into gb_edge (src, rel, dst, envelope_id) values (%s,'invests_in',%s,%s) "
            "on conflict do nothing", (iid, company_id, envelope_id))
        n += 1
    return n


def backfill(conn) -> int:
    rows = conn.execute(
        "select id, extraction from gb_envelope where status='indexed' and extraction ? 'existing_investors'"
    ).fetchall()
    total = 0
    for r in rows:
        ex = r["extraction"] or {}
        co = (ex.get("company_name") or "").strip()
        if not co:
            continue
        cid = conn.execute("select id from gb_entity where type='company' and canonical=%s", (co,)).fetchone()
        if not cid:
            continue
        total += link(conn, cid["id"], ex.get("existing_investors"), r["id"])
    return total


if __name__ == "__main__":
    conn = connect()
    if (sys.argv[1:] or ["backfill"])[0] == "backfill":
        print(f"[investors] linked {backfill(conn)} investor→company edges", flush=True)
