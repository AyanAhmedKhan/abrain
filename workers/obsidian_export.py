"""gbrain · Obsidian vault export.

Generates a Dexter Capital Obsidian vault from the gbrain database that matches
Yash's vault conventions (References/ company+people notes, Email/ call-note
notes, Categories/ sector MOCs) and reuses its scaffold verbatim — the 32 Bases,
templates, Schema, and .obsidian config — so it opens with identical views.

Re-runnable and idempotent: the scaffold is copied once; the data folders
(References/, Email/, Categories/, indexes/) are rebuilt every run so the vault
tracks the database.

Run:  python -m workers.obsidian_export [VAULT_DIR]   (default /opt/gbrain/vault)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections import defaultdict
from email.utils import getaddresses

from workers.lib.db import connect
from workers.normalize import clean_body
from workers.lib.taxonomy import (canon_sector, canon_stage, entity_type,
                                  TYPE_CATEGORY, is_investor, is_dexter_email,
                                  name_from_email, DEXTER_TEAM, make_aliases)

SRC = "/opt/gbrain/Obsidian/Yash"          # template/reference vault (never modified)
VAULT = sys.argv[1] if len(sys.argv) > 1 else "/opt/gbrain/vault"

SCAFFOLD_DIRS = ["_templates", ".obsidian", "Schema", "scripts", "agents"]
SCAFFOLD_FILES = ["CLAUDE.md", "AGENTS.md"]
DATA_DIRS = ["References", "Email", "Categories", "indexes"]

ILLEGAL = re.compile(r'[/\\:*?"<>|#\^\[\]]')


# ── helpers ──────────────────────────────────────────────────

def safe_name(name: str) -> str:
    n = ILLEGAL.sub("-", (name or "").strip()).replace("\n", " ")
    n = re.sub(r"\s{2,}", " ", n).strip(" .-")
    if len(n) > 120:   # hash-suffix so distinct long names don't silently collide
        import hashlib
        n = n[:108].rstrip() + "-" + hashlib.sha1(n.encode("utf-8")).hexdigest()[:6]
    return n or "Untitled"


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def yq(v) -> str:
    """YAML-safe scalar. Bare ISO dates stay unquoted so Obsidian Bases treat
    them as dates (sortable), everything else is double-quoted + escaped."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if _ISO_DATE.fullmatch(s):
        return s
    s = (s.replace("\\", "\\\\").replace('"', '\\"')
          .replace("\n", " ").replace("\r", " ").replace("\t", " "))
    return f'"{s}"'


def fm_scalar(key, v):
    val = yq(v)
    return f"{key}: {val}" if val != "" else f"{key}:"


def fm_list(key, items):
    items = [i for i in (items or []) if i not in (None, "")]
    if not items:
        return f"{key}: []"
    return key + ":\n" + "\n".join(f'  - {yq(i)}' for i in items)


def wl(name, folder="References"):
    return f"[[{folder}/{safe_name(name)}]]"


def cr(n):
    """Render an INR-crore number as '₹X Cr'. Safe: returns None on non-numeric
    (Gemini sometimes emits strings like '40-60' or '~40')."""
    if n is None:
        return None
    try:
        f = float(n)
    except (TypeError, ValueError):
        return None
    return f"₹{int(f) if f == int(f) else round(f, 2)} Cr"


def sectors_of(raw):
    """Split a sector string into canonical category names."""
    if not raw:
        return []
    out = []
    for p in re.split(r"[,/]| and ", str(raw)):
        cs = canon_sector(p.strip())
        if cs and cs.lower() != "null" and cs not in out:
            out.append(cs)
    return out


def parse_contacts(actors, keys=("from", "to", "cc")):
    """→ [(name, email)] from a Gmail actors dict. Uses RFC-2822 address parsing
    (handles 'Last, First <e@x>' and comma-joined recipient strings correctly)."""
    fields = []
    for k in keys:
        v = actors.get(k)
        if isinstance(v, list):
            fields += [str(x) for x in v]
        elif v:
            fields.append(str(v))
    out = []
    for nm, email in getaddresses(fields):
        nm = nm.strip().strip('"')
        email = email.strip()
        if (not nm or "@" in nm) and email:
            nm = name_from_email(email)
        if nm or email:
            out.append((nm, email))
    return out


# ── scaffold ─────────────────────────────────────────────────

def scaffold(dest):
    os.makedirs(dest, exist_ok=True)
    for d in SCAFFOLD_DIRS:
        s = os.path.join(SRC, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest, d), dirs_exist_ok=True)
    for f in SCAFFOLD_FILES:
        s = os.path.join(SRC, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, f))
    for d in DATA_DIRS:
        p = os.path.join(dest, d)
        if os.path.isdir(p):
            shutil.rmtree(p)
        os.makedirs(p)


# ── data model ───────────────────────────────────────────────

def latest(cur, v):
    return v if v not in (None, "", []) else cur


def build_model(conn):
    rows = conn.execute(
        """select source, source_id, title, occurred_at, actors, body_clean, extraction
             from gb_envelope
            where status='indexed' and source in ('gmail','pdf')
              and coalesce(extraction->>'company_name','') <> ''
            order by occurred_at asc nulls first"""
    ).fetchall()

    # observations keyed by lower(company canonical)
    obs = defaultdict(dict)
    for r in conn.execute(
        """select e.canonical, o.metric, o.value_num, o.unit, o.period, o.as_of
             from gb_observation o join gb_entity e on e.id=o.entity_id
            where e.type='company'
            order by o.as_of asc nulls first, o.created_at asc"""
    ).fetchall():
        obs[r["canonical"].lower()][r["metric"]] = r  # most-recent as_of wins

    companies, emails, people = {}, [], {}

    for r in rows:
        ex = r["extraction"] or {}
        name = (ex.get("company_name") or "").strip()
        if not name:
            continue
        date = r["occurred_at"].date().isoformat() if r["occurred_at"] else ""
        c = companies.setdefault(name, {
            "name": name, "sector": None, "sub_sector": None, "stage": None,
            "round_type": None, "business_model": None, "summary": None,
            "ask": None, "valuation": None, "revenue": None, "revenue_period": None,
            "ebitda": None, "founders": {}, "key_metrics": [], "risks": [],
            "actions": [], "opinions": [], "emails": [], "last": "",
            "hq": None, "website": None, "founded": None, "poc": None,
            "fitment": None, "referred_by": None, "aliases": [], "existing_investors": [],
            "dexter": set(),
        })
        for nm, email in parse_contacts(r["actors"] or {}):
            if nm and (is_dexter_email(email) or nm in DEXTER_TEAM):
                c["dexter"].add(nm)
                people.setdefault(nm, {"role": None, "company": "Dexter Capital",
                                       "linkedin": None, "last": date, "dexter": True})
        c["sector"] = latest(c["sector"], ex.get("sector"))
        c["sub_sector"] = latest(c["sub_sector"], ex.get("sub_sector"))
        c["stage"] = latest(c["stage"], ex.get("stage"))
        c["round_type"] = latest(c["round_type"], ex.get("round_type"))
        c["business_model"] = latest(c["business_model"], ex.get("business_model"))
        c["summary"] = latest(c["summary"], ex.get("summary"))
        c["hq"] = latest(c["hq"], ex.get("hq"))
        c["website"] = latest(c["website"], ex.get("website"))
        c["founded"] = latest(c["founded"], ex.get("founded"))
        c["poc"] = latest(c["poc"], ex.get("poc"))
        c["fitment"] = latest(c["fitment"], ex.get("fitment"))
        c["referred_by"] = latest(c["referred_by"], ex.get("referred_by"))
        for a in ex.get("aliases") or []:
            if a and a not in c["aliases"]:
                c["aliases"].append(a)
        for inv in ex.get("existing_investors") or []:
            if inv and inv not in c["existing_investors"]:
                c["existing_investors"].append(inv)
        c["ask"] = latest(c["ask"], ex.get("ask_inr_cr"))
        c["valuation"] = latest(c["valuation"], ex.get("valuation_inr_cr"))
        c["revenue"] = latest(c["revenue"], ex.get("revenue_inr_cr"))
        c["revenue_period"] = latest(c["revenue_period"], ex.get("revenue_period"))
        c["ebitda"] = latest(c["ebitda"], ex.get("ebitda_inr_cr"))
        for f in ex.get("founders") or []:
            nm = (f.get("name") or "").strip()
            if nm:
                c["founders"][nm] = f.get("role") or c["founders"].get(nm)
                p = people.get(nm)
                if p is None:
                    people[nm] = {"role": f.get("role"), "company": name,
                                  "linkedin": f.get("linkedin"), "last": date}
                else:  # merge: fill gaps, advance company on newer mention
                    if f.get("role") and not p.get("role"):
                        p["role"] = f.get("role")
                    if f.get("linkedin") and not p.get("linkedin"):
                        p["linkedin"] = f.get("linkedin")
                    if not p.get("dexter") and date >= (p.get("last") or ""):
                        p["last"], p["company"] = date, name
        for k in ex.get("key_metrics") or []:
            if k and k not in c["key_metrics"]:
                c["key_metrics"].append(k)
        if ex.get("risks"):
            c["risks"] = ex["risks"]
        for a in ex.get("action_items") or []:
            if a and a not in c["actions"]:
                c["actions"].append(a)
        if ex.get("summary"):
            c["opinions"].append((date, ex.get("confidence"), ex["summary"]))
        # email note for this envelope
        efile = email_filename(date, r["title"], r["source_id"])
        c["emails"].append(efile)
        if date > c["last"]:
            c["last"] = date
        emails.append({
            "file": efile, "title": r["title"], "date": date, "source": r["source"],
            "actors": r["actors"] or {}, "body": r["body_clean"], "ex": ex,
            "company": name,
        })

    # attach rich LinkedIn profiles (Apify, deterministic) keyed by entity name.
    # A profiled person who isn't a founder/Dexter contact still gets a note.
    for r in conn.execute(
        """select e.canonical, p.linkedin_url, p.public_id, p.headline, p.about,
                  p.location_city, p.location_country, p.current_title, p.current_company,
                  p.photo_url, p.followers, p.connections, p.skills, p.experience,
                  p.education, p.certifications, p.honors, p.projects
             from gb_person_profile p join gb_entity e on e.id = p.person_id
            where e.type='person'"""
    ).fetchall():
        nm = (r["canonical"] or "").strip()
        if not nm:
            continue
        person = people.get(nm)
        if person is None:
            person = people.setdefault(nm, {"role": None, "company": None,
                                            "linkedin": None, "last": "", "dexter": False})
        person["profile"] = {
            "linkedin": r["linkedin_url"], "public_id": r["public_id"],
            "headline": r["headline"], "about": r["about"],
            "location": ", ".join(x for x in (r["location_city"], r["location_country"]) if x) or None,
            "current_title": r["current_title"], "current_company": r["current_company"],
            "photo": r["photo_url"], "followers": r["followers"], "connections": r["connections"],
            "skills": r["skills"] or [], "experience": r["experience"] or [],
            "education": r["education"] or [], "certifications": r["certifications"] or [],
            "honors": r["honors"] or [], "projects": r["projects"] or [],
        }
        person["linkedin"] = person.get("linkedin") or r["linkedin_url"]
        person["role"] = person.get("role") or r["current_title"]
        person["company"] = person.get("company") or r["current_company"]

    # company LinkedIn: the URL/logo live on gb_entity.attrs (free harvest, set
    # even before a full scrape); the rich profile lives in gb_company_profile.
    for r in conn.execute(
        "select canonical, attrs->>'linkedin' li, attrs->>'logo' logo "
        "from gb_entity where type='company' and attrs->>'linkedin' is not null"
    ).fetchall():
        c = companies.get(r["canonical"])
        if c:
            c["linkedin"], c["logo"] = r["li"], r["logo"]
    for r in conn.execute(
        """select company, industry, company_size, employee_count, followers,
                  founded, hq, website, description, public_id, specialties
             from gb_company_full"""
    ).fetchall():
        c = companies.get(r["company"])
        if not c:
            continue
        c["li_industry"] = r["industry"]
        c["li_size"] = r["company_size"]
        c["li_employees"] = r["employee_count"]
        c["li_followers"] = r["followers"]
        c["li_description"] = r["description"]
        c["li_specialties"] = r["specialties"] or []
        c["li_public_id"] = r["public_id"]
        c["founded"] = c.get("founded") or r["founded"]
        c["hq"] = c.get("hq") or r["hq"]
        c["website"] = c.get("website") or r["website"]

    # reverse-aggregation: who referred which deals → investor: [companies]
    referred = defaultdict(list)
    for c in companies.values():
        if c["referred_by"]:
            referred[c["referred_by"].strip()].append(c["name"])
    return companies, emails, people, obs, dict(referred)


_email_seen = set()


def email_filename(date, title, sid):
    base = f"{date or '0000-00-00'} - {safe_name(title or 'Call Note')}"
    fn = base
    if fn in _email_seen:
        fn = f"{base} ({sid[:6]})"
    _email_seen.add(fn)
    return fn


# ── renderers ────────────────────────────────────────────────

def render_company(c, obs, referred):
    name = c["name"]
    secs = sectors_of(c["sector"]) or sectors_of(c["sub_sector"])
    cats = [f"[[Categories/{safe_name(s)}]]" for s in secs]
    etype = entity_type(c["sector"], name, c["summary"] or "")
    is_inv = is_investor(etype)
    type_cat = TYPE_CATEGORY.get(etype)
    type_links = [f"[[Categories/{safe_name(type_cat)}]]"] if type_cat else cats
    stage = canon_stage(c["stage"])
    aliases = list(dict.fromkeys((c["aliases"] or []) + make_aliases(name)))
    people_links = [wl(n) for n in c["founders"]] + [wl(n) for n in sorted(c["dexter"])]
    email_links = [wl(e, "Email") for e in c["emails"]]
    has_deal = c["ask"] is not None or bool(c["round_type"])

    fm = ["---", 'categories:', '  - "[[Companies]]"']
    fm.append(fm_list("type", type_links))
    fm.append(fm_list("people", people_links))
    fm += [fm_scalar("url", c["website"]), fm_scalar("founded", c["founded"]),
           fm_scalar("hq", c["hq"]), fm_scalar("linkedin", c.get("linkedin")),
           fm_scalar("linkedin_id", c.get("li_public_id")),
           fm_scalar("industry", c.get("li_industry")),
           fm_scalar("employees", c.get("li_employees")),
           fm_scalar("followers", c.get("li_followers"))]
    if not is_inv:
        fm += [
            fm_scalar("revenue_latest", cr(c["revenue"])),
            fm_scalar("revenue_inr_cr", c["revenue"]),
            fm_scalar("revenue_type", "Revenue" if c["revenue"] else None),
            fm_scalar("revenue_period", c["revenue_period"]),
            fm_scalar("poc", c["poc"]),
            fm_scalar("fitment", c["fitment"]),
            fm_scalar("has_deal", has_deal),
            fm_scalar("stage", stage),
            fm_scalar("deal_type", c["round_type"]),
            fm_list("sector", cats),
            fm_scalar("valuation", cr(c["valuation"])),
            fm_scalar("valuation_inr_cr", c["valuation"]),
            fm_scalar("ebitda", cr(c["ebitda"])),
            fm_scalar("ask", cr(c["ask"])),
            fm_list("referred_by", [wl(c["referred_by"])] if c["referred_by"] else []),
        ]
    else:
        stage_links = [f"[[Categories/{safe_name(stage)}]]"] if stage else []
        fm += [fm_list("sector_focus", cats), fm_list("stage_focus", stage_links),
               fm_list("portfolio", [])]
    fm += [
        fm_scalar("last_interaction", c["last"]),
        fm_scalar("last_interaction_type", "Call"),
        fm_scalar("last_context", (c["summary"] or "")[:160]),
        fm_scalar("status", "stable"),
        fm_scalar("created", c["last"]),
        fm_scalar("updated", c["last"]),
        fm_list("email_sources", email_links),
        fm_list("aliases", aliases),
        "---",
    ]

    body = ["", "## Activity", "", "![[Company Activity.base]]", "",
            "## Mentions", "", "![[Mentions.base]]", ""]
    # People table
    body += ["## People", "", "| Name | Role | Organization | Email | Phone |",
             "|------|------|-------------|-------|-------|"]
    for n, role in c["founders"].items():
        body.append(f"| {wl(n)} | {role or ''} | {name} | | |")
    for n in sorted(c["dexter"]):
        body.append(f"| {wl(n)} | | Dexter Capital | | |")
    if not c["founders"] and not c["dexter"]:
        body.append("| | | | | |")
    body.append("")
    # About / Business model
    body += ["## About", "", c["summary"] or "", "",
             "## Business Model", "", c["business_model"] or "", ""]
    # LinkedIn (Apify, deterministic) — shown when we have a URL/profile
    if c.get("linkedin"):
        body += ["## LinkedIn", ""]
        facts = []
        if c.get("li_public_id"):
            facts.append(f"- **Profile:** [{c['li_public_id']}]({c['linkedin']})")
        else:
            facts.append(f"- **Profile:** {c['linkedin']}")
        if c.get("li_industry"):
            facts.append(f"- **Industry:** {c['li_industry']}")
        if c.get("li_size") or c.get("li_employees"):
            facts.append(f"- **Size:** {c.get('li_size') or ''}"
                         + (f" ({c['li_employees']} on LinkedIn)" if c.get("li_employees") else ""))
        if c.get("li_followers"):
            facts.append(f"- **Followers:** {c['li_followers']:,}")
        body += facts + [""]
        if c.get("li_description"):
            body += [c["li_description"], ""]
        if c.get("li_specialties"):
            body += ["_Specialties: " + ", ".join(c["li_specialties"]) + "_", ""]
    # Traction
    body += ["## Traction & Metrics", ""]
    if c["key_metrics"]:
        body += [f"- {m}" for m in c["key_metrics"]] + [""]
    # Financials
    o = obs.get(name.lower(), {})
    body += ["## Financials", "", "| Line Item | Value | Period | Source |",
             "|-----------|-------|--------|--------|"]
    fin_rows = []
    rv = o.get("revenue")
    rev_val = cr(c["revenue"]) or (cr(rv["value_num"]) if rv else None)
    rev_period = c["revenue_period"] or (rv["period"] if rv else "")
    if rev_val:
        fin_rows.append(("Revenue", rev_val, rev_period))
    if c["ebitda"] is not None:
        fin_rows.append(("EBITDA", cr(c["ebitda"]), ""))
    for item, val, period in fin_rows:
        body.append(f"| {item} | {val or ''} | {period or ''} | Call notes |")
    if not fin_rows:
        body.append("| Revenue | | | |")
    body.append("")
    # Valuation
    body += ["## Valuation", "", "| Metric | Value | Source |",
             "|--------|-------|--------|",
             f"| Asking Valuation | {cr(c['valuation']) or ''} | Call notes |",
             f"| Ask | {cr(c['ask']) or ''} | Call notes |", ""]
    # Deal thesis / opinion / risks
    body += ["## Deal Thesis", "", (c["summary"] or "")[:400], "", "## Opinion", ""]
    for d, conf, summ in c["opinions"][-5:]:
        body.append(f"{d}: ({conf or 'n/a'} confidence) {summ[:200]}")
        body.append("")
    body += ["## Risks", ""]
    body += [f"- {r}" for r in c["risks"]] + [""] if c["risks"] else [""]
    body += ["## Existing Investors", "", "| Investor | Stake | Round | Notes |",
             "|----------|-------|-------|-------|"]
    if c["existing_investors"]:
        body += [f"| {wl(inv)} | | | |" for inv in c["existing_investors"]]
    else:
        body.append("| | | | |")
    body.append("")
    if is_inv:
        refs = referred.get(name, [])
        body += ["## Deals Referred to Dexter", ""]
        body += ([f"- {wl(co)}" for co in refs] + [""]) if refs else ["_None recorded._", ""]
    body += ["## Timeline", ""]
    body += [f"- [ ] {a}" for a in c["actions"]] + [""] if c["actions"] else ["- [ ] ", ""]
    body += ["## Sources", ""]
    body += [f"- {l}" for l in email_links] + [""]
    body += ["## Notes", ""]
    return "\n".join(fm) + "\n" + "\n".join(body)


def _exp_line(e):
    head = " — ".join(x for x in (e.get("position"), e.get("companyName")) if x) or "(role)"
    when = " – ".join(x for x in (e.get("start"), e.get("end")) if x)
    meta = " · ".join(x for x in (when, e.get("duration"), e.get("employmentType"),
                                  e.get("workplaceType"), e.get("location")) if x)
    line = f"- **{head}**"
    if meta:
        line += f"  \n  _{meta}_"
    if e.get("description"):
        line += f"  \n  {str(e['description']).strip()}"
    return line


def _edu_line(e):
    head = e.get("schoolName") or "(school)"
    detail = ", ".join(x for x in (e.get("degree"), e.get("fieldOfStudy")) if x)
    tail = " · ".join(x for x in (detail, e.get("period"), e.get("insights")) if x)
    return f"- **{head}**" + (f"  \n  _{tail}_" if tail else "")


def _cert_line(c):
    head = c.get("title") or "(certificate)"
    by = " · ".join(x for x in (c.get("issuedBy"), c.get("issuedAt")) if x)
    line = f"- {head}" + (f" — _{by}_" if by else "")
    if c.get("link"):
        line += f" ([link]({c['link']}))"
    return line


def _honor_line(h):
    head = h.get("title") or "(award)"
    by = " · ".join(x for x in (h.get("issuedBy"), h.get("issuedAt")) if x)
    line = f"- **{head}**" + (f" — _{by}_" if by else "")
    if h.get("description"):
        line += f"  \n  {str(h['description']).strip()}"
    return line


def render_person(name, p):
    prof = p.get("profile") or {}
    fm = ["---", 'categories:', '  - "[[People]]"',
          fm_scalar("profession", p.get("role")),
          fm_list("org", [wl(p["company"])] if p.get("company") else []),
          fm_scalar("email", None), fm_scalar("phone", None)]
    if prof:
        fm += [
            fm_scalar("headline", prof.get("headline")),
            fm_scalar("linkedin", prof.get("linkedin")),
            fm_scalar("linkedin_id", prof.get("public_id")),
            fm_scalar("location", prof.get("location")),
            fm_scalar("current_title", prof.get("current_title")),
            fm_scalar("current_company", prof.get("current_company")),
            fm_scalar("followers", prof.get("followers")),
            fm_scalar("connections", prof.get("connections")),
            fm_scalar("photo", prof.get("photo")),
            fm_list("skills", prof.get("skills")),
        ]
    fm += [fm_scalar("created", p.get("last")),
           fm_scalar("last_interaction", p.get("last")),
           fm_scalar("last_interaction_type", "Call"),
           fm_scalar("last_context", prof.get("headline")
                     or (f"Founder/contact at {p['company']}" if p.get("company") else None)),
           "---"]

    about = f"{name}" + (f" — {p['role']}" if p.get("role") else "") + \
            (f" at [[References/{safe_name(p['company'])}]]" if p.get("company") else "") + "."
    body = [""]
    if prof.get("photo"):
        body += [f"![profile|160]({prof['photo']})", ""]
    if prof.get("headline"):
        body += [f"> {prof['headline']}", ""]
    body += ["## About", ""]
    body += [prof.get("about") or about, ""]
    if prof:  # contact / LinkedIn block
        meta = []
        if prof.get("linkedin"):
            meta.append(f"- **LinkedIn:** [{prof.get('public_id') or prof['linkedin']}]({prof['linkedin']})")
        if prof.get("location"):
            meta.append(f"- **Location:** {prof['location']}")
        if prof.get("current_title") or prof.get("current_company"):
            cur = " at ".join(x for x in (prof.get("current_title"), prof.get("current_company")) if x)
            meta.append(f"- **Current:** {cur}")
        if prof.get("followers"):
            meta.append(f"- **Followers:** {prof['followers']:,}")
        if meta:
            body += meta + [""]
    if prof.get("experience"):
        body += ["## Experience", ""] + [_exp_line(e) for e in prof["experience"]] + [""]
    if prof.get("education"):
        body += ["## Education", ""] + [_edu_line(e) for e in prof["education"]] + [""]
    if prof.get("skills"):
        body += ["## Skills", "", ", ".join(prof["skills"]), ""]
    if prof.get("certifications"):
        body += ["## Certifications", ""] + [_cert_line(c) for c in prof["certifications"]] + [""]
    if prof.get("honors"):
        body += ["## Honors & Awards", ""] + [_honor_line(h) for h in prof["honors"]] + [""]
    if prof.get("projects"):
        body += ["## Projects", ""]
        for pr in prof["projects"]:
            t = pr.get("title") or "(project)"
            d = f" — {pr['description']}" if pr.get("description") else ""
            body.append(f"- **{t}**{d}")
        body.append("")
    body += ["## Articles", "", "![[Articles by Person.base]]", "",
             "## Meetings", "", "![[Meetings.base]]", "", "## Deals", "", "![[Deal Metrics.base]]", "",
             "## Mentions", "", "![[Mentions.base]]", "", "## Notes", ""]
    return "\n".join(fm) + "\n" + "\n".join(body)


def render_email(e, companies):
    actors = e["actors"]
    frm = parse_contacts(actors, keys=("from", "organizer"))
    from_name, from_email = frm[0] if frm else ("", "")
    participants = [f"{n} <{em}>" if em else n for n, em in parse_contacts(actors, keys=("to", "cc"))]
    comp = e["company"]
    cdata = companies.get(comp, {})
    founders = list(cdata.get("founders", {}).keys())
    is_inv = is_investor(entity_type(cdata.get("sector"), comp, cdata.get("summary") or ""))
    mtype = "Deck" if e["source"] == "pdf" else ("VC" if is_inv else "Founder")
    ex = e["ex"]

    fm = ["---", fm_scalar("title", e["title"]),
          fm_scalar("source", "PDF" if e["source"] == "pdf" else "Gmail"),
          fm_scalar("from_name", from_name), fm_scalar("from_email", from_email),
          fm_scalar("date_iso", e["date"]),
          fm_list("participants", participants),
          fm_scalar("Processed", True),
          fm_list("company", [wl(comp)]),
          fm_list("people", [wl(n) for n in founders]),
          fm_scalar("context", (ex.get("summary") or "")[:160]),
          fm_scalar("summary", (ex.get("summary") or "")[:300]),
          fm_scalar("meeting_type", mtype),
          "tags:", "  - email", "---", ""]
    if e["source"] == "pdf":
        parts = [ex.get("summary") or ""]
        if ex.get("key_metrics"):
            parts.append("\n### Key metrics\n" + "\n".join(f"- {m}" for m in ex["key_metrics"]))
        bodytext = "\n".join(parts)
    else:
        # re-clean: older envelopes were normalized before the forward-cleaner fix
        bodytext = clean_body(e["body"]) or ex.get("summary") or ""
    return "\n".join(fm) + "\n" + bodytext + "\n"


# Enhanced People base: adds LinkedIn / headline / location / company / followers
# columns + a dedicated profiles view. Written over the scaffolded copy so the
# source template vault stays pristine.
PEOPLE_BASE = """filters:
  and:
    - categories.contains(link("People"))
    - '!file.name.contains("Template")'
properties:
  file.name:
    displayName: Name
  note.headline:
    displayName: Headline
  note.profession:
    displayName: Profession
  note.org:
    displayName: Organization
  note.current_company:
    displayName: Company
  note.location:
    displayName: Location
  note.linkedin:
    displayName: LinkedIn
  note.linkedin_id:
    displayName: LinkedIn ID
  note.followers:
    displayName: Followers
  note.email:
    displayName: Email
  note.phone:
    displayName: Phone
  note.last_interaction:
    displayName: Last Interaction
  note.last_context:
    displayName: Context
views:
  - type: table
    name: All People
    order:
      - file.name
      - headline
      - org
      - location
      - last_interaction
      - last_context
      - email
      - phone
    sort:
      - property: last_interaction
        direction: DESC
    columnSize:
      file.name: 240
      note.headline: 320
  - type: table
    name: LinkedIn Profiles
    filters:
      and:
        - note.linkedin != ""
    order:
      - file.name
      - headline
      - current_company
      - location
      - followers
      - linkedin_id
      - linkedin
    sort:
      - property: followers
        direction: DESC
  - type: table
    name: By Org
    filters:
      and:
        - list(org).contains(this)
    order:
      - file.name
      - profession
      - last_interaction
      - last_context
    sort:
      - property: file.name
        direction: ASC
"""


def write_people_base(dest):
    p = os.path.join(dest, "_templates", "Bases", "People.base")
    if os.path.isdir(os.path.dirname(p)):
        _write(p, PEOPLE_BASE)


def render_category(sector):
    return ("---\ntags:\n  - categories\n---\n\n## Companies\n\n"
            "![[Companies by Sector.base]]\n\n## Deals\n\n![[Deals by Sector.base]]\n\n"
            "## Investors\n\n![[Investors by Sector.base]]\n")


# ── indexes ──────────────────────────────────────────────────

def write_indexes(dest, companies, people, emails):
    idir = os.path.join(dest, "indexes")
    comp_idx, deals, pipeline = [], [], []
    for c in companies.values():
        rec = {"name": c["name"], "sector": sectors_of(c["sector"]),
               "stage": c["stage"], "revenue_inr_cr": c["revenue"],
               "valuation_inr_cr": c["valuation"], "ask_inr_cr": c["ask"],
               "last_interaction": c["last"]}
        comp_idx.append(rec)
        (deals if (c["ask"] is not None or c["round_type"]) else pipeline).append(rec)
    json.dump(comp_idx, open(os.path.join(idir, "companies.json"), "w"), indent=1, default=str)
    json.dump(deals, open(os.path.join(idir, "deals.json"), "w"), indent=1, default=str)
    json.dump(pipeline, open(os.path.join(idir, "pipeline.json"), "w"), indent=1, default=str)
    json.dump([{"name": n, **p} for n, p in people.items()],
              open(os.path.join(idir, "people.json"), "w"), indent=1, default=str)
    json.dump([{"file": e["file"], "date": e["date"], "company": e["company"],
                "meeting_type": "Deck" if e["source"] == "pdf" else "Call"} for e in emails],
              open(os.path.join(idir, "email-log.json"), "w"), indent=1, default=str)


# ── main ─────────────────────────────────────────────────────

def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build_vault(dest, conn):
    """Generate the whole vault under `dest`. One bad row never aborts the run."""
    _email_seen.clear()
    scaffold(dest)
    write_people_base(dest)   # enrich the People base with LinkedIn/profile columns
    companies, emails, people, obs, referred = build_model(conn)

    sectors = set()
    for c in companies.values():
        for s in sectors_of(c["sector"]) or sectors_of(c["sub_sector"]):
            sectors.add(s)
        tc = TYPE_CATEGORY.get(entity_type(c["sector"], c["name"], c["summary"] or ""))
        if tc:
            sectors.add(tc)

    written = set()   # reference filenames already taken (company wins over person)
    errs = 0
    for c in companies.values():
        try:
            fn = safe_name(c["name"]) + ".md"
            _write(os.path.join(dest, "References", fn), render_company(c, obs, referred))
            written.add(fn.lower())
        except Exception as e:
            errs += 1; print(f"[vault] skip company {c.get('name')!r}: {e!r}", flush=True)
    for n, p in people.items():
        try:
            fn = safe_name(n) + ".md"
            if fn.lower() in written:    # name clashes with a company / another person
                continue
            _write(os.path.join(dest, "References", fn), render_person(n, p))
            written.add(fn.lower())
        except Exception as e:
            errs += 1; print(f"[vault] skip person {n!r}: {e!r}", flush=True)
    for e in emails:
        try:
            _write(os.path.join(dest, "Email", e["file"] + ".md"), render_email(e, companies))
        except Exception as ex:
            errs += 1; print(f"[vault] skip email {e.get('file')!r}: {ex!r}", flush=True)
    for s in sorted(sectors):
        try:
            _write(os.path.join(dest, "Categories", safe_name(s) + ".md"), render_category(s))
        except Exception as ex:
            errs += 1; print(f"[vault] skip category {s!r}: {ex!r}", flush=True)

    write_indexes(dest, companies, people, emails)
    print(f"[vault] generated {len(companies)} companies, {len(people)} people, "
          f"{len(emails)} emails, {len(sectors)} categories ({errs} skipped)", flush=True)


def main():
    tmp = VAULT + ".tmp"
    old = VAULT + ".old"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    conn = connect()
    print(f"[vault] building {tmp} from {SRC}", flush=True)
    build_vault(tmp, conn)   # if this throws, the live vault is untouched
    # atomic-ish swap: only replace the live vault once the new one is complete
    if os.path.exists(old):
        shutil.rmtree(old)
    if os.path.exists(VAULT):
        os.rename(VAULT, old)
    os.rename(tmp, VAULT)
    if os.path.exists(old):
        shutil.rmtree(old)
    print(f"[vault] swapped into {VAULT}", flush=True)


if __name__ == "__main__":
    main()
