"""gbrain · thin pgmq wrappers.

The queue tells a worker "there's work for you"; gb_envelope.status is
the durable truth. Workers must stay idempotent: re-check status before
acting, so a redelivered message is a no-op, never a double-spend.
"""

from __future__ import annotations

import json
import time
from typing import Any

import psycopg


def backoff(read_ct: int, base: float = 2.0, cap: float = 30.0) -> None:
    """Exponential sleep before a transient retry so a brief LLM/network outage
    doesn't burn all MAX_READS in seconds: ~2s, 4s, 8s… capped."""
    time.sleep(min(base * (2 ** max(0, read_ct - 1)), cap))

Q_NORMALIZE = "gb_q_normalize"
Q_PREPROCESS = "gb_q_preprocess"
Q_EXTRACT = "gb_q_extract"
Q_EMBED = "gb_q_embed"
Q_RESOLVE = "gb_q_resolve"
Q_INDEX = "gb_q_index"
Q_BACKFILL = "gb_q_backfill"
Q_ENRICH = "gb_q_enrich"
Q_PROFILE = "gb_q_profile"
Q_COMPANY = "gb_q_company"


def send(conn: psycopg.Connection, queue: str, payload: dict[str, Any]) -> int:
    row = conn.execute(
        "select pgmq.send(%s, %s::jsonb) as msg_id",
        (queue, json.dumps(payload)),
    ).fetchone()
    return row["msg_id"]


def read(conn: psycopg.Connection, queue: str, vt: int = 60, qty: int = 1) -> list[dict]:
    """Returns rows with msg_id, read_ct, enqueued_at, vt, message(dict)."""
    rows = conn.execute(
        "select msg_id, read_ct, enqueued_at, message "
        "from pgmq.read(%s, %s, %s)",
        (queue, vt, qty),
    ).fetchall()
    for r in rows:
        if isinstance(r["message"], str):
            r["message"] = json.loads(r["message"])
    return rows


def archive(conn: psycopg.Connection, queue: str, msg_id: int) -> None:
    conn.execute("select pgmq.archive(%s, %s::bigint)", (queue, msg_id))


def dead_letter(
    conn: psycopg.Connection,
    stage: str,
    envelope_id: str | None,
    payload: dict[str, Any] | None,
    error: str,
    retries: int,
) -> None:
    conn.execute(
        "insert into gb_dlq (stage, envelope_id, payload, error, retries) "
        "values (%s, %s, %s::jsonb, %s, %s)",
        (stage, envelope_id, json.dumps(payload or {}), error[:4000], retries),
    )
