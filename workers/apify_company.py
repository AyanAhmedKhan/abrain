"""gbrain · LinkedIn COMPANY profile ingestion (Apify scraper) — ZERO LLM tokens.

Sibling of workers/apify_linkedin.py (person profiles). Parses the Apify LinkedIn
Company Scraper JSON into the tracked company entity, deterministically:
  • DB     → gb_company_profile (flattened columns + locations/raw JSONB) and
             mirrored quick-fields on gb_entity.attrs (linkedin, industry,
             employees, followers, logo, company_scraped negative cache)
  • CRM/vault → surfaced via gb_company_full (dashboard company page + Obsidian)

Most-optimized by design:
  • company LinkedIn URLs are harvested FOR FREE from person experience entries
    (apify_linkedin._attach_company_url) — no search needed for any company that
    has an employee in the brain;
  • each company is scraped AT MOST ONCE EVER (attrs.company_scraped);
  • only companies we already TRACK are scraped (never creates a node);
  • decoupled queue (gb_q_company) so it never blocks the paid pipeline.

Fetch modes:
  worker      — continuous: consume gb_q_company + backfill tracked companies that
                have a LinkedIn URL but no profile yet (one Apify call each).
  scrape URL  — one company via the Apify actor.
  import FILE — ingest a JSON file/dir the actor already produced (no token needed).

Env: APIFY_TOKEN, APIFY_COMPANY_ACTOR_ID (e.g. harvestapi~linkedin-company),
     APIFY_COMPANY_INPUT_FIELD (default 'queries'), APIFY_MAX_PER_RUN (default 50).
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time

import httpx

from workers.lib import queues
from workers.lib.db import connect
from workers.apify_linkedin import _match_company, _check_apify_items, ApifyError  # shared matcher + actor-error guard

MAX_PER_RUN = int(os.environ.get("APIFY_MAX_PER_RUN", "50"))
IDLE_SLEEP = 5.0
NO_KEY_SLEEP = 300
VT_SECONDS = 300
MAX_READS = 3


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── parse (deterministic, matches harvestapi linkedin-company output) ──

def parse_company(j: dict) -> dict:
    name = (j.get("name") or j.get("companyName") or "").strip()

    inds = j.get("industries") or []
    if isinstance(inds, list) and inds:
        i0 = inds[0]
        industry = (i0.get("name") or i0.get("title")) if isinstance(i0, dict) else str(i0)
    else:
        industry = j.get("industry")

    rng = j.get("employeeCountRange") or {}
    if isinstance(rng, dict) and (rng.get("start") or rng.get("end")):
        s, e = rng.get("start"), rng.get("end")
        company_size = f"{s}-{e}" if e else f"{s}+"
    else:
        company_size = j.get("companySize") or j.get("staffCountRange")

    fo = j.get("foundedOn") or {}
    founded = (str(fo.get("year")) if isinstance(fo, dict) and fo.get("year")
               else (str(j.get("founded")) if j.get("founded") else None))

    hq = None
    locs = j.get("locations") or []
    if isinstance(locs, list) and locs and isinstance(locs[0], dict):
        l0 = locs[0]
        hq = ", ".join(x for x in (l0.get("city"), l0.get("geographicArea")
                                   or l0.get("country")) if x) or None
    if not hq and isinstance(j.get("headquarter"), dict):
        h = j["headquarter"]
        hq = ", ".join(x for x in (h.get("city"), h.get("geographicArea"),
                                   h.get("country")) if x) or None

    spec = j.get("specialities") or j.get("specialties") or []
    if isinstance(spec, str):
        spec = [s.strip() for s in spec.split(",") if s.strip()]

    logo = j.get("logo")
    if not logo and isinstance(j.get("logos"), list) and j["logos"]:
        logo = (j["logos"][0] or {}).get("url")

    return {
        "name": name,
        "linkedin_url": (j.get("linkedinUrl") or "").rstrip("/") or None,
        "public_id": j.get("universalName") or j.get("publicIdentifier"),
        "tagline": j.get("tagline"),
        "description": j.get("description") or j.get("about"),
        "industry": industry,
        "company_size": company_size,
        "employee_count": _int(j.get("employeeCount") or j.get("staffCount")),
        "hq": hq,
        "founded": founded,
        "website": j.get("website") or j.get("websiteUrl") or j.get("callToActionUrl"),
        "followers": _int(j.get("followerCount") or j.get("followers")),
        "specialties": spec,
        "locations": locs if isinstance(locs, list) else [],
        "logo_url": logo,
    }


# ── store (DB + entity attrs) ────────────────────────────────

def store_company(conn, j: dict, entity_id=None) -> str:
    p = parse_company(j)
    cid = entity_id or _match_company(conn, p["name"])
    if not cid:
        return f"no-entity ({p['name']})"  # we only enrich companies we track

    # mirror LinkedIn-authoritative quick fields onto the entity + negative cache
    attrs = {k: v for k, v in {
        "linkedin": p["linkedin_url"], "industry": p["industry"],
        "employees": p["employee_count"], "company_size": p["company_size"],
        "company_followers": p["followers"], "logo": p["logo_url"],
        "company_public_id": p["public_id"], "company_scraped": "apify",
    }.items() if v is not None}
    conn.execute("update gb_entity set attrs = attrs || %s::jsonb where id=%s",
                 (json.dumps(attrs), cid))

    conn.execute(
        """insert into gb_company_profile
             (company_id, linkedin_url, public_id, tagline, description, industry,
              company_size, employee_count, hq, founded, website, followers,
              specialties, locations, logo_url, raw, scraped_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb, now())
           on conflict (company_id) do update set
             linkedin_url=excluded.linkedin_url, public_id=excluded.public_id,
             tagline=excluded.tagline, description=excluded.description,
             industry=excluded.industry, company_size=excluded.company_size,
             employee_count=excluded.employee_count, hq=excluded.hq,
             founded=excluded.founded, website=excluded.website,
             followers=excluded.followers, specialties=excluded.specialties,
             locations=excluded.locations, logo_url=excluded.logo_url,
             raw=excluded.raw, scraped_at=now()""",
        (cid, p["linkedin_url"], p["public_id"], p["tagline"], p["description"],
         p["industry"], p["company_size"], p["employee_count"], p["hq"], p["founded"],
         p["website"], p["followers"], p["specialties"], json.dumps(p["locations"]),
         p["logo_url"], json.dumps(j)),
    )
    return (f"{p['name'] or cid}: {p['industry'] or '—'} · "
            f"{p['employee_count'] or '?'} emp · {p['followers'] or 0} followers")


# ── Apify API ────────────────────────────────────────────────

def apify_fetch_company(urls: list[str]) -> list[dict]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    actor = os.environ.get("APIFY_COMPANY_ACTOR_ID", "").strip()
    if not token or not actor:
        raise RuntimeError("APIFY_TOKEN / APIFY_COMPANY_ACTOR_ID not set in .env")
    field = os.environ.get("APIFY_COMPANY_INPUT_FIELD", "queries")
    payload: dict = {field: urls}
    r = httpx.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        params={"token": token}, json=payload, timeout=300)
    if r.status_code not in (200, 201):
        raise ApifyError(f"apify {r.status_code}: {r.text[:200]}")
    data = r.json()
    return _check_apify_items(data if isinstance(data, list) else [data])


# ── worker (queue + backfill) ────────────────────────────────

def _ready() -> bool:
    return bool(os.environ.get("APIFY_TOKEN", "").strip()
                and os.environ.get("APIFY_COMPANY_ACTOR_ID", "").strip())


def process(conn, company_id, url=None) -> str:
    e = conn.execute("select id, canonical, attrs from gb_entity where id=%s and type='company'",
                     (company_id,)).fetchone()
    if e is None:
        return "missing"
    a = e["attrs"] or {}
    if a.get("company_scraped"):
        return "noop"
    url = url or a.get("linkedin")
    if not url:
        return "no-url"
    items = apify_fetch_company([url])
    if not items:
        conn.execute("update gb_entity set attrs = attrs || '{\"company_scraped\":\"none\"}'::jsonb where id=%s",
                     (company_id,))
        return "none"
    return store_company(conn, items[0], entity_id=company_id)


def run(once: bool = False) -> None:
    conn = connect()
    print(f"[company] up · apify={'ready' if _ready() else 'MISSING token/actor'}", flush=True)
    while True:
        if not _ready():
            if once:
                return
            time.sleep(NO_KEY_SLEEP)
            continue
        try:
            msgs = queues.read(conn, queues.Q_COMPANY, vt=VT_SECONDS, qty=3)
            if msgs:
                for m in msgs:
                    cid = m["message"].get("company_id")
                    try:
                        print(f"[company] {process(conn, cid, m['message'].get('url'))}", flush=True)
                        queues.archive(conn, queues.Q_COMPANY, m["msg_id"])
                    except ApifyError:
                        raise  # actor/plan limit → pause; leave msg for later retry
                    except Exception as exc:  # noqa: BLE001
                        if m["read_ct"] >= MAX_READS:
                            queues.dead_letter(conn, "company", cid, m["message"], repr(exc), m["read_ct"])
                            queues.archive(conn, queues.Q_COMPANY, m["msg_id"])
                            print(f"[company] {cid} → DLQ ({exc})", flush=True)
                        else:
                            queues.backoff(m["read_ct"])
                            print(f"[company] {cid} retry ({exc})", flush=True)
                continue
            # backfill: tracked companies with a LinkedIn URL but no profile yet
            ids = [r["id"] for r in conn.execute(
                "select id from gb_entity where type='company' "
                "and coalesce(attrs->>'linkedin','')<>'' and attrs->>'company_scraped' is null "
                "order by canonical limit %s", (MAX_PER_RUN,)).fetchall()]
            for cid in ids:
                print(f"[company] {process(conn, cid)}", flush=True)
            if not ids:
                if once:
                    return
                time.sleep(IDLE_SLEEP)
        except ApifyError as exc:
            print(f"[company] PAUSED — Apify actor error: {exc} "
                  f"(upgrade the harvestapi plan to continue scraping)", flush=True)
            if once:
                return
            time.sleep(NO_KEY_SLEEP)


def import_path(conn, path) -> int:
    files = glob.glob(os.path.join(path, "*.json")) if os.path.isdir(path) else [path]
    n = 0
    for f in files:
        data = json.load(open(f, encoding="utf-8"))
        for item in (data if isinstance(data, list) else [data]):
            print(f"[company] {store_company(conn, item)}", flush=True)
            n += 1
    return n


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "worker"
    conn = connect()
    if cmd == "worker":
        run(once="--once" in sys.argv)
    elif cmd == "import":
        print(f"[company] imported {import_path(conn, sys.argv[2])} companies", flush=True)
    elif cmd == "scrape":
        for item in apify_fetch_company([sys.argv[2]]):
            print(f"[company] {store_company(conn, item)}", flush=True)
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
