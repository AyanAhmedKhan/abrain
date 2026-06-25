"""gbrain · load_tracxn test.

Drives `workers.load_tracxn` over a synthetic JSONL against the live database and
asserts the structured load: company entities (enriched in place), Tracxn financial
observations, investor `invested_in` and person `works_at` edges — and that a
SECOND run is a no-op (idempotent: no duplicate observations or edges).

All test entities are named "Zztest …" so cleanup is precisely scoped. No LLM is
invoked (structured load), but we keep the GBRAIN_FAKE_LLM convention.

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


ROWS = [
    {
        "id": "aaaaaaaaaaaaaaaaaaaaaaaa",
        "name": "Zztest Alphaco",
        "website": "https://www.zztest-alpha.com/in",
        "founded": 2015,
        "stage": "Series A",
        "city": "Bengaluru",
        "country": "India",
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
        # third entry is a role bucket → must be filtered by is_person_name
        "key_people": "Zztest Arvind (CEO); Zztest Bela (CTO); Founder (Founder)",
        "tracxn_url": "https://tracxn.com/d/companies/zztest",
    },
    {
        "id": "bbbbbbbbbbbbbbbbbbbbbbbb",
        "name": "Zztest Betaco",
        "website": "",
        "revenue_inr_cr": "", "valuation_inr_cr": "",
        "investors": "", "key_people": "",
    },
]


def _scalar(conn, sql, args=None):
    # psycopg3 parses '%' as a placeholder whenever a params arg is given (even ()),
    # which breaks LIKE 'Zztest %'. Only pass params when we actually have them.
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


def company_id(conn, name):
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
        t1 = load_tracxn.load_jsonl(conn, path)
        check("run1 companies = 2", t1["companies"] == 2, str(t1))
        check("run1 investor links = 2", t1["investor_links"] == 2, str(t1))
        check("run1 people links = 2 (role bucket filtered)", t1["people_links"] == 2, str(t1))

        alpha = company_id(conn, "Zztest Alphaco")
        beta = company_id(conn, "Zztest Betaco")
        check("both companies upserted", bool(alpha) and bool(beta))

        a = conn.execute("select attrs, keys from gb_entity where id=%s", (alpha,)).fetchone()
        check("company attrs mirror revenue", a["attrs"].get("revenue_inr_cr") == 100.5,
              str(a["attrs"].get("revenue_inr_cr")))
        check("sector canonicalized to 'Consumer'", a["attrs"].get("sector") == "Consumer",
              a["attrs"].get("sector"))
        check("keys.tracxn_id stamped", a["keys"].get("tracxn_id") == "aaaaaaaaaaaaaaaaaaaaaaaa")
        check("keys.domain parsed", a["keys"].get("domain") == "zztest-alpha.com",
              a["keys"].get("domain"))

        obs = conn.execute(
            "select metric, value_num from gb_observation where entity_id=%s and source='Tracxn'",
            (alpha,)).fetchall()
        metrics = {o["metric"] for o in obs}
        check("alpha has 6 Tracxn observations", len(obs) == 6, str(sorted(metrics)))
        check("metrics cover the financial set",
              {"revenue", "ebitda", "net_profit", "valuation", "employees", "funding"} <= metrics,
              str(sorted(metrics)))
        funding = next((o["value_num"] for o in obs if o["metric"] == "funding"), None)
        check("funding USD-m→INR-cr (10×8.5=85)", funding is not None and abs(float(funding) - 85.0) < 1e-6,
              str(funding))

        beta_obs = _scalar(conn, "select count(*) from gb_observation where entity_id=%s", (beta,))
        check("beta (missing financials) has 0 observations", beta_obs == 0, str(beta_obs))

        inv_links = _scalar(conn,
            "select count(*) from gb_edge where dst=%s and rel='invests_in'", (alpha,))
        check("2 invests_in edges → alpha", inv_links == 2, str(inv_links))
        ppl_links = _scalar(conn,
            "select count(*) from gb_edge where dst=%s and rel='works_at'", (alpha,))
        check("2 works_at edges → alpha", ppl_links == 2, str(ppl_links))
        founder_node = _scalar(conn,
            "select count(*) from gb_entity where type='person' and canonical='Founder'")
        check("role bucket 'Founder' not a person entity", founder_node == 0, str(founder_node))

        # ── run 2: idempotency ───────────────────────────────
        n_before = _scalar(conn, "select count(*) from gb_entity where canonical like 'Zztest %'")
        load_tracxn.load_jsonl(conn, path)
        n_after = _scalar(conn, "select count(*) from gb_entity where canonical like 'Zztest %'")
        check("run2: entity count unchanged (no dupes)", n_before == n_after, f"{n_before}→{n_after}")
        obs2 = _scalar(conn,
            "select count(*) from gb_observation where entity_id=%s and source='Tracxn'", (alpha,))
        check("run2: still 6 observations (replaced, not appended)", obs2 == 6, str(obs2))
        inv2 = _scalar(conn, "select count(*) from gb_edge where dst=%s and rel='invests_in'", (alpha,))
        ppl2 = _scalar(conn, "select count(*) from gb_edge where dst=%s and rel='works_at'", (alpha,))
        check("run2: no duplicate edges", inv2 == 2 and ppl2 == 2, f"inv={inv2} ppl={ppl2}")

    finally:
        cleanup(conn)
        if path and os.path.exists(path):
            os.remove(path)

    print("\n" + ("PASS — load_tracxn structured + idempotent" if not failures
                  else f"FAIL — {failures} check(s) failed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
