"""gbrain · preprocess worker (Stage 3 — local, free).

Reads gb_q_preprocess. For each envelope:
  - if it references a PDF in bronze: download, extract the text layer
    (PyMuPDF), record gb_attachment (hash-deduped — same deck via two
    channels extracts ONCE), chunk page-aware.
  - else (plain email/message): chunk body_clean.
Then status='preprocessed' and enqueue gb_q_extract.

Scanned PDFs (no text layer) are dead-lettered with a clear reason —
OCR is a deliberate later add, not silent garbage extraction.

Run:  python -m workers.preprocess [--once]
"""

from __future__ import annotations

import json
import sys
import time

from workers.lib import queues, storage
from workers.lib.db import connect

MAX_READS = 5
VT_SECONDS = 120
IDLE_SLEEP = 2.0
CHUNK_CHARS = 1800           # ~450 tokens; page-aware first, size second
MIN_TEXT_PER_PAGE = 25       # below this avg, treat as scanned


def chunk_text(text: str, page: int | None) -> list[tuple[int | None, str]]:
    out, buf = [], ""
    for para in text.split("\n\n"):
        # hard-split a single oversized paragraph (no blank lines) so no chunk
        # can exceed the embed model's input limit downstream
        while len(para) > CHUNK_CHARS:
            if buf:
                out.append((page, buf.strip())); buf = ""
            out.append((page, para[:CHUNK_CHARS].strip()))
            para = para[CHUNK_CHARS:]
        if len(buf) + len(para) > CHUNK_CHARS and buf:
            out.append((page, buf.strip()))
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        out.append((page, buf.strip()))
    return out


def extract_pdf(data: bytes) -> tuple[list[tuple[int, str]], int, bool]:
    """→ ([(page, text)], n_pages, has_text_layer)"""
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = [(i + 1, doc[i].get_text("text") or "") for i in range(doc.page_count)]
    n = doc.page_count
    doc.close()
    total = sum(len(t) for _, t in pages)
    return pages, n, (total / max(n, 1)) >= MIN_TEXT_PER_PAGE


def process(conn, envelope_id: str) -> str:
    env = conn.execute("select * from gb_envelope where id=%s", (envelope_id,)).fetchone()
    if env is None:
        return "missing"
    if env["status"] not in ("normalized",):
        return "noop"  # idempotency: redelivery after completion

    raw = conn.execute("select * from gb_raw where id=%s", (env["raw_id"],)).fetchone()
    payload = (raw or {}).get("payload") or {}
    chunks: list[tuple[int | None, str]] = []

    storage_ref = payload.get("storage_ref")
    file_hash = payload.get("hash")

    if storage_ref and file_hash:
        # ── attachment path ──────────────────────────────────────
        existing = conn.execute(
            "select id from gb_attachment where hash=%s", (file_hash,)
        ).fetchone()
        if existing:
            # same deck via another channel → inherit the original's note,
            # skip re-extraction entirely ($0), finalize directly.
            orig = conn.execute(
                "select extraction from gb_envelope where id = "
                "(select envelope_id from gb_attachment where id=%s)",
                (existing["id"],),
            ).fetchone()
            conn.execute(
                "update gb_envelope set status='extracted', "
                "extraction = coalesce(%s::jsonb, extraction), "
                "skip_reason='dedup_inherited' where id=%s and status='normalized'",
                (json.dumps(orig["extraction"]) if orig and orig["extraction"] else None,
                 envelope_id),
            )
            queues.send(conn, queues.Q_EMBED, {"envelope_id": envelope_id})
            return "dedup-linked"

        data = storage.download(storage_ref)
        pages, n_pages, has_text = extract_pdf(data)
        if not has_text:
            # image/scanned PDF — no local text layer. Register the attachment
            # and hand off to extract, which reads the PDF directly via Gemini
            # multimodal (no OCR step needed).
            conn.execute(
                "insert into gb_attachment (envelope_id, hash, mime, storage_ref, text_layer, pages) "
                "values (%s,%s,%s,%s,false,%s) on conflict (hash) do update "
                "set text_layer=excluded.text_layer, pages=excluded.pages",
                (envelope_id, file_hash, payload.get("mime", "application/pdf"),
                 storage_ref, n_pages))
            conn.execute("update gb_envelope set status='preprocessed' where id=%s", (envelope_id,))
            queues.send(conn, queues.Q_EXTRACT, {"envelope_id": envelope_id})
            return f"multimodal-pending:{n_pages}p"

        att = conn.execute(
            "insert into gb_attachment (envelope_id, hash, mime, storage_ref, text_layer, pages) "
            "values (%s,%s,%s,%s,true,%s) on conflict (hash) do update set pages=excluded.pages "
            "returning id",
            (envelope_id, file_hash, payload.get("mime", "application/pdf"),
             storage_ref, n_pages),
        ).fetchone()
        for page, text in pages:
            if text.strip():
                chunks += [(p, t) for p, t in chunk_text(text, page)]
        att_id = att["id"]
    else:
        # ── plain text path (email body, message) ────────────────
        body = env.get("body_clean") or env.get("body_raw") or ""
        if not body.strip():
            conn.execute(
                "update gb_envelope set status='skipped', skip_reason='empty_body' "
                "where id=%s", (envelope_id,),
            )
            return "empty"
        chunks = chunk_text(body, None)
        att_id = None

    conn.execute("delete from gb_chunk where envelope_id=%s and attachment_id is not distinct from %s",
                 (envelope_id, att_id))
    for seq, (page, text) in enumerate(chunks):
        conn.execute(
            "insert into gb_chunk (envelope_id, attachment_id, seq, page, text, token_est) "
            "values (%s,%s,%s,%s,%s,%s)",
            (envelope_id, att_id, seq, page, text, len(text) // 4),
        )

    conn.execute("update gb_envelope set status='preprocessed' where id=%s", (envelope_id,))
    queues.send(conn, queues.Q_EXTRACT, {"envelope_id": envelope_id})
    return f"chunked:{len(chunks)}"


def run(once: bool = False) -> None:
    conn = connect()
    print("[preprocess] up", flush=True)
    while True:
        msgs = queues.read(conn, queues.Q_PREPROCESS, vt=VT_SECONDS, qty=5)
        if not msgs:
            if once:
                return
            time.sleep(IDLE_SLEEP)
            continue
        for m in msgs:
            eid = m["message"].get("envelope_id")
            try:
                outcome = process(conn, eid)
                queues.archive(conn, queues.Q_PREPROCESS, m["msg_id"])
                print(f"[preprocess] {eid} → {outcome}", flush=True)
            except Exception as exc:  # noqa: BLE001
                if m["read_ct"] >= MAX_READS:
                    queues.dead_letter(conn, "preprocess", eid, m["message"],
                                       repr(exc), m["read_ct"])
                    conn.execute("update gb_envelope set status='failed' where id=%s", (eid,))
                    queues.archive(conn, queues.Q_PREPROCESS, m["msg_id"])
                    print(f"[preprocess] {eid} → DLQ ({exc})", flush=True)
                else:
                    queues.backoff(m["read_ct"])
                    print(f"[preprocess] {eid} retry {m['read_ct']} ({exc})", flush=True)


if __name__ == "__main__":
    run(once="--once" in sys.argv)
