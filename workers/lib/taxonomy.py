"""gbrain · taxonomy & entity-typing rules (from the vault's AGENTS/SKILL rules).

Single source of truth for: canonical sector/stage names, VC/PE/VD/IB/Law-Firm
typing, the Dexter Capital team roster, and alias generation. Used by the
Obsidian export and (mirrored) by the SQL gold views.
"""

from __future__ import annotations

import re

# ── canonical sectors (variant → canonical) ──────────────────
_SECTOR_MERGE = {
    "AdTech": ["advertising", "marketing tech", "martech"],
    "B2B": ["b2b commerce", "b2b marketplace", "b2b services"],
    "Beauty & Personal Care": ["beauty", "personal care", "bpc"],
    "Climate": ["cleantech", "clean tech", "sustainability", "carbon markets", "climate tech"],
    "Consumer": ["consumer brands", "fmcg", "cpg"],
    "Consumer Tech": ["consumer internet", "consumer technology"],
    "Deep Tech": ["deeptech"],
    "Defence": ["defence tech", "defense", "defense tech"],
    "E-commerce": ["marketplace", "ecommerce", "e commerce"],
    "Fintech": ["financial services", "banking", "nbfc", "financial", "finance"],
    "Food": ["f&b", "food & beverage", "food and beverage", "beverages", "foodtech"],
    "Healthcare": ["health & wellness", "health and wellness", "hospitals", "health", "healthtech", "health tech"],
    "Logistics": ["supply chain", "logistics & mobility", "logistics and mobility"],
    "Manufacturing": ["industrial", "engineering services", "industrials"],
    "Media": ["entertainment", "media & entertainment"],
    "Real Estate": ["proptech", "prop tech", "real-estate"],
    "SaaS": ["software", "enterprise software", "enterprise tech", "enterprise technology"],
    "Services": ["it services", "professional services"],
    "Venture Capital": ["vc"],
    "Private Equity": ["pe"],
    "Venture Debt": ["venture debt", "private credit"],
    "Asset Management": ["asset management", "am"],
}
_SECTOR_LOOKUP = {}
for canon, variants in _SECTOR_MERGE.items():
    _SECTOR_LOOKUP[canon.lower()] = canon
    for v in variants:
        _SECTOR_LOOKUP[v.lower()] = canon

_STAGE_MERGE = {
    "Seed": ["pre-seed", "preseed", "early stage", "early-stage", "early growth", "venture"],
    "Pre-Series A": ["pre series a", "pre-series-a"],
    "Series A": [], "Series B": [], "Series C": [],
    "Growth": ["stage-agnostic", "growth equity", "growth stage"],
    "Late Stage": ["pre-ipo", "post-ipo", "late-stage"],
    "Buyout": ["control", "control buyouts", "m&a", "minority stakes", "acquisition"],
    "Private Credit": ["debt", "structured credit", "special situations"],
}
_STAGE_LOOKUP = {}
for canon, variants in _STAGE_MERGE.items():
    _STAGE_LOOKUP[canon.lower()] = canon
    for v in variants:
        _STAGE_LOOKUP[v.lower()] = canon


def canon_sector(s: str | None) -> str | None:
    if not s:
        return None
    key = s.strip().lower()
    if key in _SECTOR_LOOKUP:
        return _SECTOR_LOOKUP[key]
    # unknown → keep, but Title Case while preserving common tech casing
    t = s.strip()
    return t


def canon_stage(s: str | None) -> str | None:
    if not s:
        return None
    return _STAGE_LOOKUP.get(s.strip().lower(), s.strip())


# ── entity typing (vc/pe/vd/am/ib/lawfirm/company) ───────────
def entity_type(sector: str | None, name: str = "", summary: str = "") -> str:
    t = f"{sector or ''} {name or ''} {summary or ''}".lower()
    if "venture debt" in t or "private credit" in t:
        return "vd"
    if "private equity" in t:
        return "pe"
    if "asset management" in t or "asset manager" in t:
        return "am"
    if "venture capital" in t or re.search(r"\bvc\b", t) or "micro-vc" in t:
        return "vc"
    if "law firm" in t or "legal counsel" in t or "law offices" in t:
        return "lawfirm"
    if "investment bank" in t or "merchant bank" in t or ("advisory" in t and "fund" not in t):
        return "ib"
    return "company"


TYPE_CATEGORY = {
    "vc": "Venture Capital", "pe": "Private Equity", "vd": "Venture Debt",
    "am": "Asset Management", "ib": "Investment Banking", "lawfirm": "Law Firm",
}


def is_investor(etype: str) -> bool:
    return etype in ("vc", "pe", "vd", "am")


# ── Dexter Capital team ──────────────────────────────────────
DEXTER_DOMAINS = ("dextercapital.in", "dexter.ventures", "discoverventures.in")
DEXTER_TEAM = {
    "Devendra Agrawal", "Rohit Singh", "Divyanshu Tambe", "Gaurav Goyal",
    "Ashish Mathur", "Abhijeet Dhar", "Bindu Reddy", "Vishal Maniar",
    "Jaideep Singh Gaur", "Mailinie Jauhar", "Pavan Palepu", "Aniruddh Shenvi",
    "Himanshu Arora", "Sudhir Gouda", "Karthikeyan Janagaraj", "Jatin Verma",
    "Yash Garg", "Priyansh Gupta", "Pavani Mehrotra", "Khushi Punamiya",
    "Divya Nallapu", "Rishabh Jain", "Shanaya Sharma", "Yash Shivani",
    "Harshul Bansal",
}


def is_dexter_email(email: str | None) -> bool:
    return bool(email) and any(email.lower().endswith("@" + d) for d in DEXTER_DOMAINS)


def name_from_email(email: str) -> str:
    local = email.split("@")[0]
    return " ".join(w.capitalize() for w in re.split(r"[._-]+", local) if w)


# ── alias generation ─────────────────────────────────────────
_SUFFIXES = {"ventures", "venture", "capital", "partners", "technologies",
             "technology", "limited", "ltd", "pvt", "private", "inc", "llp",
             "fund", "funds", "solutions", "labs", "systems", "global",
             "group", "company", "co", "india", "&"}


def make_aliases(name: str) -> list[str]:
    if not name:
        return []
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    out = []
    core = [w for w in words if w.lower().strip(".,&") not in _SUFFIXES]
    if core and len(core) < len(words):
        short = " ".join(core)
        if short and short.lower() != name.lower():
            out.append(short)
    if len(core) >= 2:
        acro = "".join(w[0] for w in core if w[:1].isalnum()).upper()
        if 2 <= len(acro) <= 6:
            out.append(acro)
    seen, uniq = set(), []
    for a in out:
        if a.lower() not in seen and a.lower() != name.lower():
            seen.add(a.lower())
            uniq.append(a)
    return uniq
