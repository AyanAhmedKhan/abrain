"""gbrain · resolve worker (Stage 6 — identity resolution & graph build).

Reads gb_q_resolve. Deterministic-first, $0 for the vast majority:

  1. ACTORS  — the envelope's from/participants/owners are matched to
     person entities by email/phone key (created if new), with
     `sent_by` / `attended` edges.
  2. DOMAINS — a sender's email domain links them to a company
     (works_at) when a company carries that domain key.
  3. MENTIONS — entity canonicals (companies, deals from the spine)
     found in the title/body produce `mentions` edges.
  4. MEETINGS — calendar envelopes become meeting entities with
     attended edges per participant.
  5. EXTRACTION links — the analyzed company (if any) is linked to the
     sender (`shown_to` reversed as sent_by → mentions chain).

No LLM call here. The residual-ambiguity Gemini resolver is a later
add once deterministic coverage is measured (<90%).

Run:  python -m workers.resolve [--once]
"""

from __future__ import annotations

import json
import re
import sys
import time

from workers.lib import queues
from workers.lib.db import connect

MAX_READS = 4
VT_SECONDS = 120
IDLE_SLEEP = 2.0

# public mailbox domains never imply a company
GENERIC_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.in",
                   "outlook.com", "hotmail.com", "icloud.com", "proton.me",
                   "protonmail.com", "rediffmail.com", "live.com", "aol.com"}

_EMAIL = re.compile(r"<?([\w.+-]+@[\w-]+\.[\w.-]+)>?")


def email_of(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _EMAIL.search(raw)
    return m.group(1).lower() if m else None


def upsert(conn, etype: str, canonical: str, attrs: dict | None = None,
           keys: dict | None = None):
    if not canonical or not canonical.strip():
        return None
    row = conn.execute(
        """insert into gb_entity (type, canonical, attrs, keys)
           values (%s,%s,%s::jsonb,%s::jsonb)
           on conflict (type, canonical) do update
             set attrs = gb_entity.attrs || excluded.attrs,
                 keys  = gb_entity.keys  || excluded.keys
           returning id""",
        (etype, canonical.strip(), json.dumps(attrs or {}), json.dumps(keys or {})),
    ).fetchone()
    return row["id"]


def edge(conn, src, rel, dst, envelope_id, occurred_at=None):
    if src and dst and src != dst:
        conn.execute(
            "insert into gb_edge (src, rel, dst, envelope_id, occurred_at) "
            "values (%s,%s,%s,%s,%s) on conflict do nothing",
            (src, rel, dst, envelope_id, occurred_at),
        )


def person_for(conn, identifier: str, display: str | None = None):
    """Find a person by email/phone key, or create one."""
    em = email_of(identifier)
    key_val = em or identifier
    found = conn.execute(
        "select id from gb_entity where type='person' and "
        "(keys->>'email' = %s or keys->>'phone' = %s) limit 1",
        (key_val, key_val),
    ).fetchone()
    if found:
        return found["id"]
    name = display or (em.split("@")[0].replace(".", " ").title() if em else identifier)
    keys = {"email": em} if em else {"phone": identifier}
    return upsert(conn, "person", name, {}, keys)


def company_for_domain(conn, em: str | None):
    if not em or "@" not in em:
        return None
    domain = em.split("@", 1)[1].lower()
    if domain in GENERIC_DOMAINS:
        return None
    row = conn.execute(
        "select id from gb_entity where type='company' and keys->>'domain' = %s limit 1",
        (domain,),
    ).fetchone()
    return row["id"] if row else None


def mention_targets(conn) -> list[dict]:
    """Companies + deals worth scanning for (the spine). Cached per loop."""
    return conn.execute(
        "select id, type, canonical from gb_entity "
        "where type in ('company','deal') and length(canonical) >= 4"
    ).fetchall()


def process(conn, envelope_id: str, targets: list[dict]) -> str:
    env = conn.execute("select * from gb_envelope where id=%s", (envelope_id,)).fetchone()
    if env is None:
        return "missing"
    if env["status"] not in ("embedded", "extracted"):
        return "noop"

    occurred = env.get("occurred_at")
    actors = env.get("actors") or {}
    n_edges = 0

    # 1+2 ── actors → people; sender domain → company
    sender_raw = actors.get("from") or actors.get("organizer")
    sender_pid = None
    if sender_raw:
        sender_pid = person_for(conn, str(sender_raw), actors.get("from_name"))
        doc_node = upsert(conn, "document", f"{env['source']}:{env['source_id']}",
                          {"title": env.get("title")})
        edge(conn, sender_pid, "sent_by", doc_node, envelope_id, occurred)
        comp = company_for_domain(conn, email_of(str(sender_raw)))
        if comp:
            edge(conn, sender_pid, "works_at", comp, envelope_id, occurred)
            n_edges += 1

    participants = (actors.get("participants") or []) + (actors.get("owners") or [])

    # 4 ── calendar events become meetings with attendance
    if env.get("kind") == "event":
        meeting_id = upsert(conn, "meeting", env.get("title") or f"event:{env['source_id']}",
                            {"occurred_at": str(occurred) if occurred else None,
                             "source_event_id": env["source_id"]})
        for p in participants:
            pid = person_for(conn, str(p))
            edge(conn, pid, "attended", meeting_id, envelope_id, occurred)
            n_edges += 1
        if sender_pid:
            edge(conn, sender_pid, "organized", meeting_id, envelope_id, occurred)
    else:
        for p in participants:
            person_for(conn, str(p))

    # 3 ── mentions: scan title + body for known companies/deals
    text = f"{env.get('title') or ''}\n{env.get('body_clean') or ''}".lower()
    doc_node = upsert(conn, "document", f"{env['source']}:{env['source_id']}",
                      {"title": env.get("title")})
    for t in targets:
        if t["canonical"].lower() in text:
            edge(conn, doc_node, "mentions", t["id"], envelope_id, occurred)
            n_edges += 1

    # 5 ── extraction company ↔ this document
    note = env.get("extraction")
    note = note if isinstance(note, dict) else {}
    if note.get("company_name"):
        comp = conn.execute(
            "select id from gb_entity where type='company' and canonical=%s",
            (note["company_name"],),
        ).fetchone()
        if comp:
            edge(conn, doc_node, "about", comp["id"], envelope_id, occurred)
            if sender_pid:
                edge(conn, sender_pid, "mentions", comp["id"], envelope_id, occurred)
            n_edges += 1

    conn.execute("update gb_envelope set status='indexed' where id=%s", (envelope_id,))
    return f"resolved:{n_edges} edges"


def run(once: bool = False) -> None:
    conn = connect()
    print("[resolve] up", flush=True)
    targets: list[dict] = []
    refresh = 0.0
    while True:
        msgs = queues.read(conn, queues.Q_RESOLVE, vt=VT_SECONDS, qty=10)
        if not msgs:
            if once:
                return
            time.sleep(IDLE_SLEEP)
            continue
        if time.time() - refresh > 60:
            targets = mention_targets(conn)
            refresh = time.time()
        for m in msgs:
            eid = m["message"].get("envelope_id")
            try:
                outcome = process(conn, eid, targets or mention_targets(conn))
                queues.archive(conn, queues.Q_RESOLVE, m["msg_id"])
                print(f"[resolve] {eid} → {outcome}", flush=True)
            except Exception as exc:  # noqa: BLE001
                if m["read_ct"] >= MAX_READS:
                    queues.dead_letter(conn, "resolve", eid, m["message"], repr(exc), m["read_ct"])
                    conn.execute("update gb_envelope set status='failed' where id=%s", (eid,))
                    queues.archive(conn, queues.Q_RESOLVE, m["msg_id"])
                    print(f"[resolve] {eid} → DLQ ({exc})", flush=True)
                else:
                    queues.backoff(m["read_ct"])
                    print(f"[resolve] {eid} retry {m['read_ct']} ({exc})", flush=True)


if __name__ == "__main__":
    run(once="--once" in sys.argv)
