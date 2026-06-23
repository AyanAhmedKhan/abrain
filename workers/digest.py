"""gbrain · weekly digest — follow-ups due, new deals, companies going quiet,
fresh financials. Decoupled + provider-agnostic: always logs the digest; emails
it only when SMTP is configured (so it never hard-depends on a mail provider).

Run:  python -m workers.digest            # build + log (+ email if SMTP set)
      python -m workers.digest --print    # just print the text digest

Env (optional, to enable email):
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS,
  DIGEST_FROM (default SMTP_USER), DIGEST_TO (comma-separated; default the user).
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage

from workers.lib.db import connect

QUIET_DAYS = int(os.environ.get("DIGEST_QUIET_DAYS", "21"))


def gather(conn) -> dict:
    overdue = conn.execute(
        """select description, company, due_date from gb_open_tasks
            where overdue order by due_date asc limit 25""").fetchall()
    due_soon = conn.execute(
        """select description, company, due_date from gb_open_tasks
            where due_date is not null and not overdue
              and due_date <= current_date + interval '7 days'
            order by due_date asc limit 25""").fetchall()
    new_deals = conn.execute(
        """with firstseen as (
             select extraction->>'company_name' company, min(occurred_at) seen
               from gb_envelope where status='indexed' and coalesce(extraction->>'company_name','')<>''
              group by 1)
           select c.company, c.sector, c.ask_inr_cr from gb_company_card c
             join firstseen f on f.company=c.company
            where f.seen >= now() - interval '7 days' order by f.seen desc""").fetchall()
    quiet = conn.execute(
        """select company, last_interaction from gb_company_card
            where has_deal and last_interaction is not null
              and last_interaction < current_date - make_interval(days => %s)
            order by last_interaction asc limit 20""", (QUIET_DAYS,)).fetchall()
    fresh = conn.execute(
        """select company, metric, value_num, period from gb_company_financials
            where created_at >= now() - interval '7 days' order by created_at desc limit 25""").fetchall()
    return {"overdue": overdue, "due_soon": due_soon, "new_deals": new_deals,
            "quiet": quiet, "fresh": fresh}


def _cr(v):
    try:
        n = float(v); return f"₹{int(n) if n == int(n) else round(n, 1)} Cr"
    except (TypeError, ValueError):
        return ""


def render_text(d: dict) -> str:
    L = ["gbrain weekly digest", "=" * 22, ""]
    L += [f"⚑ Overdue follow-ups ({len(d['overdue'])})"]
    L += [f"   • {t['description'][:90]}  [{t['company'] or '—'}, due {str(t['due_date'])[:10]}]" for t in d["overdue"][:10]] or ["   (none)"]
    L += ["", f"⏰ Due this week ({len(d['due_soon'])})"]
    L += [f"   • {t['description'][:90]}  [{t['company'] or '—'}, {str(t['due_date'])[:10]}]" for t in d["due_soon"][:10]] or ["   (none)"]
    L += ["", f"✦ New this week ({len(d['new_deals'])})"]
    L += [f"   • {x['company']}  {x['sector'] or ''} {_cr(x['ask_inr_cr'])}".rstrip() for x in d["new_deals"][:15]] or ["   (none)"]
    L += ["", f"💤 Going quiet ({QUIET_DAYS}d+)  ({len(d['quiet'])})"]
    L += [f"   • {x['company']}  (last {str(x['last_interaction'])[:10]})" for x in d["quiet"][:15]] or ["   (none)"]
    L += ["", f"📈 Fresh financials ({len(d['fresh'])})"]
    L += [f"   • {x['company']}: {x['metric']} {_cr(x['value_num'])} {x['period'] or ''}".rstrip() for x in d["fresh"][:15]] or ["   (none)"]
    return "\n".join(L)


def send_email(text: str) -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return False
    to = [a.strip() for a in os.environ.get("DIGEST_TO", "tech@discoverventures.in").split(",") if a.strip()]
    msg = EmailMessage()
    msg["Subject"] = "gbrain · weekly digest"
    msg["From"] = os.environ.get("DIGEST_FROM") or os.environ.get("SMTP_USER", "")
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
        s.send_message(msg)
    return True


def main():
    conn = connect()
    text = render_text(gather(conn))
    if "--print" in sys.argv:
        print(text); return
    print(text, flush=True)  # always to journal
    try:
        print(f"[digest] {'emailed' if send_email(text) else 'SMTP not configured — log only'}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[digest] email failed: {exc!r}", flush=True)


if __name__ == "__main__":
    main()
