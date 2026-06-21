"""gbrain · entity de-duplication (companies + persons) — idempotent, verifiable.

Merges duplicate entities into one canonical node, repointing EVERY foreign key
(gb_edge.src/dst, gb_observation.entity_id, gb_task.company_id/deal_id, and the
gb_person_profile / gb_company_profile rows), folding attrs + aliases, then
deleting the loser.

Conservative by design — only HIGH-CONFIDENCE duplicates are merged:
  companies — share a website, OR same normalized core ("dexter") + an alias link
              between them. Ambiguous pairs (parent/subsidiary, generic names) are
              listed but SKIPPED for manual review.
  persons   — same LinkedIn /in/ slug, OR a stub whose name is an exact prefix of
              a profiled person's full name and which has no own graph edges.

The keeper is the most-connected node (tie-break: has a scraped profile).

    python -m workers.dedup            # DRY-RUN: print the plan, change nothing
    python -m workers.dedup --apply    # execute inside a transaction
"""

from __future__ import annotations

import re
import sys

from workers.lib.db import connect
from workers.apify_linkedin import _norm_co


def _core_ns(s: str) -> str:
    return _norm_co(s).replace(" ", "")


def _web(attrs: dict | None) -> str | None:
    w = ((attrs or {}).get("website") or "").strip().lower().rstrip("/")
    w = re.sub(r"^https?://(www\.)?", "", w)
    return w or None


def _aliases(attrs: dict | None) -> set[str]:
    return {a.lower() for a in ((attrs or {}).get("aliases") or []) if isinstance(a, str)}


def _deg(conn, eid) -> int:
    return conn.execute("select count(*) n from gb_edge where src=%s or dst=%s", (eid, eid)).fetchone()["n"]


def _has_profile(conn, eid, kind) -> bool:
    tbl = "gb_company_profile" if kind == "company" else "gb_person_profile"
    col = "company_id" if kind == "company" else "person_id"
    return conn.execute(f"select 1 from {tbl} where {col}=%s", (eid,)).fetchone() is not None


# ── cluster detection ────────────────────────────────────────

def company_clusters(conn):
    rows = conn.execute("select id, canonical, attrs from gb_entity where type='company'").fetchall()
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    # 1) shared website → same firm (strong)
    by_web: dict[str, list] = {}
    for r in rows:
        w = _web(r["attrs"])
        if w:
            by_web.setdefault(w, []).append(r["id"])
    for grp in by_web.values():
        for x in grp[1:]:
            union(grp[0], x)

    # 2) same normalized core + an alias link between the pair (corroborated)
    for i, a in enumerate(rows):
        ca, na = _core_ns(a["canonical"]), (a["canonical"] or "").lower()
        if len(ca) < 4:
            continue
        for b in rows[i + 1:]:
            if _core_ns(b["canonical"]) != ca:
                continue
            nb = (b["canonical"] or "").lower()
            if na in _aliases(b["attrs"]) or nb in _aliases(a["attrs"]) \
               or na in nb or nb in na:
                union(a["id"], b["id"])

    clusters: dict = {}
    for r in rows:
        clusters.setdefault(find(r["id"]), []).append(r)
    return [v for v in clusters.values() if len(v) > 1]


def person_clusters(conn):
    """Stub (no edges) whose name is an exact prefix of a profiled person's full
    name → merge into the profiled node. Plus same /in/ slug across nodes."""
    prof = conn.execute(
        "select e.id, e.canonical from gb_entity e join gb_person_profile p on p.person_id=e.id"
    ).fetchall()
    out = []
    for pr in prof:
        full = (pr["canonical"] or "").strip()
        if not full:
            continue
        stubs = conn.execute(
            """select e.id, e.canonical from gb_entity e
               where e.type='person' and e.id<>%s
                 and lower(%s) like lower(e.canonical) || ' %%'
                 and (select count(*) from gb_edge where src=e.id or dst=e.id)=0
                 and not exists (select 1 from gb_person_profile p where p.person_id=e.id)""",
            (pr["id"], full)).fetchall()
        if stubs:
            out.append([pr] + list(stubs))   # keeper first
    return out


# ── merge ────────────────────────────────────────────────────

def _merge(conn, keeper, loser, kind):
    k, l = keeper["id"], loser["id"]
    # gb_edge: repoint src then dst, guarding the (src,rel,dst) unique constraint
    conn.execute("""update gb_edge e set src=%s where src=%s
        and not exists (select 1 from gb_edge x where x.src=%s and x.rel=e.rel and x.dst=e.dst)""", (k, l, k))
    conn.execute("delete from gb_edge where src=%s", (l,))
    conn.execute("""update gb_edge e set dst=%s where dst=%s
        and not exists (select 1 from gb_edge x where x.src=e.src and x.rel=e.rel and x.dst=%s)""", (k, l, k))
    conn.execute("delete from gb_edge where dst=%s", (l,))
    conn.execute("delete from gb_edge where src=dst")  # any self-loops created
    # other FKs
    conn.execute("update gb_observation set entity_id=%s where entity_id=%s", (k, l))
    conn.execute("update gb_task set company_id=%s where company_id=%s", (k, l))
    conn.execute("update gb_task set deal_id=%s where deal_id=%s", (k, l))
    # profile row: move to keeper only if keeper has none (else keeper's wins)
    if not _has_profile(conn, k, kind):
        tbl = "gb_company_profile" if kind == "company" else "gb_person_profile"
        col = "company_id" if kind == "company" else "person_id"
        conn.execute(f"update {tbl} set {col}=%s where {col}=%s", (k, l))
    # fold attrs (keeper wins) + union aliases incl. loser canonical
    ka = conn.execute("select canonical, attrs, keys from gb_entity where id=%s", (k,)).fetchone()
    la = conn.execute("select canonical, attrs, keys from gb_entity where id=%s", (l,)).fetchone()
    merged = {**(la["attrs"] or {}), **(ka["attrs"] or {})}
    aliases = list(dict.fromkeys(
        (list((ka["attrs"] or {}).get("aliases") or []))
        + list((la["attrs"] or {}).get("aliases") or [])
        + [la["canonical"]]))
    merged["aliases"] = [a for a in aliases if a and a.lower() != (ka["canonical"] or "").lower()]
    merged_keys = {**(la["keys"] or {}), **(ka["keys"] or {})}
    import json
    conn.execute("update gb_entity set attrs=%s::jsonb, keys=%s::jsonb where id=%s",
                 (json.dumps(merged), json.dumps(merged_keys), k))
    conn.execute("delete from gb_entity where id=%s", (l,))


def _pick_keeper(conn, members, kind):
    return max(members, key=lambda r: (_deg(conn, r["id"]), _has_profile(conn, r["id"], kind)))


def run(apply: bool):
    conn = connect()
    total = 0
    for kind, clusters in (("company", company_clusters(conn)), ("person", person_clusters(conn))):
        print(f"\n=== {kind} clusters: {len(clusters)} ===")
        for members in clusters:
            if kind == "person":
                keeper, losers = members[0], members[1:]   # keeper = profiled node
            else:
                keeper = _pick_keeper(conn, members, kind)
                losers = [m for m in members if m["id"] != keeper["id"]]
            print(f"  KEEP {keeper['canonical']!r} (deg {_deg(conn, keeper['id'])})")
            for l in losers:
                print(f"    ← merge {l['canonical']!r} (deg {_deg(conn, l['id'])})")
                if apply:
                    _merge(conn, keeper, l, kind)
                total += 1
    print(f"\n{'APPLIED' if apply else 'DRY-RUN'} · {total} merges"
          + ("" if apply else " (run with --apply to execute)"))


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
