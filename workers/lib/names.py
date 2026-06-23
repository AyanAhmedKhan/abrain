"""gbrain · shared person-name quality gate.

Single source of truth used by ingestion (extract.fan_out), enrichment, and the
Obsidian export. Rejects extraction artifacts that are NOT real people — role
buckets, section headers, departments, placeholders ("Active US Founder",
"CEO/Founder", "Deals", "HR Operations", "The Team", "Promoter") — so they never
become person entities, get LinkedIn-searched, or pollute people listings.
"""

from __future__ import annotations

import re

# tokens that are roles/sections/departments, never a real personal name
ROLE_TOKENS = {
    "founder", "founders", "cofounder", "co-founder", "ceo", "cfo", "cto", "coo",
    "cmo", "cxo", "chairman", "chairperson", "promoter", "promoters", "director",
    "accounts", "account", "finance", "sales", "marketing", "admin", "hr", "hrops",
    "ops", "operations", "legal", "support", "deals", "deal", "mentions", "mention",
    "dormant", "active", "investor", "investors", "advisor", "advisors", "team",
    "unknown", "tbd", "na", "contact", "contacts", "info", "promoter", "everyone",
    "entire", "group", "management", "founderceo",
}
_NAME_OK = re.compile(r"^[A-Za-z][A-Za-z.'\- ]+$")


def name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[\s.]+", (name or "")) if t]


def is_person_name(name: str) -> bool:
    """True only for a plausible human name: letters/space/.'- , ≥3 chars, no
    digits/slashes/@, and no role/section/placeholder token (split on space, dot
    AND hyphen so 'CEO-Founder' is caught)."""
    n = (name or "").strip()
    if len(n) < 3 or any(c.isdigit() for c in n) or "/" in n or "@" in n:
        return False
    if not _NAME_OK.match(n):
        return False
    parts = [p for p in re.split(r"[\s.\-]+", n.lower()) if p]
    return not any(p in ROLE_TOKENS for p in parts)
