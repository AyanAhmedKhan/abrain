"""gbrain · load_tracxn test.

Drives `workers.load_tracxn` over a synthetic JSONL against the live database and
asserts the structured load:
  - company entities upserted, with name_map enrich-in-place (a Tracxn id mapped
    to a different gbrain canonical lands on that canonical, not the Tracxn name);
  - Tracxn financial observations (source='Tracxn', one snapshot per metric);
  - investor `invests_in` and person `works_at` edges;
  - statutory-filing rows (kind='document') → document entities + 'about' edges;
  - a SECOND run is a no-op (idempotent: no duplicate observations, edges, or docs).

All test entities are named "Zztest …" so cleanup is precisely scoped. No LLM is
invoked, but we keep the GBRAIN_FAKE_LLM convention.

Run:  GBRAIN_FAKE_LLM=1 python -m tests.test_load_tracxn
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ.setdefault("GBRAIN_FAKE_LLM", "1")

from workers.lib.db import connect  # noqa: E402
from workers import load_tracxn  # noqa: E402

PASS, FAIL = "  ✓", "  ✗"
failures = 0


def check(label, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


ALPHA_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
ROWS = [
    {
        "id": ALPHA_ID,
        "name": "Zztest Alphaco",                         # remapped via NAME_MAP below
        "website": "https://www.zztest-alpha.com/in",
        "founded": 2015, "stage": "Series A",
        "city": "Bengaluru", "country": "India",
        "sector": "Consumer > Fashion Tech > Eyewear",
        "short_description": "Test eyewear co",
        "revenue_inr_cr": 100.5, "revenue_as_on": "2024-03-31",
        "ebitda_inr_cr": -5.2, "ebitda_as_on": "2024-03-31",
        "net_profit_inr_cr": -8.0, "net_profit_as_on": "2024-03-31",
        "valuation_inr_cr": 900.0, "valuation_as_on": "2024-06-30",
        "employee_count": 120,
        "total_equity_funding_usd_m": 10.0,
        "tracxn_score": 75,
        "investors": "Zztest Capital; Zztest Ventures",
        "key_people": "Zztest Arvind (CEO); Zztest Bela (CTO); Founder (Founder)",
        "tracxn_url": "https://tracxn.com/d/companies/zztest",
    },
    {
        "id": "bbbbbbbbbbbbbbbbbbbbbbbb",
        "name": "Zztest Betaco",
        "website": "", "revenue_inr_cr": "", "valuation_inr_cr": "",
        "investors": "", "key_people": "",
    },
    {
        "kind": "document",
        "company_id": ALPHA_ID, "company_name": "Zztest Alphaco",
        "id": "ddddddddddddddddddddddd1", "name": "Form MGT-7",
        "document_type": "Annual Returns", "category": "Annual Reports",
        "filing_type": "Annual Return", "registrar": "mca.gov.in",
        "filing_date": "2025-09-24", "cin": "U33100DL2008PLC178355",
        "viewer_url": "https://platform.tracxn.com/a/d/document/ddddddddddddddddddddddd1/formmgt-7",
        "document_code": "MGT7",
    },
]
# map the Tracxn id to a DIFFERENT gbrain canonical → must enrich that one in place
NAME_MAP = {ALPHA_ID: "Zztest Alpha Renamed"}


def _scalar(conn, sql, args=None):
    cur = conn.execute(sql, args) if args else conn.execute(sql)
    r = cur.fetchone()
    return list(r.values())[0] if r else None


def cleanup(conn):
    ids = [r["id"] for r in conn.execute(
        "select id from gb_entity where canonical like 'Zztest %'").fetchall()]
    if ids:
        conn.execute("delete from gb_edge where src = any(%s) or dst = any(%s)", (ids, ids))
        conn.execute("delete from gb_observation where entity_id = any(%s)", (ids,))
        conn.execute("delete from gb_entity where id = any(%s)", (ids,))


def cid(conn, name):
    return _scalar(conn, "select id from gb_entity where type='company' and canonical=%s", (name,))


def main() -> int:
    conn = connect()
    cleanup(conn)  # start clean

    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="tracxn_test_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in ROWS:
                fh.write(json.dumps(r) + "\n")

        # ── run 1 ────────────────────────────────────────────
        t1 = load_tracxn.load_jsonl(conn, path, NAME_MAP)
        check("run1 companies = 2", t1["companies"] == 2, str(t1))
        check("run1 investor links = 2", t1["investor_links"] == 2, str(t1))
        check("run1 people links = 2 (role bucket filtered)", t1["people_links"] == 2, str(t1))
        check("run1 documents = 1, linked = 1", t1["documents"] == 1 and t1["doc_links"] == 1, str(t1))

        alpha = cid(conn, "Zztest Alpha Renamed")
        check("name_map enrich-in-place: company is the MAPPED canonical", bool(alpha))
        check("name_map: Tracxn's own name NOT created", cid(conn, "Zztest Alphaco") is None)
        check("unmapped company keeps its row name", bool(cid(conn, "Zztest Betaco")))

        a = conn.execute("select attrs, keys from gb_entity where id=%s", (alpha,)).fetchone()
        check("company attrs mirror revenue", a["attrs"].get("revenue_inr_cr") == 100.5)
        check("sector canonicalized to 'Consumer'", a["attrs"].get("sector") == "Consumer",
              a["attrs"].get("sector"))
        check("keys.domain parsed", a["keys"].get("domain") == "zztest-alpha.com", a["keys"].get("domain"))

        obs = conn.execute(
            "select metric from gb_observation where entity_id=%s and source='Tracxn'", (alpha,)).fetchall()
        metrics = {o["metric"] for o in obs}
        check("alpha has 6 Tracxn observations", len(obs) == 6, str(sorted(metrics)))
        check("metrics cover the financial set",
              {"revenue", "ebitda", "net_profit", "valuation", "employees", "funding"} <= metrics,
              str(sorted(metrics)))

        inv = _scalar(conn, "select count(*) from gb_edge where dst=%s and rel='invests_in'", (alpha,))
        ppl = _scalar(conn, "select count(*) from gb_edge where dst=%s and rel='works_at'", (alpha,))
        check("2 invests_in + 2 works_at edges → alpha", inv == 2 and ppl == 2, f"inv={inv} ppl={ppl}")
        check("role bucket 'Founder' not a person entity",
              _scalar(conn, "select count(*) from gb_entity where type='person' and canonical='Founder'") == 0)

        # ── document assertions ──────────────────────────────
        doc = conn.execute(
            "select id, attrs, keys from gb_entity where type='document' "
            "and canonical=%s", ("Zztest Alpha Renamed — Form MGT-7 (2025-09-24)",)).fetchone()
        check("document entity created (canonical scoped to company+date)", bool(doc),
              "missing document node")
        if doc:
            check("doc source_url = viewer_url",
                  doc["attrs"].get("source_url", "").endswith("/formmgt-7"))
            check("doc keys.tracxn_doc_id stamped",
                  doc["keys"].get("tracxn_doc_id") == "ddddddddddddddddddddddd1")
            about = _scalar(conn,
                "select count(*) from gb_edge where src=%s and rel='about' and dst=%s", (doc["id"], alpha))
            check("document --about--> company edge", about == 1, str(about))

        # ── run 2: idempotency ───────────────────────────────
        n_before = _scalar(conn, "select count(*) from gb_entity where canonical like 'Zztest %'")
        load_tracxn.load_jsonl(conn, path, NAME_MAP)
        n_after = _scalar(conn, "select count(*) from gb_entity where canonical like 'Zztest %'")
        check("run2: entity count unchanged (no dupes)", n_before == n_after, f"{n_before}→{n_after}")
        obs2 = _scalar(conn,
            "select count(*) from gb_observation where entity_id=%s and source='Tracxn'", (alpha,))
        check("run2: still 6 observations (replaced, not appended)", obs2 == 6, str(obs2))
        inv2 = _scalar(conn, "select count(*) from gb_edge where dst=%s and rel='invests_in'", (alpha,))
        ppl2 = _scalar(conn, "select count(*) from gb_edge where dst=%s and rel='works_at'", (alpha,))
        about2 = _scalar(conn, "select count(*) from gb_edge where rel='about' and dst=%s", (alpha,))
        check("run2: no duplicate edges", inv2 == 2 and ppl2 == 2 and about2 == 1,
              f"inv={inv2} ppl={ppl2} about={about2}")

    finally:
        cleanup(conn)
        if path and os.path.exists(path):
            os.remove(path)

    print("\n" + ("PASS — load_tracxn: companies + name-map + observations + edges + documents, idempotent"
                  if not failures else f"FAIL — {failures} check(s) failed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
