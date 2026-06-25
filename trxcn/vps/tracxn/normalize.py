"""
Flatten a Tracxn /api/4.0/companies profile record into one flat dict.

This is a faithful Python port of the JS flattener that was validated live
against Lenskart, Meller, Paytm, Stripe and Zerodha (negatives, missing
financials, foreign/USD base, empty investors all handled).

Money is normalised to:
  *_inr_cr  = INR crore   (amount.INR.value / 1e7)
  *_usd_m   = USD million (amount.USD.value / 1e6)
each paired with an `as_on` fiscal date — matching the vault's INR-crore rule.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


def _fy(d: Optional[dict]) -> str:
    if not d or not d.get("year"):
        return ""
    return f'{d["year"]:04d}-{d.get("month", 1):02d}-{d.get("day", 1):02d}'


def _money(m: Optional[dict]) -> Dict[str, Any]:
    """Tracxn money object -> {inr_cr, usd_m, as_on, growth_1y/3y/5y}."""
    if not m or not isinstance(m, dict) or not m.get("amount"):
        return {}
    amt = m.get("amount") or {}
    inr = (amt.get("INR") or {}).get("value")
    usd = (amt.get("USD") or {}).get("value")
    g = m.get("growthDetails") or {}

    def cagr(period):
        return (g.get(period) or {}).get("CAGR")

    return {
        "inr_cr": round(inr / 1e7, 2) if isinstance(inr, (int, float)) else "",
        "usd_m": round(usd / 1e6, 2) if isinstance(usd, (int, float)) else "",
        "as_on": _fy(m.get("asOnDate")),
        "growth_1y": cagr("oneYear"),
        "growth_3y": cagr("threeYear"),
        "growth_5y": cagr("fiveYear"),
    }


def _sector_path(tax: Any) -> str:
    """primaryTaxonomy is an array of path-arrays of {name,...}."""
    try:
        return " > ".join(n.get("name", "") for n in tax[0])
    except Exception:
        return ""


def _loc(locations: Any) -> Dict[str, str]:
    l = (locations or [{}])[0] if locations else {}
    return {
        "city": (l.get("city") or {}).get("name", ""),
        "state": (l.get("state") or {}).get("name", ""),
        "country": (l.get("country") or {}).get("name", ""),
    }


def _names(arr: Any, fn, n: int = 5) -> str:
    if not isinstance(arr, list):
        return ""
    out = []
    for item in arr[:n]:
        try:
            v = fn(item)
        except Exception:
            v = None
        if v:
            out.append(v)
    return "; ".join(out)


def _investor_name(i: dict) -> Optional[str]:
    return i.get("name") or (i.get("institutionalInvestor") or {}).get("name")


def _person_label(p: dict) -> Optional[str]:
    nm = p.get("name") or (p.get("person") or {}).get("name")
    role = p.get("designation") or p.get("role")
    if not role and isinstance(p.get("roles"), list) and p["roles"]:
        role = p["roles"][0]
    if not nm:
        return None
    return f"{nm} ({role})" if role else nm


def flatten(c: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not c:
        return None
    rev, ebitda = _money(c.get("latestRevenue")), _money(c.get("latestEBITDA"))
    npf, val = _money(c.get("latestNetProfit")), _money(c.get("latestValuation"))
    L = _loc(c.get("locations"))
    emp = c.get("latestEmployeeCount")
    tef = c.get("totalEquityFunding") or {}
    tef_usd = (((tef.get("amount") or {}).get("USD")) or {}).get("value")
    score = c.get("tracxnScore")
    websites = c.get("website") or []

    return {
        "id": c.get("id", ""),
        "name": c.get("name", ""),
        "website": (websites[0].get("url") if websites else "") or "",
        "founded": c.get("foundedYear", "") or "",
        "stage": c.get("stage", "") or "",
        "city": L["city"],
        "country": L["country"],
        "sector": _sector_path(c.get("primaryTaxonomy")),
        "short_description": " ".join((c.get("shortDescription") or "").split()),
        "revenue_inr_cr": rev.get("inr_cr", ""),
        "revenue_usd_m": rev.get("usd_m", ""),
        "revenue_as_on": rev.get("as_on", ""),
        "revenue_growth_1y": rev.get("growth_1y", ""),
        "revenue_growth_3y": rev.get("growth_3y", ""),
        "ebitda_inr_cr": ebitda.get("inr_cr", ""),
        "ebitda_as_on": ebitda.get("as_on", ""),
        "net_profit_inr_cr": npf.get("inr_cr", ""),
        "net_profit_as_on": npf.get("as_on", ""),
        "valuation_inr_cr": val.get("inr_cr", ""),
        "valuation_usd_m": val.get("usd_m", ""),
        "valuation_as_on": val.get("as_on", ""),
        "employee_count": (emp.get("value") if isinstance(emp, dict) else emp) or "",
        "total_equity_funding_usd_m": round(tef_usd / 1e6, 2) if isinstance(tef_usd, (int, float)) else "",
        "tracxn_score": (score.get("value") if isinstance(score, dict) else score) or "",
        "investors": _names(c.get("investors"), _investor_name),
        "key_people": _names(c.get("keyPeople"), _person_label),
        "legal_entity_ids": "; ".join(e.get("id", "") for e in (c.get("legalEntities") or [])),
        "tracxn_url": c.get("tracxnPlatformUrl", "") or "",
    }


# Column order for CSV / tabular consumers
COLUMNS: List[str] = list(flatten({"id": "", "name": ""}).keys())
