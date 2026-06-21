"""gbrain · enrichment worker (Scrappa search).

PRIMARY: find each person's LinkedIn profile URL and write it where it shows —
the person entity (→ dashboard People + company detail) and the company's
extraction founders[] (→ company card + Obsidian vault note).

Frugal by design (best practice — minimal, no duplicate API calls):
  • runs DURING processing: extract enqueues a person to gb_q_enrich the moment
    a founder without a LinkedIn is created.
  • each person is searched AT MOST ONCE EVER — a persistent `linkedin_checked`
    flag is set whether or not a profile is found (negative cache), so a person
    appearing in 10 call notes still costs 1 credit, and 0 on re-runs.
  • a daily cap (SCRAPPA_DAILY_CAP, default 200) bounds spend; idle time backfills
    pre-existing people. No-ops entirely when SCRAPPA_API_KEY is unset.

Run:
    python -m workers.enrich worker          # continuous (systemd) — queue + idle backfill
    python -m workers.enrich persons [N]     # one-shot batch
"""

from __future__ import annotations

import json
import os
import sys
import time

from workers.lib import queues, search
from workers.lib.db import connect

DAILY_CAP = int(os.environ.get("SCRAPPA_DAILY_CAP", "200"))
IDLE_BATCH = 20
IDLE_SLEEP = 5.0
NO_KEY_SLEEP = 300
VT_SECONDS = 120
MAX_READS = 3


def _key_set() -> bool:
    return bool(os.environ.get("SCRAPPA_API_KEY", "").strip())


def _checked_today(conn) -> int:
    return conn.execute(
        "select count(*) c from gb_entity where type='person' "
        "and attrs->>'linkedin_checked' = to_char(now(),'YYYY-MM-DD')"
    ).fetchone()["c"]


def _patch_founder_linkedin(conn, company, name, li):
    """Mirror the LinkedIn into the company's extraction founders[] → shows on the
    company card and the Obsidian vault note, not just the People view."""
    if not company:
        return
    for e in conn.execute(
        "select id, extraction from gb_envelope "
        "where status='indexed' and extraction->>'company_name'=%s", (company,)
    ).fetchall():
        ex = e["extraction"] or {}
        founders = ex.get("founders") or []
        changed = False
        for f in founders:
            if (isinstance(f, dict) and not f.get("linkedin")
                    and (f.get("name") or "").strip().lower() == name.strip().lower()):
                f["linkedin"] = li
                changed = True
        if changed:
            conn.execute("update gb_envelope set extraction=%s::jsonb where id=%s",
                         (json.dumps(ex), e["id"]))


def process(conn, person_id) -> str:
    """Look up one person's LinkedIn (≤1 Scrappa call; negative-cached)."""
    e = conn.execute("select id, canonical, attrs from gb_entity where id=%s and type='person'",
                     (person_id,)).fetchone()
    if e is None:
        return "missing"
    a = e["attrs"] or {}
    if a.get("linkedin") or a.get("linkedin_checked"):
        return "noop"  # already known or already attempted — NO api call
    li = search.find_linkedin(e["canonical"], a.get("company") or "")
    # stamp checked (today) regardless of outcome → never searched again
    patch = {"linkedin_checked": "__DATE__"}
    if li:
        patch["linkedin"] = li
    conn.execute(
        "update gb_entity set attrs = attrs || jsonb_build_object('linkedin_checked', to_char(now(),'YYYY-MM-DD'))"
        + (" || jsonb_build_object('linkedin', %s::text)" if li else "")
        + " where id=%s",
        ((li, person_id) if li else (person_id,)),
    )
    if li:
        _patch_founder_linkedin(conn, a.get("company"), e["canonical"], li)
        # immediate hand-off to the Apify profile scraper for the full profile.
        # Best-effort: the scraper also backfills and dedups via attrs.profile_scraped,
        # so a duplicate/failed enqueue is harmless — never fail enrich over it.
        try:
            queues.send(conn, queues.Q_PROFILE, {"person_id": str(person_id), "url": li})
        except Exception:  # noqa: BLE001
            pass
    return f"{e['canonical']}: {li or 'none'}"


def _backfill_ids(conn, limit):
    return [r["id"] for r in conn.execute(
        "select id from gb_entity where type='person' "
        "and coalesce(attrs->>'linkedin','')='' and attrs->>'linkedin_checked' is null "
        "order by canonical limit %s", (limit,)).fetchall()]


# ── continuous worker (queue + idle backfill) ────────────────

def run(once: bool = False) -> None:
    conn = connect()
    print(f"[enrich] up · daily cap {DAILY_CAP} · key={'set' if _key_set() else 'MISSING'}", flush=True)
    while True:
        if not _key_set():
            if once:
                return
            time.sleep(NO_KEY_SLEEP)
            continue
        if _checked_today(conn) >= DAILY_CAP:
            print(f"[enrich] daily cap {DAILY_CAP} reached — pausing", flush=True)
            if once:
                return
            time.sleep(NO_KEY_SLEEP)
            continue

        msgs = queues.read(conn, queues.Q_ENRICH, vt=VT_SECONDS, qty=5)
        if msgs:
            for m in msgs:
                pid = m["message"].get("person_id")
                try:
                    out = process(conn, pid)
                    queues.archive(conn, queues.Q_ENRICH, m["msg_id"])
                    print(f"[enrich] {out}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    if m["read_ct"] >= MAX_READS:
                        queues.dead_letter(conn, "enrich", pid, m["message"], repr(exc), m["read_ct"])
                        queues.archive(conn, queues.Q_ENRICH, m["msg_id"])
                        print(f"[enrich] {pid} → DLQ ({exc})", flush=True)
                    else:
                        queues.backoff(m["read_ct"])
                        print(f"[enrich] {pid} retry {m['read_ct']} ({exc})", flush=True)
            continue

        # idle: backfill pre-existing people (bounded by remaining daily cap)
        remaining = max(0, DAILY_CAP - _checked_today(conn))
        ids = _backfill_ids(conn, min(IDLE_BATCH, remaining))
        for pid in ids:
            try:
                print(f"[enrich] {process(conn, pid)}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[enrich] backfill {pid} error: {exc!r}", flush=True)
                break  # likely auth/credit — stop
        if not ids:
            if once:
                return
            time.sleep(IDLE_SLEEP)


# ── one-shot CLI (batch / company) ───────────────────────────

def enrich_persons(conn, limit) -> int:
    done = 0
    for pid in _backfill_ids(conn, limit):
        out = process(conn, pid)
        print(f"[enrich] {out}", flush=True)
        if ": none" not in out and out != "noop":
            done += 1
    return done


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "worker"
    conn = connect()
    if cmd == "worker":
        run(once="--once" in sys.argv)
    elif cmd == "persons":
        n = enrich_persons(conn, int(sys.argv[2]) if len(sys.argv) > 2 else DAILY_CAP)
        print(f"[enrich] done ({n} found)", flush=True)
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
