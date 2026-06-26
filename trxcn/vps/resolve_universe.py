#!/usr/bin/env python3
"""Resolve gbrain company NAMES -> Tracxn ids (one autocomplete call each), so the
rest of the flow runs on stable ids and enriches the RIGHT gbrain entity in place.

Produces two artifacts:
  out/universe_ids.txt  — one Tracxn company id per line  (feed: tracxn_pull --ids-file)
  out/name_map.json     — {tracxn_id: gbrain_canonical}    (feed: load_tracxn <jsonl> name_map)

The name_map matters because Tracxn's own name often differs from gbrain's
canonical (e.g. "Agarwal" vs "Agarwal Packers & Movers"); mapping ids back to the
gbrain name lets load_tracxn upsert the existing company instead of a duplicate.

Usage:
  python resolve_universe.py [names_file]      # default: out/universe_names.txt
"""
from __future__ import annotations
import json
import os
import sys
import time

from tracxn.config import Config
from tracxn.client import TracxnClient


def main(names_path: str) -> int:
    names = [l.strip() for l in open(names_path, encoding="utf-8") if l.strip()]
    cfg = Config()
    client = TracxnClient(cfg)
    name_map: dict[str, str] = {}
    ids: list[str] = []
    misses: list[str] = []
    try:
        for nm in names:
            hits = client.resolve_ids(nm, size=1)
            if hits:
                tid = hits[0]["id"]
                if tid not in name_map:          # first gbrain name wins a given id
                    name_map[tid] = nm
                    ids.append(tid)
                print(f"  {nm}  ->  {tid}  ({hits[0]['name']})")
            else:
                misses.append(nm)
                print(f"  {nm}  ->  NO MATCH")
            time.sleep(cfg.delay_s)
    finally:
        client.close()

    os.makedirs("out", exist_ok=True)
    with open("out/universe_ids.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(ids) + ("\n" if ids else ""))
    with open("out/name_map.json", "w", encoding="utf-8") as f:
        json.dump(name_map, f, indent=1, ensure_ascii=False)

    print(f"\nresolved {len(ids)}/{len(names)} ({len(misses)} misses) "
          f"-> out/universe_ids.txt + out/name_map.json")
    if misses:
        print("misses:", ", ".join(misses))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/universe_names.txt"))
