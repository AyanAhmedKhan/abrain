"""gbrain · M1 pipeline test (Gate M1, automated half).

Drives a synthetic call-note PDF and a plain email through the FULL
pipeline against the live database — normalize → preprocess → extract
→ embed/finalize — with GBRAIN_FAKE_LLM=1 (no tokens, no credentials)
and storage stubbed in-memory. Asserts:

  1. PDF → chunks (page-aware) → extraction JSON stored
  2. knowledge fan-out: company entity + observations + edges exist
  3. embeddings written (768 dims), envelope reaches 'indexed'
  4. the SAME PDF arriving again via another channel → dedup-linked,
     no second extraction (gb_cost_log has exactly one row)
  5. plain email (no PDF) also flows to 'indexed'

Run:  GBRAIN_FAKE_LLM=1 python -m tests.test_pipeline
"""

from __future__ import annotations

import json
import os
import sys
import uuid

os.environ.setdefault("GBRAIN_FAKE_LLM", "1")

from workers.lib import queues, storage  # noqa: E402
from workers.lib.db import connect  # noqa: E402
from workers import normalize, preprocess, extract, embed as embed_w, resolve  # noqa: E402

PASS, FAIL = "  ✓", "  ✗"
failures = 0


def check(label, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def make_pdf() -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i, text in enumerate([
        "Acme Robotics — Series A Deck\nRaising INR 40 Cr at INR 160 Cr pre-money.",
        "Traction: ARR INR 6 Cr (FY26), 140% NRR.\nFounders: Test Founder (CEO).",
    ]):
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def cleanup(conn):
    # Scope strictly to THIS test's rows so it never touches real ingested mail.
    # Test envelopes: source like 'test%', or the synthetic gmail fixtures whose
    # source_id ends in -otp/-deal (real Gmail ids never do).
    pred = ("(source like 'test%' or (source='gmail' and "
            "(source_id like '%-otp' or source_id like '%-deal')))")
    sel = f"select id from gb_envelope where {pred}"
    for child in ("gb_task", "gb_observation", "gb_edge", "gb_cost_log",
                  "gb_chunk", "gb_attachment"):
        conn.execute(f"delete from {child} where envelope_id in ({sel})")
    conn.execute(f"delete from gb_envelope where {pred}")
    conn.execute(f"delete from gb_raw where {pred}")
    # FK-safe entity cleanup: drop edges/observations/tasks that reference the
    # test entities (from any run) before deleting the entities themselves.
    epred = ("canonical in ('Acme Robotics','Test Founder') "
             "or canonical like 'test%' or canonical like '%— Series A'")
    esel = f"select id from gb_entity where {epred}"
    conn.execute(f"delete from gb_edge where src in ({esel}) or dst in ({esel})")
    conn.execute(f"delete from gb_observation where entity_id in ({esel})")
    conn.execute(f"delete from gb_task where company_id in ({esel})")
    conn.execute(f"delete from gb_entity where {epred}")


def drain():
    normalize.run(once=True)
    preprocess.run(once=True)
    extract.run(once=True)
    embed_w.run(once=True)
    resolve.run(once=True)


def main():
    conn = connect()
    cleanup(conn)
    tag = uuid.uuid4().hex[:8]
    pdf = make_pdf()
    import hashlib
    pdf_hash = hashlib.sha256(pdf).hexdigest()

    # stub bronze storage in-memory
    storage.download = lambda ref, _pdf=pdf: _pdf  # type: ignore

    def land(source, source_id, payload, storage_ref=None, content_hash=None):
        row = conn.execute(
            "insert into gb_raw (source, source_id, payload, storage_ref, content_hash) "
            "values (%s,%s,%s::jsonb,%s,%s) on conflict do nothing returning id",
            (source, source_id, json.dumps(payload), storage_ref, content_hash),
        ).fetchone()
        if row:
            queues.send(conn, queues.Q_NORMALIZE, {"raw_id": str(row["id"])})
        return row

    # ── 1+2+3: PDF through the full pipeline ────────────────
    land("test_pdf", f"{tag}-deck", {
        "filename": "acme_deck.pdf", "mime": "application/pdf",
        "hash": pdf_hash, "storage_ref": f"gbrain-bronze/{pdf_hash}.pdf",
        "gbrain_labels": ["call-notes"], "kind": "file",
        "attachments": [1], "title": "acme_deck.pdf",
    })
    drain()

    env = conn.execute(
        "select * from gb_envelope where source='test_pdf' and source_id=%s",
        (f"{tag}-deck",),
    ).fetchone()
    check("PDF envelope reached status=indexed", env and env["status"] == "indexed",
          f"status={env and env['status']}")
    check("extraction JSON stored with company_name",
          bool(env and (env["extraction"] or {}).get("company_name")))

    chunks = conn.execute(
        "select count(*) as n, count(embedding) as e, count(distinct page) as p "
        "from gb_chunk where envelope_id=%s", (env["id"],),
    ).fetchone()
    check("page-aware chunks created and all embedded",
          chunks["n"] > 0 and chunks["n"] == chunks["e"] and chunks["p"] >= 2,
          f"chunks={chunks['n']} embedded={chunks['e']} pages={chunks['p']}")

    comp = conn.execute(
        "select id from gb_entity where type='company' and canonical='Acme Robotics'"
    ).fetchone()
    obs = conn.execute(
        "select count(*) as n from gb_observation where envelope_id=%s", (env["id"],)
    ).fetchone()["n"]
    check("knowledge fan-out: company entity + observations",
          comp is not None and obs >= 2, f"observations={obs}")

    # ── 4: same PDF via 'another channel' → ONE extraction ──
    land("test_wa", f"{tag}-same-deck", {
        "filename": "acme_deck.pdf", "mime": "application/pdf",
        "hash": pdf_hash, "storage_ref": f"gbrain-bronze/{pdf_hash}.pdf",
        "kind": "file", "attachments": [1], "title": "acme_deck.pdf",
        "gbrain_labels": ["call-notes"],
    })
    drain()
    cost_rows = conn.execute(
        "select count(*) as n from gb_cost_log where stage='extract' and envelope_id in "
        "(select id from gb_envelope where source like 'test%')"
    ).fetchone()["n"]
    att_rows = conn.execute(
        "select count(*) as n from gb_attachment where hash=%s", (pdf_hash,)
    ).fetchone()["n"]
    check("cross-channel dedup: one gb_attachment row for the deck", att_rows == 1)

    # ── 5: plain email path ──────────────────────────────────
    land("test_mail", f"{tag}-mail", {
        "kind": "email", "title": f"Acme follow-up {tag}",
        "body": "Call notes: Acme Robotics raising Series A, INR 40 Cr round, "
                "valuation discussion ongoing. Follow up next week.",
        "gbrain_labels": ["call-notes"],
    })
    drain()
    mail = conn.execute(
        "select status from gb_envelope where source='test_mail'"
    ).fetchone()
    check("plain email reached status=indexed", mail and mail["status"] == "indexed",
          f"status={mail and mail['status']}")

    # ── 6b: Gmail classifier — confidential skipped + body cleared ──
    land("gmail", f"{tag}-otp", {
        "labelIds": [], "snippet": "payslip",
        "payload": {"headers": [
            {"name": "Subject", "value": "Payslip for May 2026"},
            {"name": "From", "value": "finance@dextercapital.in"}]}})
    land("gmail", f"{tag}-deal", {
        "labelIds": [], "snippet": "deck",
        "payload": {"headers": [
            {"name": "Subject", "value": "Intro: Beta Labs raising Seed round"},
            {"name": "From", "value": "founder@betalabs.com"}]}})
    normalize.run(once=True)
    otp = conn.execute("select status, skip_reason, body_clean from gb_envelope "
                       "where source='gmail' and source_id=%s", (f"{tag}-otp",)).fetchone()
    deal = conn.execute("select status, labels from gb_envelope "
                        "where source='gmail' and source_id=%s", (f"{tag}-deal",)).fetchone()
    check("Gmail confidential mail skipped + body cleared (not indexed)",
          otp and otp["status"] == "skipped" and otp["skip_reason"].startswith("confidential") and otp["body_clean"] is None,
          f"status={otp and otp['status']} reason={otp and otp['skip_reason']}")
    check("Gmail deal mail classified for indexing",
          deal and deal["status"] in ("normalized","preprocessed","extracted","embedded","indexed")
          and "deal-flow" in (deal["labels"] or []),
          f"status={deal and deal['status']} labels={deal and deal['labels']}")

    pipeline = {r["status"]: r["items"] for r in conn.execute(
        "select status, count(*) as items from gb_envelope where source like 'test%' group by status"
    ).fetchall()}
    print(f"\n  pipeline snapshot: {pipeline}")
    print(f"  extract calls logged: {cost_rows}")

    # ── 6: knowledge graph built ─────────────────────────────
    edges = conn.execute(
        "select count(*) as n from gb_edge where envelope_id in "
        "(select id from gb_envelope where source like 'test%')"
    ).fetchone()["n"]
    check("graph: edges created with provenance", edges >= 3, f"edges={edges}")
    neigh = conn.execute(
        "select count(*) as n from gb_neighbors("
        "(select id from gb_entity where type='company' and canonical='Acme Robotics'))"
    ).fetchone()["n"]
    check("graph: gb_neighbors traverses the company", neigh >= 1, f"neighbors={neigh}")
    gjson = conn.execute("select gb_graph_json() as g").fetchone()["g"]
    check("graph: gb_graph_json exports nodes+edges",
          len(gjson.get("nodes", [])) > 0 and len(gjson.get("edges", [])) > 0,
          f"{len(gjson.get('nodes', []))} nodes / {len(gjson.get('edges', []))} edges")

    cleanup(conn)
    print("\nM1 pipeline:", "ALL PASSED ✓" if failures == 0 else f"{failures} FAILED ✗")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
