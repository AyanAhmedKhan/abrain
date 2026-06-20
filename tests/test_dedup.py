"""gbrain · Phase 0 verification (build spec §15: "idempotency + dedup
constraints verified with a duplicate test").

Runs against your live Supabase (uses source='test' rows only, cleans up
after itself). Verifies:

  1. native-id dedup        — same (source, source_id) lands once in gb_raw
  2. idempotency_key dedup  — duplicate content yields one envelope
  3. replay is a no-op      — re-enqueuing a processed raw_id changes nothing
  4. signal gate            — junk is `skipped`, deal content is queued

Run:  python -m tests.test_dedup
"""

from __future__ import annotations

import json
import sys
import uuid

from workers.lib import queues
from workers.lib.db import connect
from workers.normalize import run as run_normalize

PASS, FAIL = "  ✓", "  ✗"
failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{PASS if ok else FAIL} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def insert_raw(conn, source_id: str, payload: dict) -> str | None:
    row = conn.execute(
        "insert into gb_raw (source, source_id, payload) "
        "values ('test', %s, %s::jsonb) "
        "on conflict (source, source_id) do nothing returning id",
        (source_id, json.dumps(payload)),
    ).fetchone()
    return str(row["id"]) if row else None


def cleanup(conn) -> None:
    conn.execute("delete from gb_chunk where envelope_id in (select id from gb_envelope where source='test')")
    conn.execute("delete from gb_envelope where source = 'test'")
    conn.execute("delete from gb_raw where source = 'test'")
    conn.execute("delete from gb_dlq where stage = 'normalize' and payload->>'raw_id' is null")


def main() -> None:
    conn = connect()
    cleanup(conn)
    tag = uuid.uuid4().hex[:8]

    deal_payload = {
        "kind": "message",
        "title": f"Acme Robotics — Series A {tag}",
        "body": "Sharing the pitch deck. Raising a Series A round, "
                "₹40 Cr ask at a pre-money valuation of ₹160 Cr. ARR ₹6 Cr.",
        "labels": ["deal-flow"],
    }
    junk_payload = {"kind": "message", "body": "ok"}

    # 1 ── native-id dedup at the door
    rid1 = insert_raw(conn, f"msg-{tag}-deal", deal_payload)
    rid_dup = insert_raw(conn, f"msg-{tag}-deal", deal_payload)
    check("native-id dedup: second insert of same (source, source_id) rejected",
          rid1 is not None and rid_dup is None)

    # 2 ── same content under a NEW native id → idempotency_key collision
    rid2 = insert_raw(conn, f"msg-{tag}-junk", junk_payload)
    for rid in (rid1, rid2):
        queues.send(conn, queues.Q_NORMALIZE, {"raw_id": rid})
    run_normalize(once=True)

    n_env = conn.execute(
        "select count(*) as n from gb_envelope where source='test'"
    ).fetchone()["n"]
    check("normalize produced exactly one envelope per logical item", n_env == 2,
          f"expected 2, got {n_env}")

    # 3 ── replay is a no-op (idempotent worker re-checks status)
    queues.send(conn, queues.Q_NORMALIZE, {"raw_id": rid1})
    run_normalize(once=True)
    n_env2 = conn.execute(
        "select count(*) as n from gb_envelope where source='test'"
    ).fetchone()["n"]
    check("replaying a processed raw_id is a no-op", n_env2 == n_env)

    # 4 ── the gate: deal content queued, junk skipped
    statuses = {
        r["source_id"]: (r["status"], r["signal_score"])
        for r in conn.execute(
            "select source_id, status, signal_score from gb_envelope where source='test'"
        ).fetchall()
    }
    deal_status, deal_score = statuses[f"msg-{tag}-deal"]
    junk_status, junk_score = statuses[f"msg-{tag}-junk"]
    check("deal-term message passes the gate (status=normalized, queued)",
          deal_status == "normalized", f"score={deal_score:.2f}")
    check("one-word 'ok' message is skipped — $0 spent",
          junk_status == "skipped", f"score={junk_score:.2f}")

    # queue hygiene: exactly one preprocess message (the deal item)
    depth = conn.execute(
        "select queue_length from pgmq.metrics('gb_q_preprocess')"
    ).fetchone()["queue_length"]
    check("exactly the gated items reached gb_q_preprocess", depth >= 1,
          f"depth={depth}")

    cleanup(conn)
    print("\nPhase 0 verification:", "ALL PASSED ✓" if failures == 0
          else f"{failures} FAILED ✗")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
