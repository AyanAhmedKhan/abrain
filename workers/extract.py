"""gbrain · extract worker (Stage 4 — the one paid step).

Reads gb_q_extract. For each envelope: assemble the document text from
its chunks → one Gemini structured-analysis call (gemini-2.5-flash;
escalates to ESCALATE_MODEL when the model self-reports low confidence)
→ store the note (gb_envelope.extraction) → fan out to the knowledge
layer (gb_entity company/person/deal, gb_observation financials,
gb_task action items) → log cost → enqueue gb_q_embed.

Idempotent: redelivery after 'extracted' is a no-op; entity upserts are
conflict-safe; observations keyed by (envelope, metric) are not re-inserted.

Run:  python -m workers.extract [--once]
"""

from __future__ import annotations

import json
import os
import sys
import time

from workers.lib import queues, storage
from workers.lib.db import connect
from workers.lib.gemini import ESCALATE_MODEL, generate_json, generate_json_from_pdf
from workers.lib.names import is_person_name
from workers.lib.note_schema import PROMPT
from workers.lib.num import safe_num

MAX_READS = 4
VT_SECONDS = 300
IDLE_SLEEP = 2.0
MAX_DOC_CHARS = 120_000          # ~30K tokens; plenty for decks/CIM sections

# hard cost rail: pause (don't spend) once today's LLM spend hits this many USD.
# 0/empty = unlimited. Default ~₹2,100/day — generous (a full re-extract is ~₹90).
DAILY_BUDGET_USD = float(os.environ.get("LLM_DAILY_BUDGET_USD", "25") or 0)
BUDGET_SLEEP = 300


def budget_exceeded(conn) -> bool:
    if not DAILY_BUDGET_USD:
        return False
    r = conn.execute(
        "select coalesce(sum(usd),0) s from gb_cost_log where at::date = current_date"
    ).fetchone()
    return float(r["s"]) >= DAILY_BUDGET_USD

# pricing per MTok (USD) for the cost log — update if rates change
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-pro": (1.25, 10.0),
         "fake-llm": (0.0, 0.0)}


def usd(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICE.get(model, (0.0, 0.0))
    return round(tin / 1e6 * pin + tout / 1e6 * pout, 5)


def upsert_entity(conn, etype: str, canonical: str, attrs: dict, keys: dict | None = None):
    if not canonical:
        return None
    row = conn.execute(
        """insert into gb_entity (type, canonical, attrs, keys)
           values (%s,%s,%s::jsonb,%s::jsonb)
           on conflict (type, canonical) do update
             set attrs = gb_entity.attrs || excluded.attrs,
                 keys  = gb_entity.keys  || excluded.keys
           returning id""",
        (etype, canonical.strip(), json.dumps(attrs), json.dumps(keys or {})),
    ).fetchone()
    return row["id"]


def edge(conn, src, rel, dst, envelope_id, occurred_at=None):
    if src and dst:
        conn.execute(
            "insert into gb_edge (src, rel, dst, envelope_id, occurred_at) "
            "values (%s,%s,%s,%s,%s) on conflict do nothing",
            (src, rel, dst, envelope_id, occurred_at),
        )


def fan_out(conn, envelope_id: str, env: dict, note: dict) -> None:
    """Structured note → knowledge layer."""
    company_id = upsert_entity(conn, "company", note.get("company_name") or "", {
        k: note.get(k) for k in
        ("sector", "sub_sector", "stage", "business_model",
         "hq", "website", "founded", "poc", "fitment", "aliases")
        if note.get(k) is not None
    })

    enrich_on = bool(os.environ.get("SCRAPPA_API_KEY", "").strip())

    def add_person(f, relation):
        name = (f.get("name") or "").strip()
        # write-time identity gate: skip role/section placeholders ("Active US
        # Founder", "CEO/Founder", "The Team") so they never become person nodes.
        if not is_person_name(name):
            return
        pid = upsert_entity(conn, "person", name, {
            "role": f.get("role"), "company": note.get("company_name"),
            "linkedin": f.get("linkedin"), "relation": relation,
        })
        edge(conn, pid, "works_at", company_id, envelope_id, env.get("occurred_at"))
        # async LinkedIn enrichment (decoupled; the enrich worker dedups so a
        # person is searched at most once ever). Only if Scrappa is configured
        # and we don't already have a LinkedIn for them.
        if enrich_on and pid and not f.get("linkedin"):
            queues.send(conn, queues.Q_ENRICH, {"person_id": str(pid)})

    for f in note.get("founders") or []:
        add_person(f, "founder")
    for f in note.get("key_people") or []:
        add_person(f, "contact")

    if note.get("round_type") or note.get("ask_inr_cr"):
        deal_id = upsert_entity(
            conn, "deal", f"{note.get('company_name')} — {note.get('round_type') or 'Round'}",
            {"company": note.get("company_name"), "round_type": note.get("round_type"),
             "ask_inr_cr": note.get("ask_inr_cr"),
             "valuation_inr_cr": note.get("valuation_inr_cr"), "status": "active"},
        )
        edge(conn, deal_id, "involves", company_id, envelope_id, env.get("occurred_at"))

    for metric, key, period_key in (
        ("revenue", "revenue_inr_cr", "revenue_period"),
        ("ebitda", "ebitda_inr_cr", None),
        ("valuation", "valuation_inr_cr", None),
        ("funding_ask", "ask_inr_cr", None),
    ):
        val = safe_num(note.get(key))
        if val is None or company_id is None:
            continue
        dup = conn.execute(
            "select 1 from gb_observation where envelope_id=%s and metric=%s",
            (envelope_id, metric),
        ).fetchone()
        if dup:
            continue
        conn.execute(
            """insert into gb_observation
               (entity_id, metric, value_num, unit, period, as_of, source, confidence, envelope_id)
               values (%s,%s,%s,'INR_Cr',%s,%s,%s,%s,%s)""",
            (company_id, metric, val,
             note.get(period_key) if period_key else None,
             (env.get("occurred_at") or None),
             f"document via {env.get('source')}",
             "High" if note.get("confidence") == "high" else "Medium",
             envelope_id),
        )

    for item in note.get("action_items") or []:
        dup = conn.execute(
            "select 1 from gb_task where envelope_id=%s and description=%s",
            (envelope_id, item),
        ).fetchone()
        if not dup:
            conn.execute(
                "insert into gb_task (description, company_id, envelope_id) values (%s,%s,%s)",
                (item, company_id, envelope_id),
            )


def process(conn, envelope_id: str) -> str:
    env = conn.execute("select * from gb_envelope where id=%s", (envelope_id,)).fetchone()
    if env is None:
        return "missing"
    if env["status"] not in ("preprocessed",):
        return "noop"

    rows = conn.execute(
        "select text from gb_chunk where envelope_id=%s order by seq", (envelope_id,)
    ).fetchall()
    title = env.get("title") or ""
    multimodal = False

    if rows:
        # text path — chunked email body or native PDF. The subject gives the
        # model the company name on forwarded threads ("Call Notes | Acme").
        body = "\n\n".join(r["text"] for r in rows)[:MAX_DOC_CHARS]
        doc = f"Email subject: {title}\n\n{body}" if title else body
        res = generate_json(PROMPT, doc)
        if (res.data.get("confidence") == "low") and res.model != ESCALATE_MODEL:
            print(f"[extract] {envelope_id} escalating → {ESCALATE_MODEL}", flush=True)
            res = generate_json(PROMPT, doc, model=ESCALATE_MODEL)
    else:
        # no text → image/scanned PDF deck: read it directly via Gemini multimodal
        att = conn.execute(
            "select storage_ref from gb_attachment where envelope_id=%s "
            "and text_layer = false and storage_ref is not null limit 1", (envelope_id,)
        ).fetchone()
        if not att:
            conn.execute("update gb_envelope set status='skipped', skip_reason='no_text' where id=%s",
                         (envelope_id,))
            return "empty"
        pdf = storage.download(att["storage_ref"])
        res = generate_json_from_pdf(PROMPT, pdf)
        if (res.data.get("confidence") == "low") and res.model != ESCALATE_MODEL:
            print(f"[extract] {envelope_id} escalating (pdf) → {ESCALATE_MODEL}", flush=True)
            res = generate_json_from_pdf(PROMPT, pdf, model=ESCALATE_MODEL)
        multimodal = True

    note = res.data if isinstance(res.data, dict) else {}
    conn.execute(
        "update gb_envelope set extraction=%s::jsonb, status='extracted' where id=%s",
        (json.dumps(note), envelope_id),
    )
    fan_out(conn, envelope_id, env, note)
    conn.execute(
        "insert into gb_cost_log (envelope_id, stage, model, tokens_in, tokens_out, usd) "
        "values (%s,'extract',%s,%s,%s,%s)",
        (envelope_id, res.model, res.tokens_in, res.tokens_out,
         usd(res.model, res.tokens_in, res.tokens_out)),
    )
    # image decks have no chunks — synthesize one from the note so the deck is
    # still semantically searchable (embed picks up any chunk with a null vector).
    if multimodal and not rows:
        syn = "\n".join(x for x in (
            note.get("company_name"), note.get("summary"),
            " ".join(note.get("key_metrics") or [])) if x).strip()
        if syn:
            conn.execute(
                "insert into gb_chunk (envelope_id, seq, page, text, token_est) "
                "values (%s,0,NULL,%s,%s)", (envelope_id, syn[:6000], len(syn) // 4))

    queues.send(conn, queues.Q_EMBED, {"envelope_id": envelope_id})
    tag = f"{res.model}, multimodal" if multimodal else res.model
    return f"extracted:{note.get('company_name')} ({tag})"


def run(once: bool = False) -> None:
    conn = connect()
    print(f"[extract] up · daily budget {('$'+str(DAILY_BUDGET_USD)) if DAILY_BUDGET_USD else 'unlimited'}", flush=True)
    budget_warned = False
    while True:
        if budget_exceeded(conn):
            if not budget_warned:
                print(f"[extract] daily LLM budget ${DAILY_BUDGET_USD} reached — pausing "
                      f"(set LLM_DAILY_BUDGET_USD higher to resume)", flush=True)
                budget_warned = True
            if once:
                return
            time.sleep(BUDGET_SLEEP)
            continue
        budget_warned = False
        msgs = queues.read(conn, queues.Q_EXTRACT, vt=VT_SECONDS, qty=3)
        if not msgs:
            if once:
                return
            time.sleep(IDLE_SLEEP)
            continue
        for m in msgs:
            eid = m["message"].get("envelope_id")
            try:
                outcome = process(conn, eid)
                queues.archive(conn, queues.Q_EXTRACT, m["msg_id"])
                print(f"[extract] {eid} → {outcome}", flush=True)
            except Exception as exc:  # noqa: BLE001
                if m["read_ct"] >= MAX_READS:
                    queues.dead_letter(conn, "extract", eid, m["message"], repr(exc), m["read_ct"])
                    conn.execute("update gb_envelope set status='failed' where id=%s", (eid,))
                    queues.archive(conn, queues.Q_EXTRACT, m["msg_id"])
                    print(f"[extract] {eid} → DLQ ({exc})", flush=True)
                else:
                    queues.backoff(m["read_ct"])
                    print(f"[extract] {eid} retry {m['read_ct']} ({exc})", flush=True)


if __name__ == "__main__":
    run(once="--once" in sys.argv)
