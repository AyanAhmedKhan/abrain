"""gbrain · edge-case hardening tests.

Covers the failure modes the hardening pass fixed: numeric coercion, Gemini
JSON-parse fallback + array coercion, oversized-chunk splitting, the stuck-
envelope sweeper, the LLM budget cap, safe filenames, and degenerate-row
rendering.

Run with the systemd workers STOPPED (so the sweeper test's queue message
isn't consumed by a live worker):
    GBRAIN_FAKE_LLM=1 python -m tests.test_edges
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("GBRAIN_FAKE_LLM", "1")

from workers.lib.db import connect  # noqa: E402

PASS, FAIL = "  ✓", "  ✗"
failures = 0


def check(label, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def test_safe_num():
    from workers.lib.num import safe_num
    cases = {"40-60": 40.0, "$5M": 42.5, "$1.1B": 9350.0, "~40": 40.0,
             "₹50 Cr": 50.0, "": None, "n/a": None, 12: 12.0, 12.5: 12.5}
    bad = {k: (safe_num(k), v) for k, v in cases.items() if safe_num(k) != v}
    check("safe_num coerces messy numeric strings", safe_num(None) is None and not bad, str(bad))


def test_gemini_fallback():
    from workers.lib import gemini

    class Bad:
        text = "totally not json {oops"
        usage_metadata = None
    r = gemini._result(Bad(), "m")
    check("gemini JSON-parse fallback → low-confidence dict (no crash)",
          isinstance(r.data, dict) and r.data.get("confidence") == "low")

    class Arr:
        text = '[{"company_name": "X", "confidence": "high"}, {"company_name": "Y"}]'
        usage_metadata = None
    r2 = gemini._result(Arr(), "m")
    check("gemini coerces array → primary object", r2.data.get("company_name") == "X")


def test_chunk_split():
    from workers.preprocess import chunk_text, CHUNK_CHARS
    big = "x" * (CHUNK_CHARS * 3)          # one paragraph, no blank lines
    chunks = chunk_text(big, 1)
    check("oversized paragraph is hard-split under CHUNK_CHARS",
          chunks and all(len(t) <= CHUNK_CHARS for _, t in chunks) and len(chunks) >= 3,
          f"{len(chunks)} chunks, max={max(len(t) for _,t in chunks)}")


def test_safe_name():
    from workers.obsidian_export import safe_name
    long = "Acme " * 60
    s = safe_name(long)
    check("long filename capped + hash-suffixed + stable",
          len(s) <= 120 and s == safe_name(long))
    check("illegal chars stripped", "/" not in safe_name("A/B : C*?"))


def test_render_degenerate():
    from workers import obsidian_export as g
    minimal = {k: v for k, v in {
        "name": "Edge & Co / Test", "sector": None, "sub_sector": None, "stage": None,
        "round_type": None, "business_model": None, "summary": None, "ask": None,
        "valuation": None, "revenue": None, "revenue_period": None, "ebitda": None,
        "founders": {}, "key_metrics": [], "risks": [], "actions": [], "opinions": [],
        "emails": [], "last": "", "hq": None, "website": None, "founded": None,
        "poc": None, "fitment": None, "referred_by": None, "aliases": [],
        "existing_investors": [], "dexter": set(),
    }.items()}
    out = g.render_company(minimal, {}, {})
    check("render_company handles an all-empty row without throwing",
          isinstance(out, str) and out.startswith("---"))


def test_budget_cap(conn):
    from workers import extract
    orig = extract.DAILY_BUDGET_USD
    conn.execute("insert into gb_cost_log (stage, model, usd) values ('extract','__edgetest__',0.05)")
    try:
        extract.DAILY_BUDGET_USD = 0.0001
        check("budget cap trips when today's spend exceeds it", extract.budget_exceeded(conn) is True)
        extract.DAILY_BUDGET_USD = 0
        check("budget cap of 0 = unlimited (never trips)", extract.budget_exceeded(conn) is False)
    finally:
        extract.DAILY_BUDGET_USD = orig
        conn.execute("delete from gb_cost_log where model='__edgetest__'")


def test_sweeper_stuck(conn):
    from workers import sweeper
    rid = conn.execute(
        "insert into gb_raw (source, source_id, payload) "
        "values ('test_edge','edge-stuck','{}'::jsonb) "
        "on conflict (source, source_id) do update set received_at=now() returning id"
    ).fetchone()["id"]
    eid = conn.execute(
        """insert into gb_envelope (raw_id, idempotency_key, source, source_id, kind, status, ingested_at)
           values (%s,'edge-stuck-key','test_edge','edge-stuck','email','extracted', now() - interval '1 hour')
           on conflict (idempotency_key) do update
             set status='extracted', ingested_at = now() - interval '1 hour'
           returning id""", (rid,)).fetchone()["id"]
    try:
        sweeper.run()
        msgs = conn.execute("select message from pgmq.q_gb_q_embed").fetchall()
        found = any(m["message"].get("envelope_id") == str(eid) for m in msgs)
        check("sweeper re-enqueues a stuck 'extracted' envelope → gb_q_embed", found)
    finally:
        conn.execute("delete from pgmq.q_gb_q_embed where message->>'envelope_id' = %s", (str(eid),))
        conn.execute("delete from gb_envelope where id=%s", (eid,))
        conn.execute("delete from gb_raw where id=%s", (rid,))


def main():
    conn = connect()
    test_safe_num()
    test_gemini_fallback()
    test_chunk_split()
    test_safe_name()
    test_render_degenerate()
    test_budget_cap(conn)
    test_sweeper_stuck(conn)
    print("\nedge cases:", "ALL PASSED ✓" if failures == 0 else f"{failures} FAILED ✗")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
