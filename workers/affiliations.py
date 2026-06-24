"""gbrain · affiliations graph — past/other employers (org) + education (school).

Promotes a scraped person's NON-tracked employers and their schools into
first-class graph nodes so we can show a company/org's alumni and a school's
graduates. Deterministic, ZERO API/AI — built entirely from the already-stored
LinkedIn profile JSON in workers/apify_linkedin.store_profile.

  • org    (type='org')    + edge works_at  (person → org)     — untracked employers
  • school (type='school') + edge studied_at(person → school)  — colleges/universities

Tracked deal companies keep their company works_at edges (handled in apify_linkedin
via _match_company); orgs are ONLY created when no company matches, so the two
layers never collide.
"""

from __future__ import annotations

import json
import re

# generic, non-identifying employer/school "names" that must NOT become nodes
_JUNK = {
    "self-employed", "self employed", "freelance", "freelancer", "independent",
    "independent consultant", "various", "various companies", "other", "others",
    "n/a", "na", "none", "-", "—", "unknown", "tbd", "private", "confidential",
    "stealth", "stealth startup", "stealth mode",
}


def _ok(name: str) -> bool:
    n = (name or "").strip().strip(".")
    return len(n) >= 2 and "@" not in n and n.lower() not in _JUNK


is_org_name = _ok
is_school_name = _ok


def _upsert(conn, etype: str, name: str, flag: str):
    return conn.execute(
        f"""insert into gb_entity (type, canonical, attrs)
              values (%s, %s, '{{"{flag}": true}}'::jsonb)
            on conflict (type, canonical) do update set attrs = gb_entity.attrs || excluded.attrs
            returning id""",
        (etype, name.strip()),
    ).fetchone()["id"]


def upsert_org(conn, name: str):
    return _upsert(conn, "org", name, "is_org") if is_org_name(name) else None


def upsert_school(conn, name: str):
    return _upsert(conn, "school", name, "is_school") if is_school_name(name) else None


def add_works_at_org(conn, person_id, org_id, props: dict) -> None:
    """person → org works_at edge with the same props shape as company roles."""
    conn.execute(
        "insert into gb_edge (src, rel, dst, props) values (%s,'works_at',%s,%s::jsonb)",
        (person_id, org_id, json.dumps({k: v for k, v in props.items() if v not in (None, "")})))


def add_studied_at(conn, person_id, school_id, props: dict) -> None:
    conn.execute(
        "insert into gb_edge (src, rel, dst, props) values (%s,'studied_at',%s,%s::jsonb)",
        (person_id, school_id, json.dumps({k: v for k, v in props.items() if v not in (None, "")})))


def _slug(url: str | None) -> str | None:
    """LinkedIn id (slug) from a /school/, /company/ or /edu/ URL."""
    m = re.search(r"/(?:school|company|edu|in)/([^/?#]+)", url or "", re.I)
    return m.group(1).strip("/").lower() if m else None


def attach_meta(conn, entity_id, url: str | None = None, logo: str | None = None,
                public_id: str | None = None) -> None:
    """Stamp a LinkedIn URL + id (slug) + logo onto an org or school node (free,
    from the person's experience/education entry) for the Obsidian note + base."""
    patch = {k: v for k, v in {
        "linkedin": (url.split("?")[0].rstrip("/") if url else None),
        "linkedin_id": public_id or _slug(url),
        "logo": logo,
    }.items() if v}
    if patch and entity_id:
        conn.execute("update gb_entity set attrs = attrs || %s::jsonb where id=%s",
                     (json.dumps(patch), entity_id))
