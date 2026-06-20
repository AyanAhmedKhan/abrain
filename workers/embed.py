"""gbrain · embed + finalize worker (Stages 5–6 for M1).

Reads gb_q_embed. For each envelope: batch-embed its chunks
(gemini-embedding-001 @ 768 dims) → write vectors into pgvector →
link the envelope to the entities its extraction created (mentions
edges) → status='indexed'. The item is now queryable by FTS, vector,
and entity.

(Full deterministic identity resolution against the 92-deal spine is
M4; this finalize step covers what M1 needs.)

Run:  python -m workers.embed [--once]
"""

from __future__ import annotations

import sys
import time

from workers.lib import queues
from workers.lib.db import connect
from workers.lib.gemini import EMBED_MODEL, FAKE, embed

MAX_READS = 4
VT_SECONDS = 300
IDLE_SLEEP = 2.0
EMBED_BATCH = 32
MAX_EMBED_CHARS = 20_000   # ~2k tokens — cap so one big chunk can't fail the batch


def process(conn, envelope_id: str) -> str:
    env = conn.execute("select * from gb_envelope where id=%s", (envelope_id,)).fetchone()
    if env is None:
        return "missing"
    if env["status"] not in ("extracted",):
        return "noop"

    rows = conn.execute(
        "select id, text from gb_chunk where envelope_id=%s and embedding is null order by seq",
        (envelope_id,),
    ).fetchall()

    n = 0
    for i in range(0, len(rows), EMBED_BATCH):
        batch = [r for r in rows[i:i + EMBED_BATCH] if (r["text"] or "").strip()]
        if not batch:
            continue
        vecs = embed([(r["text"] or "")[:MAX_EMBED_CHARS] for r in batch])
        for r, v in zip(batch, vecs):
            conn.execute(
                "update gb_chunk set embedding=%s::vector, embed_model=%s where id=%s",
                (str(v), "fake" if FAKE else EMBED_MODEL, r["id"]),
            )
            n += 1

    conn.execute("update gb_envelope set status='embedded' where id=%s", (envelope_id,))
    queues.send(conn, queues.Q_RESOLVE, {"envelope_id": envelope_id})
    return f"embedded:{n} → resolve"


def run(once: bool = False) -> None:
    conn = connect()
    print(f"[embed] up · model={'fake' if FAKE else EMBED_MODEL}", flush=True)
    while True:
        msgs = queues.read(conn, queues.Q_EMBED, vt=VT_SECONDS, qty=5)
        if not msgs:
            if once:
                return
            time.sleep(IDLE_SLEEP)
            continue
        for m in msgs:
            eid = m["message"].get("envelope_id")
            try:
                outcome = process(conn, eid)
                queues.archive(conn, queues.Q_EMBED, m["msg_id"])
                print(f"[embed] {eid} → {outcome}", flush=True)
            except Exception as exc:  # noqa: BLE001
                if m["read_ct"] >= MAX_READS:
                    queues.dead_letter(conn, "embed", eid, m["message"], repr(exc), m["read_ct"])
                    conn.execute("update gb_envelope set status='failed' where id=%s", (eid,))
                    queues.archive(conn, queues.Q_EMBED, m["msg_id"])
                    print(f"[embed] {eid} → DLQ ({exc})", flush=True)
                else:
                    queues.backoff(m["read_ct"])
                    print(f"[embed] {eid} retry {m['read_ct']} ({exc})", flush=True)


if __name__ == "__main__":
    run(once="--once" in sys.argv)
