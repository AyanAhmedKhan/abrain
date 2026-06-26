"""gbrain · load Tracxn company rows (JSONL) straight into the knowledge layer.

Tracxn data is already-structured company financials — the same shape as the
92-deal spine (`workers/seed_spine.py`) and the temporal `gb_observation` store.
So it BYPASSES the LLM pipeline entirely (no `gb_raw`, no Gemini): we upsert
companies into `gb_entity`, financials into `gb_observation` (source='Tracxn'),
and investors/key-people into `gb_entity` + `gb_edge`.

Input is the JSONL the extractor writes (`trxcn/vps/out/tracxn.jsonl`), one
flattened company per line (see `trxcn/vps/tracxn/normalize.flatten`). Numeric
fields may be "" when Tracxn has no value.

Usage:
  python -m workers.load_tracxn /opt/gbrain/trxcn/vps/out/tracxn.jsonl

Idempotent — re-running upserts entities, replaces this company's Tracxn
observations (keeps exactly one snapshot per metric), and never duplicates edges.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlsplit

from workers.lib.db import connect
from workers.lib.names import is_person_name
from workers.lib.taxonomy import canon_sector, canon_stage

SOURCE = "Tracxn"
CONFIDENCE = "Verified"          # Tracxn/MCA filings are authoritative
USD_M_TO_INR_CR = 8.5            # $1=₹85, then USD-million→INR-crore (×85 ÷10)

# financial metrics: (db metric, row value key, row as_on key, unit)
_METRICS = [
    ("revenue",    "revenue_inr_cr",    "revenue_as_on",    "INR_Cr"),
    ("ebitda",     "ebitda_inr_cr",     "ebitda_as_on",     "INR_Cr"),
    ("net_profit", "net_profit_inr_cr", "net_profit_as_on", "INR_Cr"),
    ("valuation",  "valuation_inr_cr",  "valuation_as_on",  "INR_Cr"),
]

_PERSON_ROLE_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")


def _doc_kind(row: dict) -> str:
    """Classify an MCA filing into a material kind for display, or 'Other' (noise).
    MCA dumps are ~80% administrative churn (resignations, optional attachments,
    KYC); we only graph the filings an analyst acts on."""
    dt = (row.get("document_type") or "")
    nm = (row.get("name") or "").lower()
    if dt == "Financial Documents" or "aoc-4" in nm or "financial statement" in nm or "balance sheet" in nm:
        return "Financials"
    if dt == "Annual Reports" or "mgt-7" in nm or "annual return" in nm:
        return "Annual Return"
    if dt == "Charge Documents" or "chg-" in nm:
        return "Charge"
    if dt == "Valuation Documents" or "valuation" in nm:
        return "Valuation"
    if "pas-3" in nm or "allottees" in nm or dt == "Changes to Capital Structure":
        return "Allotment/Capital"
    if "dpt-3" in nm:
        return "Deposits"
    return "Other"


# ── coercion helpers ─────────────────────────────────────────

def _num(v):
    """Tracxn numeric or '' → float | None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _str(v):
    s = (str(v).strip() if v is not None else "")
    return s or None


def _domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlsplit(website if "//" in website else "//" + website).netloc.lower()
    return host[4:] if host.startswith("www.") else host or None


def _period(as_on: str | None) -> str | None:
    """'2024-03-31' → 'FY24' (Indian fiscal-year label by ending year)."""
    if not as_on or len(as_on) < 4 or not as_on[:4].isdigit():
        return None
    return f"FY{as_on[2:4]}"


def _primary_sector(path: str | None) -> str | None:
    """Tracxn sector is a path 'Consumer > Fashion Tech > …' → canon first segment."""
    if not path:
        return None
    return canon_sector(path.split(">")[0].strip())


# ── entity / edge primitives (psycopg autocommit; see seed_spine) ──

def upsert(conn, etype, canonical, attrs=None, keys=None):
    """Upsert by (type, canonical); MERGE attrs and keys so existing rows are
    enriched in place, never clobbered."""
    if not canonical or not canonical.strip():
        return None
    return conn.execute(
        """insert into gb_entity (type, canonical, attrs, keys)
           values (%s,%s,%s::jsonb,%s::jsonb)
           on conflict (type, canonical) do update
             set attrs = gb_entity.attrs || excluded.attrs,
                 keys  = gb_entity.keys  || excluded.keys
           returning id""",
        (etype, canonical.strip(), json.dumps(attrs or {}), json.dumps(keys or {})),
    ).fetchone()["id"]


def link(conn, src, rel, dst) -> bool:
    """Idempotent edge insert. gb_edge's unique key includes envelope_id, which is
    NULL here — and NULLs are distinct under a UNIQUE constraint, so `on conflict`
    would NOT dedup. Guard with NOT EXISTS instead."""
    if not (src and dst):
        return False
    return bool(conn.execute(
        """insert into gb_edge (src, rel, dst)
           select %s,%s,%s
           where not exists (
             select 1 from gb_edge
             where src=%s and rel=%s and dst=%s and envelope_id is null)
           returning id""",
        (src, rel, dst, src, rel, dst),
    ).fetchone())


def _replace_observation(conn, entity_id, metric, value_num, unit, period, as_of) -> None:
    """Keep exactly one Tracxn observation per (entity, metric): delete then insert."""
    conn.execute(
        "delete from gb_observation where entity_id=%s and metric=%s and source=%s",
        (entity_id, metric, SOURCE),
    )
    conn.execute(
        """insert into gb_observation
             (entity_id, metric, value_num, unit, period, as_of, source, confidence)
           values (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (entity_id, metric, value_num, unit, period, as_of or None, SOURCE, CONFIDENCE),
    )


# ── per-company load ─────────────────────────────────────────

def load_company(conn, row: dict, name_map: dict) -> dict:
    """Load one flattened Tracxn company row. Returns per-row counts.

    name_map ({tracxn_id: gbrain_canonical}) lets us upsert under the EXISTING
    gbrain name so Tracxn enriches the right entity in place even when Tracxn's
    own name differs (e.g. 'Agarwal' vs 'Agarwal Packers & Movers')."""
    name = name_map.get(row.get("id")) or _str(row.get("name"))
    if not name:
        return {"skipped": 1}

    sector = _primary_sector(row.get("sector"))
    hq = ", ".join(p for p in (_str(row.get("city")), _str(row.get("country"))) if p) or None
    rev, ebitda, val = _num(row.get("revenue_inr_cr")), _num(row.get("ebitda_inr_cr")), _num(row.get("valuation_inr_cr"))
    funding_usd_m = _num(row.get("total_equity_funding_usd_m"))
    funding_inr_cr = round(funding_usd_m * USD_M_TO_INR_CR, 2) if funding_usd_m is not None else None
    employees = _num(row.get("employee_count"))
    as_ons = [row.get(k) for _, _, k, _ in _METRICS if row.get(k)]
    enrich_as_of = max(as_ons) if as_ons else None  # ISO dates sort lexically

    # company attrs — only include present values so we never overwrite good data
    # with blanks; the gb_company view reads these mirror fields directly.
    attrs = {
        "sector": sector,
        "sector_path": _str(row.get("sector")),
        "hq": hq,
        "url": _str(row.get("website")),
        "stage": canon_stage(_str(row.get("stage"))),
        "tagline": _str(row.get("short_description")),
        "tracxn_score": _num(row.get("tracxn_score")),
        "tracxn_url": _str(row.get("tracxn_url")),
        "revenue_inr_cr": rev,
        "revenue_period": _period(row.get("revenue_as_on")),
        "revenue_as_of": _str(row.get("revenue_as_on")),
        "revenue_source": SOURCE,
        "ebitda_inr_cr": ebitda,
        "valuation_inr_cr": val,
        "total_funding_inr_cr": funding_inr_cr,
        "employee_count": int(employees) if employees is not None else None,
        "founding_year": int(_num(row.get("founded"))) if _num(row.get("founded")) else None,
        "enrichment_as_of": enrich_as_of,
    }
    attrs = {k: v for k, v in attrs.items() if v is not None}
    keys = {k: v for k, v in {
        "tracxn_id": _str(row.get("id")),
        "domain": _domain(row.get("website")),
    }.items() if v is not None}

    counts = {"companies": 0, "observations": 0, "investor_links": 0, "people_links": 0}
    with conn.transaction():
        cid = upsert(conn, "company", name, attrs, keys)
        counts["companies"] = 1

        for metric, vkey, akey, unit in _METRICS:
            v = _num(row.get(vkey))
            if v is not None:
                _replace_observation(conn, cid, metric, v, unit, _period(row.get(akey)), _str(row.get(akey)))
                counts["observations"] += 1
        if employees is not None:
            _replace_observation(conn, cid, "employees", employees, "count", None, None)
            counts["observations"] += 1
        if funding_inr_cr is not None:
            _replace_observation(conn, cid, "funding", funding_inr_cr, "INR_Cr", None, None)
            counts["observations"] += 1

        for inv in _split_list(row.get("investors")):
            iid = upsert(conn, "investor", inv, {"source": SOURCE}, {})
            # 'invests_in' (investor→company) is the live convention written by
            # workers/investors.py and read by the gb_investor_portfolio view.
            if link(conn, iid, "invests_in", cid):
                counts["investor_links"] += 1

        for label in _split_list(row.get("key_people")):
            pname, role = _parse_person(label)
            if not pname or not is_person_name(pname):
                continue
            pattrs = {"company": name, "source": SOURCE}
            if role:
                pattrs["role"] = role
            pid = upsert(conn, "person", pname, pattrs, {})
            if link(conn, pid, "works_at", cid):
                counts["people_links"] += 1
    return counts


def load_document(conn, row: dict, name_map: dict) -> dict:
    """Load one Tracxn statutory-filing record → a document entity linked to its
    company. We store metadata + the durable viewer_url only; the PDF binary is
    resolved on demand via tracxn.resolve.fetch_pdf (raw S3 links are expiring),
    so nothing is downloaded here."""
    cname = name_map.get(row.get("company_id")) or _str(row.get("company_name"))
    doc_name = _str(row.get("name")) or "Filing"
    kind = _doc_kind(row)
    if not cname or kind == "Other":   # skip noise — only material filings are graphed
        return {"skipped": 1}
    filing_date = _str(row.get("filing_date"))
    canonical = f"{cname} — {doc_name}" + (f" ({filing_date})" if filing_date else "")
    attrs = {k: v for k, v in {
        "doc_type": _str(row.get("document_type")),
        "filing_kind": kind,
        "file_type": "pdf",
        "company": cname,
        "source_url": _str(row.get("viewer_url")),
        "doc_date": filing_date,
        "confidentiality": "public",          # MCA statutory filings are public record
        "category": _str(row.get("category")),
        "filing_type": _str(row.get("filing_type")),
        "registrar": _str(row.get("registrar")),
        "document_code": _str(row.get("document_code")),
        "source": SOURCE,
    }.items() if v is not None}
    keys = {k: v for k, v in {
        "tracxn_doc_id": _str(row.get("id")),
        "tracxn_company_id": _str(row.get("company_id")),
        "cin": _str(row.get("cin")),
    }.items() if v is not None}
    ckeys = {"tracxn_id": _str(row.get("company_id"))} if _str(row.get("company_id")) else {}
    with conn.transaction():
        cid = upsert(conn, "company", cname, {}, ckeys)   # find-or-create the company node
        did = upsert(conn, "document", canonical, attrs, keys)
        linked = link(conn, did, "about", cid)
    return {"documents": 1, "doc_links": 1 if linked else 0}


def _split_list(s) -> list[str]:
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def _parse_person(label: str) -> tuple[str | None, str | None]:
    m = _PERSON_ROLE_RE.match(label or "")
    if m:
        return (_str(m.group(1)), _str(m.group(2)))
    return (_str(label), None)


# ── driver ───────────────────────────────────────────────────

def load_jsonl(conn, path: str, name_map: dict | None = None) -> dict:
    name_map = name_map or {}
    total = {"companies": 0, "observations": 0, "investor_links": 0, "people_links": 0,
             "documents": 0, "doc_links": 0, "skipped": 0, "errors": 0}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                total["errors"] += 1
                continue
            if not isinstance(row, dict):
                total["errors"] += 1
                continue
            handler = load_document if row.get("kind") == "document" else load_company
            try:
                for k, v in handler(conn, row, name_map).items():
                    total[k] = total.get(k, 0) + v
            except Exception as e:  # noqa: BLE001 — one bad row never aborts the load
                total["errors"] += 1
                print(f"  ! {row.get('name', '?')}: {e}", file=sys.stderr)
    return total


def main(path: str, name_map_path: str | None = None) -> None:
    conn = connect()
    name_map = {}
    if name_map_path:
        with open(name_map_path, encoding="utf-8") as fh:
            name_map = json.load(fh)
    t = load_jsonl(conn, path, name_map)
    print(
        f"tracxn loaded: {t['companies']} companies · {t['observations']} observations · "
        f"{t['investor_links']} investor links · {t['people_links']} people links · "
        f"{t['documents']} documents ({t['doc_links']} linked) "
        f"[{t['skipped']} skipped, {t['errors']} errors]"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m workers.load_tracxn <tracxn.jsonl> [name_map.json]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
