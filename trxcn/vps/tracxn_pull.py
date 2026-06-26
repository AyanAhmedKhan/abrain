#!/usr/bin/env python3
"""
Tracxn -> gbrain extractor (VPS entry point).

Examples
--------
  # by company name(s) (resolved via autocomplete)
  python tracxn_pull.py --names "Lenskart" "Paytm" "Zerodha"

  # by explicit company id(s)
  python tracxn_pull.py --ids 52bfc960e4b0420b03968ee8

  # from a file of ids (one per line) with detailed MCA financials, resumable
  python tracxn_pull.py --ids-file universe.txt --financials --resume

  # discover a universe from a saved Tracxn filter, then pull it
  python tracxn_pull.py --discover-file filter.json --resume

Auth & gbrain settings come from environment (see .env.example).
Every company is written to JSONL locally AND POSTed to gbrain (if configured).
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from typing import List, Set

from tracxn.config import Config
from tracxn.client import TracxnClient, AuthError
from tracxn.normalize import flatten, flatten_document
from tracxn.sinks import JsonlSink, GbrainSink, FanoutSink

log = logging.getLogger("tracxn.pull")


def load_processed(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    return {ln.strip() for ln in open(path, encoding="utf-8") if ln.strip()}


def mark_processed(path: str, company_id: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(company_id + "\n")


def gather_ids(client: TracxnClient, args) -> List[str]:
    ids: List[str] = []
    if args.ids:
        ids += args.ids
    if args.ids_file:
        ids += [ln.strip() for ln in open(args.ids_file, encoding="utf-8") if ln.strip()]
    if args.names:
        for nm in args.names:
            hits = client.resolve_ids(nm, size=1)
            if hits:
                log.info("resolved '%s' -> %s (%s)", nm, hits[0]["id"], hits[0]["name"])
                ids.append(hits[0]["id"])
            else:
                log.warning("no match for name '%s'", nm)
            time.sleep(client.cfg.delay_s)
    if args.discover_file:
        filt = json.load(open(args.discover_file, encoding="utf-8"))
        ids += [d["id"] for d in client.discover(filt, max_records=args.max) if d.get("id")]
    # de-dupe, preserve order
    seen, out = set(), []
    for i in ids:
        if i and i not in seen:
            seen.add(i); out.append(i)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Tracxn -> gbrain extractor")
    src = ap.add_argument_group("company source (combine freely)")
    src.add_argument("--names", nargs="+", help="company names (resolved via autocomplete)")
    src.add_argument("--ids", nargs="+", help="explicit 24-char company ids")
    src.add_argument("--ids-file", help="file with one company id per line")
    src.add_argument("--discover-file", help="JSON file holding a Tracxn filter object to page through")
    ap.add_argument("--financials", action="store_true", help="also pull detailed MCA statutory financials")
    ap.add_argument("--documents", action="store_true",
                    help="also emit one record per statutory filing (metadata + viewer URL)")
    ap.add_argument("--docs-since", type=int, metavar="YEAR",
                    help="with --documents, only filings on/after this filing year")
    ap.add_argument("--resume", action="store_true", help="skip ids already in the state file")
    ap.add_argument("--max", type=int, default=1000, help="max records when discovering")
    ap.add_argument("--limit", type=int, default=0, help="stop after N companies (0 = all)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config()
    client = TracxnClient(cfg)

    sinks = FanoutSink([JsonlSink(cfg.jsonl_path), GbrainSink(cfg)])
    processed = load_processed(cfg.state_path) if args.resume else set()

    try:
        ids = gather_ids(client, args)
        if not ids:
            log.error("no company ids to process — pass --names/--ids/--ids-file/--discover-file")
            return 2
        if args.resume:
            before = len(ids)
            ids = [i for i in ids if i not in processed]
            log.info("resume: %d/%d already done, %d remaining", before - len(ids), before, len(ids))
        if args.limit:
            ids = ids[: args.limit]

        log.info("processing %d companies (delay %dms, financials=%s, documents=%s)",
                 len(ids), cfg.delay_ms, args.financials, args.documents)
        ok = fail = docs_total = 0
        for n, cid in enumerate(ids, 1):
            try:
                c = client.profile(cid)
                row = flatten(c)
                if row is None:
                    log.warning("[%d/%d] %s -> empty profile", n, len(ids), cid)
                    fail += 1
                    continue
                if args.financials and row.get("legal_entity_ids"):
                    le = row["legal_entity_ids"].split("; ")[0]
                    try:
                        row["_statutory"] = client.statutory_financials(le)
                    except Exception as e:
                        log.warning("statutory pull failed for %s: %s", row["name"], e)
                sinks.push(row)
                ok += 1

                if args.documents and row.get("legal_entity_ids"):
                    ndocs = 0
                    for le in [x for x in row["legal_entity_ids"].split("; ") if x]:
                        try:
                            for rec in client.list_filings(le, since_year=args.docs_since):
                                sinks.push(flatten_document(rec, row, cfg.base))
                                ndocs += 1
                        except Exception as e:
                            log.warning("filings failed for %s (LE %s): %s", row["name"], le, e)
                        time.sleep(cfg.delay_s)
                    docs_total += ndocs
                    log.info("[%d/%d] %s  rev=%s INRcr  +%d docs",
                             n, len(ids), row["name"], row.get("revenue_inr_cr") or "-", ndocs)
                else:
                    log.info("[%d/%d] %s  rev=%s INRcr", n, len(ids), row["name"], row.get("revenue_inr_cr") or "-")

                mark_processed(cfg.state_path, cid)
            except AuthError as e:
                log.error("AUTH: %s", e)
                return 3
            except Exception as e:
                fail += 1
                log.error("[%d/%d] %s FAILED: %s", n, len(ids), cid, e)
            if n < len(ids):
                time.sleep(cfg.delay_s)

        log.info("DONE: %d companies ok, %d failed, %d document records -> %s",
                 ok, fail, docs_total, cfg.jsonl_path)
        return 0
    finally:
        sinks.close()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
