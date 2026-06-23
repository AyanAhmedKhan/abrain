"""gbrain · LinkedIn profile ingestion (Apify scraper) — ZERO LLM tokens.

Parses the Apify LinkedIn Profile Scraper JSON into a first-class person record
and stores it everywhere, deterministically (pure mapping, no Gemini):
  • DB     → gb_person_profile (flattened columns + experience/education/skills/
             certs as JSONB + full raw) and mirrored quick-fields on gb_entity.attrs
  • graph  → person —works_at→ company edges for jobs whose company already exists
             as an entity (links people to tracked deal companies)
  • vault/CRM → surfaced via gb_person_card / gb_person_full (dashboard + Obsidian)

Each person is scraped at most once (attrs.profile_scraped negative cache).

Fetch modes (chosen: Apify API, everyone):
  worker      — continuous: consume gb_q_profile + backfill people with a LinkedIn
                URL but no profile yet (one Apify call each).
  scrape URL  — one profile via the Apify actor.
  import FILE — ingest a JSON file/dir the actor already produced (no token needed).

Env: APIFY_TOKEN, APIFY_ACTOR_ID (e.g. harvestapi~linkedin-profile-scraper),
     APIFY_INPUT_FIELD (default 'queries' — harvestapi's URL/slug field),
     APIFY_SCRAPER_MODE (optional — pins the actor's pricing tier, e.g.
     'Profile details no email ($4 per 1k)'), APIFY_MAX_PER_RUN (default 50).
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time

import httpx

from workers.lib import queues
from workers.lib.db import connect

# company-name normalisation for fuzzy graph linking ("Dexter Capital Advisors"
# → "Dexter Capital"). Strip legal/industry suffixes, punctuation, case.
_CO_SUFFIX = re.compile(
    r"\b(advisors?|capital|ventures?|partners?|technolog(?:y|ies)|tech|limited|ltd|"
    r"pvt|private|inc|llp|llc|fund|funds|group|company|co|solutions|labs|systems|"
    r"india|global|holdings?|enterprises?)\b", re.I)


def _norm_co(s: str | None) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = _CO_SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_li_url(u: str | None) -> str | None:
    """Canonicalise a LinkedIn URL for the Apify actor: drop query/fragment and
    trailing slash, and normalise the country subdomain (in./uk./jp.…) to www.
    harvestapi reliably resolves www URLs but returns empty for country-prefixed
    or trailing-slash variants — this is what made ~60% of scrapes 'no-name'."""
    if not u:
        return u
    u = u.strip().split("?")[0].split("#")[0].rstrip("/")
    u = re.sub(r"^https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", u, flags=re.I)
    u = re.sub(r"^https?://linkedin\.com", "https://www.linkedin.com", u, flags=re.I)
    return u


def _match_company(conn, cn: str | None):
    """Map a LinkedIn company name to an existing company entity. Returns entity
    id or None (NEVER creates a node). Tolerant of: legal/industry suffixes
    ("Dexter Capital Advisors" → "Dexter Capital"), aliases (attrs.aliases, e.g.
    "Dexter Ventures"), and duplicate entities — when several entities share the
    same normalized core they are the same firm under name variants, so we link
    to the most-connected one (the canonical hub) rather than a thin duplicate."""
    if not cn or not cn.strip():
        return None
    low = cn.strip().lower()
    core = _norm_co(cn)
    rows = conn.execute(
        "select id, canonical, attrs, "
        "(select count(*) from gb_edge where dst = e.id) as deg "
        "from gb_entity e where type='company'").fetchall()
    cands = []  # (quality, deg, id, core)
    for r in rows:
        cand = r["canonical"] or ""
        aliases = [a for a in ((r["attrs"] or {}).get("aliases") or []) if isinstance(a, str)]
        c2 = _norm_co(cand)
        if cand.lower() == low or low in {a.lower() for a in aliases}:
            q = 3                                   # exact canonical or alias
        elif core and len(core) >= 3 and (c2 == core or core in {_norm_co(a) for a in aliases}):
            q = 2                                   # same normalized core
        elif core and len(core) >= 4 and c2 and (core in c2 or c2 in core):
            q = 1                                   # core substring (looser)
        else:
            continue
        cands.append((q, r["deg"], r["id"], c2))
    if not cands:
        return None
    # same-firm collapse: entities whose core equals the query core are name
    # variants of one firm → pick the most-connected (the real hub).
    same = [c for c in cands if core and c[3] == core]
    if same:
        return max(same, key=lambda c: c[1])[2]
    return max(cands, key=lambda c: (c[0], c[1]))[2]

MAX_PER_RUN = int(os.environ.get("APIFY_MAX_PER_RUN", "50"))
IDLE_SLEEP = 5.0
NO_KEY_SLEEP = 300
VT_SECONDS = 300
MAX_READS = 3


# ── parse (deterministic) ────────────────────────────────────

def _exp(e: dict) -> dict:
    return {k: e.get(k) for k in
            ("position", "companyName", "companyLinkedinUrl", "companyId",
             "companyUniversalName", "companyLogo", "location", "employmentType",
             "workplaceType", "duration", "description")
            } | {"start": (e.get("startDate") or {}).get("text"),
                 "end": (e.get("endDate") or {}).get("text"),
                 "skills": e.get("skills") or []}


def _edu(e: dict) -> dict:
    return {k: e.get(k) for k in ("schoolName", "schoolLinkedinUrl", "degree",
                                  "fieldOfStudy", "period", "insights")}


def _cert(c: dict) -> dict:
    return {k: c.get(k) for k in ("title", "issuedBy", "issuedAt", "link")}


def _honor(h: dict) -> dict:
    return {k: h.get(k) for k in ("title", "issuedBy", "issuedAt", "description")}


_COUNTRY = {  # common ISO-3166 codes → full name (else fall back to the raw code)
    "IN": "India", "US": "United States", "GB": "United Kingdom", "SG": "Singapore",
    "AE": "United Arab Emirates", "CA": "Canada", "AU": "Australia", "DE": "Germany",
    "FR": "France", "NL": "Netherlands", "CH": "Switzerland", "JP": "Japan",
    "CN": "China", "HK": "Hong Kong", "ID": "Indonesia", "MY": "Malaysia",
    "PH": "Philippines", "TH": "Thailand", "VN": "Vietnam", "BD": "Bangladesh",
    "PK": "Pakistan", "LK": "Sri Lanka", "NP": "Nepal", "SA": "Saudi Arabia",
    "IL": "Israel", "IE": "Ireland", "SE": "Sweden", "ES": "Spain", "IT": "Italy",
    "BR": "Brazil", "ZA": "South Africa", "NZ": "New Zealand", "KR": "South Korea",
}


def parse_profile(j: dict) -> dict:
    name = " ".join(x for x in (j.get("firstName"), j.get("lastName")) if x).strip() \
        or (j.get("name") or "").strip() \
        or (j.get("publicIdentifier") or "").replace("-", " ").strip().title()
    name = re.sub(r"\s+", " ", name)
    locobj = j.get("location") or {}
    loc = locobj.get("parsed") or {}
    # location: prefer the parsed city/country, then split the raw LinkedIn text
    # ("Mumbai, Maharashtra, India" → city=Mumbai, country=India), then map a
    # bare country code ("IN" → "India").
    cc = (loc.get("countryCode") or locobj.get("countryCode") or "").upper()
    city = loc.get("city") or loc.get("text")
    country = loc.get("country") or loc.get("countryFull")
    if not city or not country:
        parts = [s.strip() for s in (locobj.get("linkedinText") or "").split(",") if s.strip()]
        if parts:
            city = city or parts[0]
            if not country and len(parts) > 1:
                country = parts[-1]
    country = country or _COUNTRY.get(cc, cc or None)
    exp = j.get("experience") or j.get("currentPosition") or []
    cur = (j.get("currentPosition") or exp or [{}])[0] if (j.get("currentPosition") or exp) else {}
    skills = [s.get("name") for s in (j.get("skills") or []) if isinstance(s, dict) and s.get("name")]
    return {
        "name": name,
        "linkedin_url": j.get("linkedinUrl"),
        "public_id": j.get("publicIdentifier"),
        "headline": j.get("headline"),
        "about": j.get("about"),
        "location_city": city,
        "location_country": country,
        "current_title": cur.get("position"),
        "current_company": cur.get("companyName"),
        "current_company_id": cur.get("companyId"),
        "photo_url": j.get("photo") or (j.get("profilePicture") or {}).get("url"),
        "followers": j.get("followerCount"),
        "connections": j.get("connectionsCount"),
        "skills": skills,
        "experience": [_exp(e) for e in (j.get("experience") or [])],
        "education": [_edu(e) for e in (j.get("education") or [])],
        "certifications": [_cert(c) for c in (j.get("certifications") or [])],
        "honors": [_honor(h) for h in (j.get("honorsAndAwards") or [])],
        "projects": [{"title": p.get("title"), "description": p.get("description")}
                     for p in (j.get("projects") or [])],
    }


# ── store (DB + entity attrs + graph) ────────────────────────

def store_profile(conn, j: dict, person_id=None) -> str:
    p = parse_profile(j)
    if not p["name"]:
        # un-scrapeable response (private/invalid/empty) — stamp the known entity
        # so it leaves the backfill set and is NEVER re-scraped (no credit leak).
        if person_id:
            conn.execute("update gb_entity set attrs = attrs || '{\"profile_scraped\":\"none\"}'::jsonb where id=%s",
                         (person_id,))
        return "no-name"
    # upgrade a stub canonical (an extracted first name like "Navneet") to the
    # full LinkedIn name when it's a safe superset with no collision — keeps one
    # clean node per person instead of a stub + a full-name duplicate.
    if person_id:
        _maybe_upgrade_canonical(conn, person_id, p["name"])
    # quick-fields mirrored onto the person entity (drive dashboard + vault)
    quick = {k: v for k, v in {
        "linkedin": p["linkedin_url"], "headline": p["headline"],
        "company": p["current_company"], "role": p["current_title"],
        "location": p["location_city"], "photo": p["photo_url"],
        "public_id": p["public_id"], "linkedin_checked": "apify",
        "profile_scraped": "apify",
    }.items() if v is not None}
    keys = {"linkedin": p["public_id"]} if p["public_id"] else {}
    if person_id:
        # worker path: the entity is KNOWN (queued/backfilled). Bind the profile to
        # it and stamp profile_scraped on IT — never spawn a second node from the
        # scraped name, and guarantee it leaves the backfill set (no re-scrape).
        conn.execute(
            "update gb_entity set attrs = attrs || %s::jsonb, keys = keys || %s::jsonb where id=%s",
            (json.dumps(quick), json.dumps(keys), person_id))
        pid = person_id
    else:
        # import/scrape CLI path: no known entity → resolve/create by canonical name.
        pid = conn.execute(
            """insert into gb_entity (type, canonical, attrs, keys)
               values ('person', %s, %s::jsonb, %s::jsonb)
               on conflict (type, canonical) do update
                 set attrs = gb_entity.attrs || excluded.attrs
               returning id""",
            (p["name"], json.dumps(quick), json.dumps(keys)),
        ).fetchone()["id"]

    conn.execute(
        """insert into gb_person_profile
             (person_id, linkedin_url, public_id, headline, about, location_city,
              location_country, current_title, current_company, current_company_id,
              photo_url, followers, connections, skills, experience, education,
              certifications, honors, projects, raw, scraped_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,
                   %s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb, now())
           on conflict (person_id) do update set
             linkedin_url=excluded.linkedin_url, public_id=excluded.public_id,
             headline=excluded.headline, about=excluded.about,
             location_city=excluded.location_city, location_country=excluded.location_country,
             current_title=excluded.current_title, current_company=excluded.current_company,
             current_company_id=excluded.current_company_id, photo_url=excluded.photo_url,
             followers=excluded.followers, connections=excluded.connections,
             skills=excluded.skills, experience=excluded.experience,
             education=excluded.education, certifications=excluded.certifications,
             honors=excluded.honors, projects=excluded.projects, raw=excluded.raw,
             scraped_at=now()""",
        (pid, p["linkedin_url"], p["public_id"], p["headline"], p["about"],
         p["location_city"], p["location_country"], p["current_title"], p["current_company"],
         p["current_company_id"], p["photo_url"], p["followers"], p["connections"],
         p["skills"], json.dumps(p["experience"]), json.dumps(p["education"]),
         json.dumps(p["certifications"]), json.dumps(p["honors"]), json.dumps(p["projects"]),
         json.dumps(j)),
    )

    # graph: works_at edges to companies we already track (suffix-tolerant match;
    # dedup by company so the same firm across multiple roles → one edge). Also
    # harvest each company's LinkedIn URL FOR FREE from the experience entry and
    # enqueue a full company scrape on first discovery (most-optimized path —
    # no extra search/credit; gb_q_company dedups via attrs.company_scraped).
    # Rebuild this person's LinkedIn works_at edges idempotently (delete our prior
    # ones — env-less — then re-insert; pipeline edges with an envelope_id are left
    # alone). Experience is ordered most-recent-first, so the first match per
    # company is the latest stint and decides current/past.
    conn.execute("delete from gb_edge where src=%s and rel='works_at' and envelope_id is null", (pid,))
    edges, seen = 0, set()
    for e in p["experience"]:
        comp_id = _match_company(conn, e.get("companyName"))
        if comp_id and comp_id not in seen:
            seen.add(comp_id)
            end = (e.get("end") or "").strip().lower()
            props = {
                "current": end in ("", "present"),
                "title": e.get("position"),
                "start": e.get("start"), "end": e.get("end"),
                "company_name": e.get("companyName"),
                "company_linkedin": _company_url(e),
                "company_public_id": e.get("companyUniversalName"),
            }
            conn.execute(
                "insert into gb_edge (src, rel, dst, props) values (%s,'works_at',%s,%s::jsonb)",
                (pid, comp_id, json.dumps({k: v for k, v in props.items() if v not in (None, "")})))
            edges += 1
            _attach_company_url(conn, comp_id, _company_url(e), e.get("companyLogo"))
    return f"{p['name']} ({len(p['experience'])} jobs, {len(p['skills'])} skills, {edges} edges)"


def _company_url(e: dict) -> str | None:
    """LinkedIn company URL from an experience entry (free byproduct of a person
    scrape): prefer the explicit URL, then the clean universalName slug, else the
    numeric company id."""
    u = (e.get("companyLinkedinUrl") or "").strip()
    if u:
        return u.split("?")[0].rstrip("/")
    un = (e.get("companyUniversalName") or "").strip()
    if un:
        return f"https://www.linkedin.com/company/{un}"
    cid = e.get("companyId")
    return f"https://www.linkedin.com/company/{cid}" if cid else None


def _attach_company_url(conn, comp_id, url: str | None, logo: str | None = None) -> None:
    """Stamp a company's LinkedIn URL (and logo, if absent) onto its entity and
    enqueue a one-time full scrape on first discovery. Zero cost — all derived
    from person data we already paid to scrape."""
    if not comp_id or not url:
        return
    a = (conn.execute("select attrs from gb_entity where id=%s", (comp_id,)).fetchone() or {}).get("attrs") or {}
    patch = {}
    if not a.get("logo") and logo:
        patch["logo"] = logo            # free company logo for the dashboard/vault
    if a.get("linkedin"):               # URL already known → just backfill the logo
        if patch:
            conn.execute("update gb_entity set attrs = attrs || %s::jsonb where id=%s",
                         (json.dumps(patch), comp_id))
        return
    patch["linkedin"] = url
    conn.execute("update gb_entity set attrs = attrs || %s::jsonb where id=%s",
                 (json.dumps(patch), comp_id))
    if not a.get("company_scraped"):
        try:
            queues.send(conn, queues.Q_COMPANY, {"company_id": str(comp_id), "url": url})
        except Exception:  # noqa: BLE001
            pass


def _maybe_upgrade_canonical(conn, person_id, name: str) -> None:
    """Rename a stub person entity to the full LinkedIn name, but ONLY when the
    current canonical is a subset of it (e.g. "Navneet" → "Navneet Agarwal") and
    no other entity already owns that name — never merges two distinct people."""
    cur = conn.execute("select canonical from gb_entity where id=%s", (person_id,)).fetchone()
    if not cur:
        return
    old = (cur["canonical"] or "").strip()
    if not old or old.lower() == name.lower() or old.lower() not in name.lower():
        return
    dup = conn.execute(
        "select 1 from gb_entity where type='person' and lower(canonical)=lower(%s) and id<>%s",
        (name, person_id)).fetchone()
    if dup:
        return
    try:
        conn.execute("update gb_entity set canonical=%s where id=%s", (name, person_id))
    except Exception:  # noqa: BLE001 — unique race; keep the existing name
        pass


# ── Apify API ────────────────────────────────────────────────

class ApifyError(RuntimeError):
    """Actor-level failure (plan/credit limit, auth, rate limit). RETRYABLE — the
    caller must NOT treat it as an empty profile (no 'none' stamp), so nothing is
    poisoned and everything re-scrapes once the plan is upgraded."""


def _check_apify_items(items: list[dict]) -> list[dict]:
    """harvestapi returns [{"error": "..."}] for plan/credit/rate limits instead
    of a profile. Detect that and raise (retryable) rather than mis-reading it as
    a no-name profile."""
    if len(items) == 1 and isinstance(items[0], dict):
        it = items[0]
        if it.get("error") and not (it.get("firstName") or it.get("lastName") or it.get("name")):
            raise ApifyError(str(it["error"])[:200])
    return items


def apify_fetch(urls: list[str]) -> list[dict]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    actor = os.environ.get("APIFY_ACTOR_ID", "").strip()
    if not token or not actor:
        raise RuntimeError("APIFY_TOKEN / APIFY_ACTOR_ID not set in .env")
    field = os.environ.get("APIFY_INPUT_FIELD", "queries")
    payload: dict = {field: urls}
    # pin the pricing tier when set (else the actor uses its own default mode)
    mode = os.environ.get("APIFY_SCRAPER_MODE", "").strip()
    if mode:
        payload["profileScraperMode"] = mode
    r = httpx.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        params={"token": token}, json=payload, timeout=300)
    if r.status_code not in (200, 201):
        raise ApifyError(f"apify {r.status_code}: {r.text[:200]}")
    data = r.json()
    return _check_apify_items(data if isinstance(data, list) else [data])


# ── worker (queue + backfill) ────────────────────────────────

def _apify_ready() -> bool:
    return bool(os.environ.get("APIFY_TOKEN", "").strip() and os.environ.get("APIFY_ACTOR_ID", "").strip())


def _li_slug(url: str | None) -> str | None:
    """The /in/<slug> identity key from a LinkedIn URL (subdomain/case/query
    independent) — the deterministic key that unifies first-name vs full-name
    nodes for the same person."""
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1).strip("/").lower() if m else None


def process(conn, person_id, url=None) -> str:
    e = conn.execute("select id, canonical, attrs from gb_entity where id=%s and type='person'",
                     (person_id,)).fetchone()
    if e is None:
        return "missing"
    a = e["attrs"] or {}
    if a.get("profile_scraped"):
        return "noop"
    url = norm_li_url(url or a.get("linkedin"))
    if not url:
        return "no-url"
    # DEDUP by LinkedIn identity: the same profile may already be scraped under a
    # name-variant node ("Jeetendra" vs "Jeetendra Kundlia"). Reuse the stored raw
    # — spend NO Apify credit — and still bind it here so both variants enrich.
    slug = _li_slug(url)
    if slug:
        # exact slug match (harvestapi's publicIdentifier IS the /in/ slug); a
        # missing/empty public_id simply fails safe to a normal scrape, never to a
        # wrong-person merge.
        twin = conn.execute(
            "select raw from gb_person_profile where lower(public_id)=%s and raw is not null limit 1",
            (slug,)).fetchone()
        if twin and twin["raw"]:
            store_profile(conn, twin["raw"], person_id=person_id)
            return f"dedup: reused /in/{slug} (no credit)"
    items = apify_fetch([url])
    if not items:
        conn.execute("update gb_entity set attrs = attrs || '{\"profile_scraped\":\"none\"}'::jsonb where id=%s", (person_id,))
        return "none"
    return store_profile(conn, items[0], person_id=person_id)


def run(once: bool = False) -> None:
    conn = connect()
    print(f"[profile] up · apify={'ready' if _apify_ready() else 'MISSING token/actor'}", flush=True)
    while True:
        if not _apify_ready():
            if once:
                return
            time.sleep(NO_KEY_SLEEP)
            continue
        try:
            msgs = queues.read(conn, queues.Q_PROFILE, vt=VT_SECONDS, qty=3)
            if msgs:
                for m in msgs:
                    pid = m["message"].get("person_id")
                    try:
                        print(f"[profile] {process(conn, pid, m['message'].get('url'))}", flush=True)
                        queues.archive(conn, queues.Q_PROFILE, m["msg_id"])
                    except ApifyError:
                        raise  # actor/plan limit → pause; leave msg for later retry
                    except Exception as exc:  # noqa: BLE001
                        if m["read_ct"] >= MAX_READS:
                            queues.dead_letter(conn, "profile", pid, m["message"], repr(exc), m["read_ct"])
                            queues.archive(conn, queues.Q_PROFILE, m["msg_id"])
                            print(f"[profile] {pid} → DLQ ({exc})", flush=True)
                        else:
                            queues.backoff(m["read_ct"])
                            print(f"[profile] {pid} retry ({exc})", flush=True)
                continue
            # backfill: people with a LinkedIn URL but no profile yet
            ids = [r["id"] for r in conn.execute(
                "select id from gb_entity where type='person' "
                "and coalesce(attrs->>'linkedin','')<>'' and attrs->>'profile_scraped' is null "
                "order by canonical limit %s", (MAX_PER_RUN,)).fetchall()]
            for pid in ids:
                print(f"[profile] {process(conn, pid)}", flush=True)
            if not ids:
                if once:
                    return
                time.sleep(IDLE_SLEEP)
        except ApifyError as exc:
            # plan/credit/rate limit — pause the whole worker (don't churn the
            # backlog stamping errors). Resumes automatically; nothing poisoned.
            print(f"[profile] PAUSED — Apify actor error: {exc} "
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
            print(f"[profile] {store_profile(conn, item)}", flush=True)
            n += 1
    return n


def relink(conn) -> int:
    """Rebuild graph edges + entity quick-fields from already-stored raw profiles
    (no Apify calls). Use after schema/logic changes — e.g. to populate works_at
    edge props (current/past, role, tenure) for profiles scraped earlier."""
    n = 0
    for r in conn.execute("select raw from gb_person_profile where raw is not null").fetchall():
        raw = r["raw"] if isinstance(r["raw"], dict) else json.loads(r["raw"])
        print(f"[profile] relink {store_profile(conn, raw)}", flush=True)
        n += 1
    return n


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "worker"
    conn = connect()
    if cmd == "worker":
        run(once="--once" in sys.argv)
    elif cmd == "import":
        print(f"[profile] imported {import_path(conn, sys.argv[2])} profiles", flush=True)
    elif cmd == "relink":
        print(f"[profile] relinked {relink(conn)} profiles", flush=True)
    elif cmd == "scrape":
        for item in apify_fetch([sys.argv[2]]):
            print(f"[profile] {store_profile(conn, item)}", flush=True)
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
