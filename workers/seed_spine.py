"""gbrain · seed the identity spine from the 92-deal dataset.

Loads a CSV (the dextercapital.in transactions export: company,
investors, description, year, sector) into gb_entity as canonical
company / investor / deal records — the spine that mentions from every
source resolve against.

Usage:
  python -m workers.seed_spine /path/to/dexter_transactions.csv
CSV columns (case-insensitive, extra columns ignored):
  company, investors, description, year, sector
Idempotent — re-running upserts.
"""

from __future__ import annotations

import csv
import json
import sys

from workers.lib.db import connect


def upsert(conn, etype, canonical, attrs=None, keys=None):
    if not canonical or not canonical.strip():
        return None
    return conn.execute(
        """insert into gb_entity (type, canonical, attrs, keys)
           values (%s,%s,%s::jsonb,%s::jsonb)
           on conflict (type, canonical) do update
             set attrs = gb_entity.attrs || excluded.attrs
           returning id""",
        (etype, canonical.strip(), json.dumps(attrs or {}), json.dumps(keys or {})),
    ).fetchone()["id"]


def main(path: str) -> None:
    conn = connect()
    n_c = n_i = n_d = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = {c.lower().strip(): c for c in reader.fieldnames or []}
        get = lambda row, name: (row.get(cols.get(name, ""), "") or "").strip()
        for row in reader:
            company = get(row, "company")
            if not company:
                continue
            cid = upsert(conn, "company", company, {
                "sector": get(row, "sector") or None,
                "description": get(row, "description") or None,
                "spine": True,
            })
            n_c += 1
            year = get(row, "year")
            did = upsert(conn, "deal", f"{company} — {year or 'Transaction'}", {
                "company": company, "year": year or None,
                "sector": get(row, "sector") or None, "spine": True,
            })
            if cid and did:
                conn.execute(
                    "insert into gb_edge (src, rel, dst) values (%s,'involves',%s) "
                    "on conflict do nothing", (did, cid))
            n_d += 1
            for inv in [i.strip() for i in get(row, "investors").split(",") if i.strip()]:
                iid = upsert(conn, "investor", inv, {"spine": True})
                if iid and did:
                    conn.execute(
                        "insert into gb_edge (src, rel, dst) values (%s,'invested_in',%s) "
                        "on conflict do nothing", (iid, did))
                n_i += 1
    print(f"spine seeded: {n_c} companies · {n_d} deals · {n_i} investor links")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m workers.seed_spine <transactions.csv>")
    main(sys.argv[1])
