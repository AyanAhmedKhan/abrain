"""gbrain · person de-duplication by LinkedIn identity.

The same human is often extracted under name variants across call notes
("Shaurya" in one note, "Shaurya Prabhat" in another). Once enrichment assigns a
LinkedIn URL, the /in/<slug> is a STRONG deterministic identity key: all person
entities sharing a slug are one person. This pass collapses each such group into
ONE canonical node — moving edges, profile, observations, attrs and keys onto the
survivor and deleting the stubs — so the graph / CRM shows one card per person.

Survivor = the node that already has a scraped profile, else the fullest name
("Shaurya Prabhat" beats "Shaurya"), tie-broken by id. A profile-less survivor is
left UNmarked so the scraper still enriches it.

Deterministic · idempotent · no LLM · no API calls · safe to re-run.

    python -m workers.dedupe_persons            # dry-run: report groups, change nothing
    python -m workers.dedupe_persons --apply    # perform the merges (destructive)
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict

from workers.lib.db import connect


def _slug(url: str | None) -> str | None:
    """The /in/<slug> identity key (subdomain/case/query independent)."""
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1).strip("/").lower() if m else None


def _groups(conn) -> dict:
    """person entities grouped by LinkedIn slug, keeping only the collisions (>1)."""
    rows = conn.execute(
        "select id, canonical, attrs, "
        "exists(select 1 from gb_person_profile p where p.person_id=gb_entity.id) as has_profile "
        "from gb_entity where type='person' and coalesce(attrs->>'linkedin','')<>''"
    ).fetchall()
    g: dict = defaultdict(list)
    for r in rows:
        s = _slug((r["attrs"] or {}).get("linkedin"))
        if s:
            g[s].append(r)
    return {s: rs for s, rs in g.items() if len(rs) > 1}


def _survivor(rows: list) -> dict:
    return max(rows, key=lambda r: (bool(r["has_profile"]), len(r["canonical"] or ""), str(r["id"])))


def merge_into(conn, survivor_id, loser_id) -> None:
    """Move every reference off `loser` onto `survivor`, then delete the stub.
    Respects the gb_edge (src,rel,dst,envelope_id) unique constraint."""
    # outgoing edges
    conn.execute("insert into gb_edge (src,rel,dst,envelope_id,occurred_at) "
                 "select %s,rel,dst,envelope_id,occurred_at from gb_edge where src=%s "
                 "on conflict (src,rel,dst,envelope_id) do nothing", (survivor_id, loser_id))
    conn.execute("delete from gb_edge where src=%s", (loser_id,))
    # incoming edges
    conn.execute("insert into gb_edge (src,rel,dst,envelope_id,occurred_at) "
                 "select src,rel,%s,envelope_id,occurred_at from gb_edge where dst=%s "
                 "on conflict (src,rel,dst,envelope_id) do nothing", (survivor_id, loser_id))
    conn.execute("delete from gb_edge where dst=%s", (loser_id,))
    # drop any self-loop if the two nodes happened to be linked to each other
    conn.execute("delete from gb_edge where src=%s and dst=%s", (survivor_id, survivor_id))
    # profile: move only if the survivor lacks one (else loser's cascades on delete)
    conn.execute("update gb_person_profile set person_id=%s where person_id=%s "
                 "and not exists (select 1 from gb_person_profile where person_id=%s)",
                 (survivor_id, loser_id, survivor_id))
    # observations (financials normally sit on companies, but re-point to be safe)
    conn.execute("update gb_observation set entity_id=%s where entity_id=%s", (survivor_id, loser_id))
    # fill survivor attrs/keys from the loser WITHOUT overwriting the survivor's own
    conn.execute("update gb_entity s set attrs = l.attrs || s.attrs, keys = l.keys || s.keys "
                 "from gb_entity l where s.id=%s and l.id=%s", (survivor_id, loser_id))
    # delete the stub (cascades any remaining gb_person_profile row)
    conn.execute("delete from gb_entity where id=%s", (loser_id,))


def run(apply: bool = False) -> int:
    conn = connect()
    groups = _groups(conn)
    print(f"[dedupe] {len(groups)} duplicate-by-slug person group(s)", flush=True)
    merged = 0
    for slug, rows in sorted(groups.items()):
        s = _survivor(rows)
        losers = [r for r in rows if r["id"] != s["id"]]
        names = ", ".join(repr(r["canonical"]) for r in losers)
        print(f"  /in/{slug}: keep {s['canonical']!r}  <-  merge {names}", flush=True)
        if not apply:
            continue
        with conn.transaction():
            for l in losers:
                merge_into(conn, s["id"], l["id"])
            # a survivor with no profile must stay in the scraper's backfill set —
            # never inherit a loser's 'profile_scraped' flag (e.g. a stale 'dup').
            conn.execute(
                "update gb_entity set attrs = attrs - 'profile_scraped' where id=%s "
                "and not exists (select 1 from gb_person_profile where person_id=%s)",
                (s["id"], s["id"]))
        merged += len(losers)
    print(f"[dedupe] {('merged '+str(merged)+' stub(s)') if apply else 'dry-run — re-run with --apply'}",
          flush=True)
    return merged


def main():
    run(apply="--apply" in sys.argv)


if __name__ == "__main__":
    main()
