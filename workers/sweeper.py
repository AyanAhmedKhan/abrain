"""gbrain · sweeper — the self-healing backstop.

If n8n persists a row to gb_raw but the pgmq.send fails (or n8n dies
mid-workflow), the message would be lost. This cron finds gb_raw rows
older than GRACE_MINUTES that never produced an envelope and re-enqueues
them. Dedup guarantees re-enqueueing is always safe.

Run from cron / n8n Schedule every 5 minutes:
    python -m workers.sweeper
"""

from __future__ import annotations

import os

from workers.lib import queues
from workers.lib.db import connect

GRACE_MINUTES = int(os.environ.get("SWEEPER_GRACE_MINUTES", "5"))
# envelopes stranded in a non-terminal status (transient LLM/network error lost the
# next queue message) are re-enqueued after this many minutes. Re-enqueue is a no-op
# if the worker already advanced (each worker re-checks status), so a generous window
# never disrupts in-flight work.
STUCK_GRACE_MINUTES = int(os.environ.get("STUCK_GRACE_MINUTES", "20"))

# status → the queue that owns its *next* transition
NEXT_QUEUE = {
    "normalized": queues.Q_PREPROCESS,
    "preprocessed": queues.Q_EXTRACT,
    "extracted": queues.Q_EMBED,
    "embedded": queues.Q_RESOLVE,
}


def run() -> None:
    conn = connect()
    # 1. orphaned gb_raw (never produced an envelope) → normalize
    rows = conn.execute(
        """
        select r.id
        from gb_raw r
        left join gb_envelope e on e.raw_id = r.id
        where e.id is null
          and r.received_at < now() - make_interval(mins => %s)
        limit 500
        """,
        (GRACE_MINUTES,),
    ).fetchall()
    for row in rows:
        queues.send(conn, queues.Q_NORMALIZE, {"raw_id": str(row["id"])})

    # 2. envelopes stuck in a non-terminal status → re-enqueue to their next queue
    stuck = conn.execute(
        """
        select id, status
        from gb_envelope
        where status in ('normalized','preprocessed','extracted','embedded')
          and ingested_at < now() - make_interval(mins => %s)
        limit 500
        """,
        (STUCK_GRACE_MINUTES,),
    ).fetchall()
    for row in stuck:
        q = NEXT_QUEUE.get(row["status"])
        if q:
            queues.send(conn, q, {"envelope_id": str(row["id"])})

    print(f"[sweeper] re-enqueued {len(rows)} orphaned raw + {len(stuck)} stuck envelopes",
          flush=True)


if __name__ == "__main__":
    run()
