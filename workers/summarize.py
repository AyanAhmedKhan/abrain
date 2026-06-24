"""gbrain · capped, cached AI one-line summaries for ORG nodes (past/other
employers, which have no description). Companies already carry extraction
summaries, so they're left alone.

Best practice / cost control:
  • only orgs WITHOUT a summary and WITH ≥1 connection (skip orphans);
  • hubs first (most connections); HARD per-run cap (SUMMARY_MAX_PER_RUN, def 40);
  • cached on attrs.summary + attrs.summary_src='ai' → generated ONCE, never again;
  • Flash, ~₹0.05 each; FAKE-mode makes no calls.

  python -m workers.summarize --once [N]
"""

from __future__ import annotations

import os
import sys

from workers.lib import gemini
from workers.lib.db import connect

MAX_PER_RUN = int(os.environ.get("SUMMARY_MAX_PER_RUN", "40"))
USD_INR = 85.0

_PROMPT = (
    'In ONE short factual sentence, say what the organization "{name}" is. '
    "Roles people held there: {ctx}. "
    'If you are not reasonably sure, reply EXACTLY: "{name} — organization." '
    "Output only the sentence, no preamble."
)


def _candidates(conn, limit):
    return conn.execute(
        """select e.id, e.canonical,
                  (select count(*) from gb_edge where dst=e.id) as deg
             from gb_entity e
            where e.type='org' and coalesce(e.attrs->>'summary','')=''
              and exists (select 1 from gb_edge where dst=e.id)
            order by deg desc, e.canonical
            limit %s""", (limit,)).fetchall()


def _context(conn, eid) -> str:
    rows = conn.execute(
        "select distinct ed.props->>'title' as t from gb_edge ed "
        "where ed.dst=%s and ed.rel='works_at' and coalesce(ed.props->>'title','')<>'' limit 6",
        (eid,)).fetchall()
    return ", ".join(r["t"] for r in rows) or "(none)"


def run(limit: int = MAX_PER_RUN) -> None:
    conn = connect()
    n, cost = 0, 0.0
    for r in _candidates(conn, limit):
        prompt = _PROMPT.format(name=r["canonical"], ctx=_context(conn, r["id"]))
        out = (gemini.generate_text(prompt) or "").strip().strip('"')
        if not out:
            continue
        conn.execute(
            "update gb_entity set attrs = attrs || jsonb_build_object('summary', %s::text, 'summary_src', 'ai') "
            "where id=%s", (out[:400], r["id"]))
        cost += (len(prompt) + len(out)) / 4 / 1e6 * 2.5 * USD_INR
        n += 1
        print(f"[summarize] {r['canonical']}: {out[:90]}", flush=True)
    print(f"[summarize] {n} summarized · ~₹{round(cost, 2)}", flush=True)


if __name__ == "__main__":
    nums = [a for a in sys.argv[1:] if a.isdigit()]
    run(limit=int(nums[0]) if nums else MAX_PER_RUN)
