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


def _li_slug(attrs, keys):
    """LinkedIn identity key for a person (subdomain/case/query independent)."""
    a, k = attrs or {}, keys or {}
    v = k.get("linkedin") or a.get("public_id") or a.get("linkedin") or ""
    m = re.search(r"/in/([^/?#]+)", v)
    s = (m.group(1) if m else v).strip("/").lower()
    return re.sub(r"[^a-z0-9]", "", s) or None


def _ptoks(name):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (name or "").lower())).strip().split()


def _person_signals(conn):
    """Per-person identity signals for resolution: LinkedIn slug, email, phone,
    companies worked at (works_at dst + attrs.company), and email threads
    (envelope_ids on their edges)."""
    sig = {}
    for r in conn.execute("select id, canonical, attrs, keys from gb_entity where type='person'").fetchall():
        a, k = r["attrs"] or {}, r["keys"] or {}
        comps = {_norm_co(a.get("company"))} if a.get("company") else set()
        threads = set()
        for e in conn.execute("select dst, rel, envelope_id from gb_edge where src=%s", (r["id"],)).fetchall():
            if e["rel"] == "works_at":
                comps.add(e["dst"])           # company entity id
            if e["envelope_id"]:
                threads.add(e["envelope_id"])
        sig[r["id"]] = {
            "id": r["id"], "name": r["canonical"], "toks": _ptoks(r["canonical"]),
            "li": _li_slug(a, k),
            "email": (k.get("email") or "").strip().lower() or None,
            "phone": re.sub(r"\D", "", k.get("phone") or "") or None,
            "comps": {c for c in comps if c}, "threads": threads,
            "has_profile": _has_profile(conn, r["id"], "person"),
            "deg": _deg(conn, r["id"]),
        }
    return sig


def _same_person(a, b):
    """Verify two person records are the same identity. Returns (merge, reason).
    HARD VETO on any conflicting strong key (different LinkedIn / email / phone) —
    a shorter name is NOT assumed to be the longer one (e.g. 'Amit' = Amit Mehta,
    not Amit Chawla). Positive: same LinkedIn / email / phone (decisive); or a
    contentless name-prefix stub corroborated by a shared company AND thread."""
    if a["li"] and b["li"] and a["li"] != b["li"]:
        return False, "different LinkedIn"
    if a["email"] and b["email"] and a["email"] != b["email"]:
        return False, "different email"
    if a["phone"] and b["phone"] and a["phone"] != b["phone"]:
        return False, "different phone"
    if a["li"] and a["li"] == b["li"]:
        return True, "same LinkedIn"
    if a["email"] and a["email"] == b["email"]:
        return True, "same email"
    if a["phone"] and a["phone"] == b["phone"]:
        return True, "same phone"
    # name-prefix stub: one is a contentless prefix of the other (no own identity
    # key), corroborated by BOTH a shared company AND a shared email thread.
    ta, tb = a["toks"], b["toks"]
    short, long_ = (a, b) if len(ta) <= len(tb) else (b, a)
    ts, tl = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if ts and len(ts) < len(tl) and tl[:len(ts)] == ts and not short["li"] and not short["email"]:
        shared_co = bool(short["comps"] & long_["comps"])
        shared_thr = bool(short["threads"] & long_["threads"])
        if shared_co and shared_thr:
            return True, "name-prefix + shared company + shared thread"
        if shared_co and short["deg"] == 0:
            return True, "name-prefix stub + shared company"
    return False, "unverified (name only)"


def person_clusters(conn, explain=False):
    """Identity-verified person duplicates via union-find over verified pairs."""
    sig = _person_signals(conn)
    ids = list(sig)
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    reasons = []
    # candidate pairs: same LinkedIn / email / phone, or name-compatible
    for i, ai in enumerate(ids):
        a = sig[ai]
        for bi in ids[i + 1:]:
            b = sig[bi]
            ta, tb = a["toks"], b["toks"]
            name_compat = ta and tb and (ta == tb or ta[:len(tb)] == tb or tb[:len(ta)] == ta)
            if not (name_compat or (a["li"] and a["li"] == b["li"])
                    or (a["email"] and a["email"] == b["email"])):
                continue
            ok, why = _same_person(a, b)
            if ok:
                parent[find(ai)] = find(bi)
                reasons.append((a["name"], b["name"], why))
            elif explain and name_compat:
                reasons.append((a["name"], b["name"], "SKIP: " + why))
    clusters = {}
    for i in ids:
        clusters.setdefault(find(i), []).append(
            {"id": sig[i]["id"], "canonical": sig[i]["name"]})
    out = [v for v in clusters.values() if len(v) > 1]
    # never merge a cluster that ended up with ≥2 distinct LinkedIn slugs
    safe = []
    for cl in out:
        slugs = {sig[m["id"]]["li"] for m in cl if sig[m["id"]]["li"]}
        if len(slugs) <= 1:
            safe.append(cl)
    return (safe, reasons) if explain else safe


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


def _person_keeper(conn, members):
    # prefer a scraped profile, then the fuller name, then most-connected
    return max(members, key=lambda m: (
        _has_profile(conn, m["id"], "person"),
        len((m["canonical"] or "").split()),
        _deg(conn, m["id"])))


def run(apply: bool):
    conn = connect()
    total = 0

    cc = company_clusters(conn)
    print(f"\n=== company clusters: {len(cc)} ===")
    for members in cc:
        keeper = _pick_keeper(conn, members, "company")
        for l in [m for m in members if m["id"] != keeper["id"]]:
            print(f"  KEEP {keeper['canonical']!r}  ← {l['canonical']!r}")
            if apply:
                _merge(conn, keeper, l, "company")
            total += 1

    pc, reasons = person_clusters(conn, explain=True)
    print(f"\n=== person clusters (identity-verified): {len(pc)} ===")
    for members in pc:
        keeper = _person_keeper(conn, members)
        for l in [m for m in members if m["id"] != keeper["id"]]:
            why = next((w for n1, n2, w in reasons
                        if {n1, n2} == {keeper["canonical"], l["canonical"]}), "")
            print(f"  KEEP {keeper['canonical']!r}  ← {l['canonical']!r}  [{why}]")
            if apply:
                _merge(conn, keeper, l, "person")
            total += 1

    skips = [(a, b, w[6:]) for a, b, w in reasons if w.startswith("SKIP")]
    if skips:
        print(f"\n=== NOT merged — kept distinct ({len(skips)}) ===")
        for a, b, w in skips:
            print(f"  {a!r} ≠ {b!r}  [{w}]")

    print(f"\n{'APPLIED' if apply else 'DRY-RUN'} · {total} merges"
          + ("" if apply else " (run with --apply to execute)"))


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
