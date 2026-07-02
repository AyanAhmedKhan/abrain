"""gbrain · normalize worker (build spec §5, stages 1–2).

Loop: read gb_q_normalize → load gb_raw → map to canonical envelope →
dedup (idempotency_key) → signal gate → enqueue gb_q_preprocess or skip.

Run:  python -m workers.normalize          (continuous loop)
      python -m workers.normalize --once   (drain once, then exit — used by tests)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from workers.lib import queues
from workers.lib.db import connect
from workers.lib.signal_score import THRESHOLD, ScoreInput, signal_score

MAX_READS = 5          # reads before a poisoned message goes to the DLQ
VT_SECONDS = 60
IDLE_SLEEP = 2.0

DOC_TYPES = {"document", "image", "video", "audio", "voice"}


# ── helpers ──────────────────────────────────────────────────

def sha256(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_QUOTE_LINE = re.compile(r"^\s*(>|On .{0,80} wrote:).*", re.MULTILINE)
_SIG_SPLIT = re.compile(r"\n-- ?\n.*$", re.DOTALL)
_WS = re.compile(r"[ \t]{2,}")
# forwarded-mail scaffolding: separators, mail-client header blocks, forwarder promos
_FWD_MARK = re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.MULTILINE | re.IGNORECASE)
_MAIL_HEADER = re.compile(
    r"^\s*(Date Received|Date Sent|From|To|Cc|Bcc|Sent|Date|Subject|Reply-To|"
    r"Importance|Message-ID):.*$",
    re.MULTILINE | re.IGNORECASE)
_CLOUDHQ = re.compile(
    r"^.*(cloudhq|multi[- ]?email[- ]?forward|emails-to-sheets|"
    r"export emails to google sheets|export, backup, and parse|"
    r"labels and documents|you might be also interested|gmail\s*<https?://).*$",
    re.MULTILINE | re.IGNORECASE)
_BLANKS = re.compile(r"\n{3,}")


def clean_body(text: str | None) -> str:
    """Strip quoted replies, signatures, and forwarded-mail scaffolding (header
    blocks, 'Forwarded message' separators, forwarder promos) → cleaner chunks,
    sharper embeddings, fewer billed tokens."""
    if not text:
        return ""
    text = _FWD_MARK.sub("", text)
    text = _CLOUDHQ.sub("", text)
    text = _MAIL_HEADER.sub("", text)
    text = _QUOTE_LINE.sub("", text)
    text = _SIG_SPLIT.sub("", text)
    text = _WS.sub(" ", text)
    text = _BLANKS.sub("\n\n", text)
    return text.strip()


def ts(value: Any) -> datetime | None:
    """Whapi sends unix seconds; APIs send ISO strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── per-source mapping → canonical envelope ──────────────────

@dataclass
class Envelope:
    kind: str
    thread_id: str | None
    occurred_at: datetime | None
    actors: dict
    title: str | None
    body_raw: str
    labels: list[str]
    has_doc_attachment: bool
    content_hash: str


def map_whatsapp(msg: dict) -> Envelope:
    """One gb_raw row per Whapi message (the receiver fans out)."""
    mtype = msg.get("type", "text")
    body = (
        (msg.get("text") or {}).get("body")
        or (msg.get(mtype) or {}).get("caption", "")
        or ""
    )
    has_doc = mtype in DOC_TYPES
    media = msg.get(mtype) or {}
    # content identity: text body, or the media file hash/id for attachments
    content_basis = body or media.get("sha256") or media.get("id") or msg.get("id", "")
    return Envelope(
        kind="message",
        thread_id=msg.get("chat_id"),
        occurred_at=ts(msg.get("timestamp")),
        actors={"from": msg.get("from"), "from_name": msg.get("from_name"),
                "chat": msg.get("chat_id"), "from_me": msg.get("from_me", False)},
        title=msg.get("chat_name"),
        body_raw=body,
        labels=["deal-flow"] if not msg.get("from_me") else ["internal"],
        has_doc_attachment=has_doc,
        content_hash=sha256(content_basis),
    )


def _gmail_header(payload: dict, name: str) -> str | None:
    for h in (payload.get("payload", {}) or {}).get("headers", []) or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return payload.get(name) or payload.get(name.lower())  # n8n-flattened fallback


# Gmail labelIds → our label vocabulary (extend in config later)
GMAIL_LABEL_MAP = {
    "CATEGORY_PROMOTIONS": "newsletter",
    "CATEGORY_UPDATES": "newsletter",
    "CATEGORY_FORUMS": "newsletter",
    "Call Notes": "call-notes",
    "CallNotes": "call-notes",
}


def map_gmail(p: dict) -> Envelope:
    """Gmail API users.messages.get resource (the connector lands it raw)."""
    subject = _gmail_header(p, "Subject")
    frm = _gmail_header(p, "From")
    to = _gmail_header(p, "To")
    cc = _gmail_header(p, "Cc")
    # connector should pre-extract plain text into 'text'; else fall back to snippet
    body = p.get("text") or p.get("body_text") or p.get("snippet", "")
    label_ids = p.get("labelIds", []) or []
    # A connector can assert routing labels directly (e.g. the call-notes
    # workflow tags every row), independent of Gmail's opaque label IDs.
    labels = list(p.get("gbrain_labels", []) or [])
    labels += [GMAIL_LABEL_MAP[l] for l in label_ids if l in GMAIL_LABEL_MAP]
    labels = list(dict.fromkeys(labels))  # dedupe, keep order
    attachments = [
        part for part in (p.get("payload", {}) or {}).get("parts", []) or []
        if part.get("filename")
    ]
    occurred = p.get("internalDate")
    return Envelope(
        kind="email",
        thread_id=p.get("threadId"),
        occurred_at=(datetime.fromtimestamp(int(occurred) / 1000, tz=timezone.utc)
                     if occurred else ts(_gmail_header(p, "Date"))),
        actors={"from": frm, "to": [to] if to else [], "cc": [cc] if cc else []},
        title=subject,
        body_raw=body,
        labels=labels,
        has_doc_attachment=bool(attachments),
        content_hash=sha256(p.get("id", "") + (subject or "") + body[:512]),
    )


def map_calendar(p: dict) -> Envelope:
    """Google Calendar Events resource. Structured — no LLM needed.

    Labels 'external-meeting' when any attendee is outside the Dexter domains —
    the signal gate indexes only external meetings (founder/investor calls) or
    events with explicit deal language; internal standups/reminders never reach
    the LLM (the first 30-day sync flooded extract: 959/1015 passed the gate)."""
    from workers.lib.taxonomy import DEXTER_DOMAINS
    start = (p.get("start") or {}).get("dateTime") or (p.get("start") or {}).get("date")
    attendees = p.get("attendees", []) or []
    emails = [a.get("email") for a in attendees if a.get("email")]
    labels = ["calendar"]
    internal_suffixes = tuple("@" + d for d in DEXTER_DOMAINS) + ("@resource.calendar.google.com",)
    if any(not e.lower().endswith(internal_suffixes) for e in emails):
        labels.append("external-meeting")
    # strip Google Meet boilerplate blocks so they can't masquerade as content
    desc = re.sub(r"-::~[\s\S]*?~::-", "", p.get("description", "") or "").strip()
    return Envelope(
        kind="event",
        thread_id=p.get("recurringEventId") or p.get("id"),
        occurred_at=ts(start),
        actors={
            "organizer": (p.get("organizer") or {}).get("email"),
            "participants": emails,
        },
        title=p.get("summary"),
        body_raw=desc,
        labels=labels,
        has_doc_attachment=bool(p.get("attachments")),
        content_hash=sha256((p.get("id", "")) + (p.get("updated", "") or start or "")),
    )


# Google-native MIME types we export to text rather than treating as binary
_GOOGLE_DOC_MIME = {
    "application/vnd.google-apps.document": "gdoc",
    "application/vnd.google-apps.presentation": "gslides",
    "application/vnd.google-apps.spreadsheet": "gsheet",
}


def map_drive(p: dict) -> Envelope:
    """Google Drive file / changes resource."""
    mime = p.get("mimeType", "")
    file_type = _GOOGLE_DOC_MIME.get(mime)
    is_binary = file_type is None  # pdf/pptx/xlsx/docx → real attachment
    body = p.get("text") or p.get("exportedText", "") or ""
    owners = [o.get("emailAddress") for o in (p.get("owners", []) or []) if o.get("emailAddress")]
    return Envelope(
        kind="document" if not is_binary else "file",
        thread_id=p.get("driveId"),
        occurred_at=ts(p.get("modifiedTime")),
        actors={"owners": owners},
        title=p.get("name"),
        body_raw=body,
        labels=["drive"],
        has_doc_attachment=is_binary,
        # content identity = revision if present (skip re-extract on rename/perm change)
        content_hash=sha256(p.get("id", "") + (p.get("headRevisionId")
                                              or p.get("md5Checksum")
                                              or p.get("modifiedTime", ""))),
    )


def map_pdf(p: dict) -> Envelope:
    """A standalone PDF (uploaded or routed). Text filled in preprocess."""
    body = p.get("text", "") or ""
    return Envelope(
        kind="file",
        thread_id=None,
        occurred_at=ts(p.get("doc_date")),
        actors={},
        title=p.get("filename") or p.get("title"),
        body_raw=body,
        labels=["pdf"],
        has_doc_attachment=True,
        content_hash=sha256(p.get("hash") or p.get("filename", "") or json.dumps(p, sort_keys=True)),
    )


def map_dashboard(p: dict) -> Envelope:
    """Internal deal/pipeline record via CDC. Structured spine — no LLM."""
    record = p.get("record", p)
    name = record.get("company") or record.get("name") or record.get("deal_name")
    return Envelope(
        kind="record",
        thread_id=record.get("deal_id") or record.get("id"),
        occurred_at=ts(record.get("updated_at") or record.get("created_at")),
        actors={"owner": record.get("deal_owner")},
        title=name,
        body_raw=json.dumps(record, sort_keys=True),
        labels=["dashboard", "internal"],
        has_doc_attachment=False,
        content_hash=sha256(json.dumps(record, sort_keys=True)),
    )


def map_generic(raw: dict) -> Envelope:
    """Fallback for unknown sources and test fixtures."""
    p = raw["payload"]
    body = p.get("body") or p.get("text") or json.dumps(p, sort_keys=True)
    return Envelope(
        kind=p.get("kind", "record"),
        thread_id=p.get("thread_id"),
        occurred_at=ts(p.get("occurred_at")),
        actors=p.get("actors", {}),
        title=p.get("title"),
        body_raw=body,
        labels=p.get("labels", []),
        has_doc_attachment=bool(p.get("attachments")),
        content_hash=sha256(body),
    )


SOURCE_MAPPERS = {
    "whatsapp": lambda raw: map_whatsapp(raw["payload"]),
    "gmail": lambda raw: map_gmail(raw["payload"]),
    "calendar": lambda raw: map_calendar(raw["payload"]),
    "drive_doc": lambda raw: map_drive(raw["payload"]),
    "pdf": lambda raw: map_pdf(raw["payload"]),
    "dashboard": lambda raw: map_dashboard(raw["payload"]),
}


def map_raw(raw: dict) -> Envelope:
    mapper = SOURCE_MAPPERS.get(raw["source"])
    return mapper(raw) if mapper else map_generic(raw)


# ── stage 1+2: normalize one raw row ─────────────────────────

def process_raw(conn, raw_id: str) -> str:
    raw = conn.execute("select * from gb_raw where id = %s", (raw_id,)).fetchone()
    if raw is None:
        return "missing"

    # idempotency: if this raw row already produced an envelope past
    # 'raw', a redelivered message is a no-op.
    existing = conn.execute(
        "select id, status from gb_envelope where raw_id = %s", (raw_id,)
    ).fetchone()
    if existing and existing["status"] != "raw":
        return "noop"

    env = map_raw(raw)
    body_clean = clean_body(env.body_raw)
    idem_key = sha256(raw["source"], raw["source_id"], env.content_hash)

    inserted = conn.execute(
        """
        insert into gb_envelope
          (raw_id, idempotency_key, source, source_id, kind, thread_id,
           occurred_at, actors, title, body_raw, body_clean, labels,
           provenance, status)
        values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb,'normalized')
        on conflict (idempotency_key) do nothing
        returning id
        """,
        (
            raw_id, idem_key, raw["source"], raw["source_id"], env.kind,
            env.thread_id, env.occurred_at, json.dumps(env.actors), env.title,
            env.body_raw, body_clean, env.labels,
            json.dumps({"content_hash": env.content_hash, "raw_ref": raw.get("storage_ref")}),
        ),
    ).fetchone()

    if inserted is None:
        return "duplicate"  # cross-channel dup — spend killed, stop here

    envelope_id = inserted["id"]

    # ── Gmail: rule-based classifier is authoritative ────────
    if raw["source"] == "gmail":
        from workers.lib.gmail_filter import classify_gmail
        # cheap spine cache for mention-based allow (refreshed elsewhere)
        spine = {r["canonical"].lower() for r in conn.execute(
            "select canonical from gb_entity where type in ('company','deal') "
            "and length(canonical) >= 4 limit 2000").fetchall()}
        decision = classify_gmail(raw["payload"], body_clean,
                                  has_pdf=env.has_doc_attachment, spine_terms=spine)
        if decision.action == "skip":
            if decision.reason.startswith("confidential"):
                # never retain sensitive content: clear the searchable body
                conn.execute(
                    "update gb_envelope set body_raw=null, body_clean=null, "
                    "signal_score=0, status='skipped', skip_reason=%s where id=%s",
                    (decision.reason, envelope_id))
            else:
                conn.execute(
                    "update gb_envelope set signal_score=0, status='skipped', "
                    "skip_reason=%s where id=%s", (decision.reason, envelope_id))
            return f"skipped:{decision.reason}"
        conn.execute(
            "update gb_envelope set labels=%s, signal_score=0.95 where id=%s",
            (decision.labels, envelope_id))
        queues.send(conn, queues.Q_PREPROCESS, {"envelope_id": str(envelope_id)})
        return f"queued:{decision.reason}"

    # GATE — sender_is_known: cheap deterministic lookup against entity keys
    sender = (env.actors or {}).get("from") or ""
    known = conn.execute(
        "select 1 from gb_entity where keys->>'phone' = %s or keys->>'email' = %s limit 1",
        (sender, sender),
    ).fetchone() is not None

    score = signal_score(ScoreInput(
        source=raw["source"], title=env.title, body_clean=body_clean,
        labels=env.labels, sender_is_known=known,
        has_doc_attachment=env.has_doc_attachment,
    ))

    if score < THRESHOLD:
        conn.execute(
            "update gb_envelope set signal_score=%s, status='skipped', "
            "skip_reason='low_signal' where id=%s",
            (score, envelope_id),
        )
        return "skipped"

    conn.execute(
        "update gb_envelope set signal_score=%s where id=%s", (score, envelope_id)
    )
    queues.send(conn, queues.Q_PREPROCESS, {"envelope_id": str(envelope_id)})
    return "queued"


# ── worker loop ──────────────────────────────────────────────

def run(once: bool = False) -> None:
    conn = connect()
    print(f"[normalize] up · threshold={THRESHOLD}", flush=True)
    while True:
        msgs = queues.read(conn, queues.Q_NORMALIZE, vt=VT_SECONDS, qty=10)
        if not msgs:
            if once:
                return
            time.sleep(IDLE_SLEEP)
            continue
        for m in msgs:
            raw_id = m["message"].get("raw_id")
            try:
                outcome = process_raw(conn, raw_id)
                queues.archive(conn, queues.Q_NORMALIZE, m["msg_id"])
                print(f"[normalize] {raw_id} → {outcome}", flush=True)
            except Exception as exc:  # noqa: BLE001
                if m["read_ct"] >= MAX_READS:
                    queues.dead_letter(conn, "normalize", None, m["message"],
                                       repr(exc), m["read_ct"])
                    queues.archive(conn, queues.Q_NORMALIZE, m["msg_id"])
                    print(f"[normalize] {raw_id} → DLQ ({exc})", flush=True)
                else:
                    queues.backoff(m["read_ct"])
                    print(f"[normalize] {raw_id} retry {m['read_ct']} ({exc})",
                          flush=True)
                # not archived → visibility timeout redelivers


if __name__ == "__main__":
    run(once="--once" in sys.argv)
