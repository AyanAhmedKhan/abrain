"""gbrain · standalone Gmail connector (no n8n).

Polls a Google Workspace mailbox and lands raw rows for the pipeline.
It stays DUMB (build spec §6): fetch + upload + INSERT only — no parsing,
no LLM, no classification. The 005 trigger enqueues gb_q_normalize on
insert; the rule-based classifier (workers/lib/gmail_filter.py) decides
index-vs-skip downstream, in normalize.

Per message it lands:
  • one  source='gmail'  row  — the full Gmail message resource (+ decoded
    plain-text body in payload["text"]); runs through the classifier.
  • one  source='pdf'    row per PDF attachment — uploaded to bronze first,
    payload carries {hash, storage_ref, mime, …}; takes preprocess's
    attachment path and dedups on the file hash (same deck via two
    channels = extracted once).

Idempotent: gb_raw has unique(source, source_id) (gmail→message id,
pdf→sha256), so re-seen items are no-ops. A sync cursor (gb_sync_cursor)
narrows each poll with Gmail `after:`; already-landed messages are
skipped before the (costly) full fetch.

Auth — OAuth tokens (multi-mailbox) preferred; service account otherwise:
  GMAIL_TOKEN_DIR=/opt/gbrain/tokens   one OAuth token .json per mailbox
  GMAIL_TOKEN_FILE=/opt/gbrain/token.json   a single OAuth token (also OK)
      User-consent tokens minted by workers/connectors/gmail_auth.py — no
      Workspace admin needed; each mailbox is polled with its own cursor
      ('gmail:<email>').
  GMAIL_SERVICE_ACCOUNT_FILE=/opt/gbrain/sa.json + GMAIL_IMPERSONATE=<mailbox>
      service account + domain-wide delegation (single mailbox; needs a
      Workspace admin to authorize the client id for gmail.readonly).

Config (env):
  GMAIL_QUERY          extra Gmail search (default excludes spam/promotions)
  GMAIL_INITIAL_DAYS   first-run lookback when no cursor exists (default 7)
  GMAIL_MAX_RESULTS    max messages fetched per poll (default 50)
  GMAIL_POLL_SECONDS   loop sleep between polls (default 60)

Run:  python -m workers.connectors.gmail --once   (one poll, used by the timer)
      python -m workers.connectors.gmail          (continuous loop)
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import re
import sys
import time

from workers.lib import storage
from workers.lib.db import connect

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_QUERY = "-in:spam -in:trash -category:promotions -category:social"


# ── auth (one or many mailboxes) ─────────────────────────────

def _build(creds):
    from googleapiclient.discovery import build  # deferred import
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _token_paths() -> list[str]:
    """OAuth token files: a directory of per-mailbox tokens and/or a single file."""
    paths: list[str] = []
    token_dir = os.environ.get("GMAIL_TOKEN_DIR")
    if token_dir and os.path.isdir(token_dir):
        paths += sorted(glob.glob(os.path.join(token_dir, "*.json")))
    token_file = os.environ.get("GMAIL_TOKEN_FILE")
    if token_file and os.path.exists(token_file):
        paths.append(token_file)
    return list(dict.fromkeys(paths))  # dedupe, keep order


def accounts() -> list[tuple[str, object]]:
    """Resolve every configured mailbox → [(cursor_key, gmail_service)].

    OAuth tokens (one per mailbox, multi-mailbox friendly) take precedence;
    otherwise a single service account + GMAIL_IMPERSONATE. cursor_key is
    'gmail:<email>' so each mailbox tracks its own sync position.
    """
    out: list[tuple[str, object]] = []
    tokens = _token_paths()
    if tokens:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        for p in tokens:
            try:
                creds = Credentials.from_authorized_user_file(p, SCOPES)
                # refresh now (detects revoked tokens early) and persist the new
                # access token back to disk — else it's lost on restart
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    try:
                        with open(p, "w") as fh:
                            fh.write(creds.to_json())
                        os.chmod(p, 0o600)
                    except OSError as e:
                        print(f"[gmail] warn: could not persist refreshed token {p}: {e}", flush=True)
                svc = _build(creds)
                email = svc.users().getProfile(userId="me").execute().get("emailAddress", p)
                out.append((f"gmail:{email}", svc))
            except Exception as e:  # one bad/revoked token must not blind the others
                print(f"[gmail] SKIP token {os.path.basename(p)}: {type(e).__name__}: {e!r}", flush=True)
                continue
        if not out:
            raise RuntimeError("no valid Gmail tokens loaded (all failed/revoked) — re-run gmail_auth")
        return out

    sa = os.environ.get("GMAIL_SERVICE_ACCOUNT_FILE")
    if sa and os.path.exists(sa):
        from google.oauth2 import service_account
        impersonate = os.environ.get("GMAIL_IMPERSONATE")
        if not impersonate:
            raise RuntimeError("GMAIL_IMPERSONATE is required with a service account")
        creds = service_account.Credentials.from_service_account_file(
            sa, scopes=SCOPES).with_subject(impersonate)
        return [(f"gmail:{impersonate}", _build(creds))]

    raise RuntimeError(
        "no Gmail auth: set GMAIL_TOKEN_DIR/GMAIL_TOKEN_FILE (OAuth) or "
        "GMAIL_SERVICE_ACCOUNT_FILE (+GMAIL_IMPERSONATE). See gmail_auth.py")


# ── cursor (per mailbox) ─────────────────────────────────────

def _get_cursor(conn, key: str) -> dict:
    row = conn.execute(
        "select cursor from gb_sync_cursor where source=%s", (key,)).fetchone()
    return (row["cursor"] if row else None) or {}


def _set_cursor(conn, key: str, cursor: dict) -> None:
    conn.execute(
        "insert into gb_sync_cursor (source, cursor, updated_at) "
        "values (%s, %s::jsonb, now()) "
        "on conflict (source) do update set cursor=excluded.cursor, updated_at=now()",
        (key, json.dumps(cursor)))


# ── MIME helpers ─────────────────────────────────────────────

def _b64(data: str | None) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8")) if data else b""


def _walk(payload: dict):
    """Breadth-first over a Gmail message payload's MIME parts."""
    stack = [payload]
    while stack:
        part = stack.pop(0)
        yield part
        for child in part.get("parts", []) or []:
            stack.append(child)


def plain_text(payload: dict) -> str:
    """First text/plain part; fall back to crudely de-tagged text/html."""
    html = None
    for part in _walk(payload):
        mime = part.get("mimeType", "")
        data = (part.get("body", {}) or {}).get("data")
        if mime == "text/plain" and data:
            return _b64(data).decode("utf-8", "replace")
        if mime == "text/html" and data and html is None:
            html = _b64(data).decode("utf-8", "replace")
    if html:
        return re.sub(r"\s{2,}", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return ""


def pdf_parts(payload: dict) -> list[dict]:
    out = []
    for part in _walk(payload):
        fn = part.get("filename") or ""
        mime = part.get("mimeType", "")
        if fn and (mime == "application/pdf" or fn.lower().endswith(".pdf")):
            body = part.get("body", {}) or {}
            out.append({
                "filename": fn,
                "mime": mime or "application/pdf",
                "attachment_id": body.get("attachmentId"),
                "data": body.get("data"),
            })
    return out


# ── one poll ─────────────────────────────────────────────────

def _idate(full) -> int:
    try:
        return int(full.get("internalDate") or 0) // 1000
    except (TypeError, ValueError):
        return 0


def poll_once(conn, svc, cursor_key: str = "gmail") -> tuple[int, int, int]:
    # advisory lock: skip if another run for this mailbox is still in flight
    lock_id = int(hashlib.sha1(cursor_key.encode()).hexdigest()[:15], 16)
    if not conn.execute("select pg_try_advisory_lock(%s) ok", (lock_id,)).fetchone()["ok"]:
        print(f"[gmail] {cursor_key}: previous poll still running, skipping", flush=True)
        return 0, 0, 0
    try:
        cursor = _get_cursor(conn, cursor_key)
        base_q = os.environ.get("GMAIL_QUERY", DEFAULT_QUERY)
        after = cursor.get("after")
        if after:
            query = f"{base_q} after:{int(after)}"
        else:
            days = int(os.environ.get("GMAIL_INITIAL_DAYS", "7"))
            query = f"{base_q} newer_than:{days}d"

        max_results = int(os.environ.get("GMAIL_MAX_RESULTS", "50"))
        ids: list[str] = []
        page_token = None
        capped = False
        while len(ids) < max_results:
            resp = svc.users().messages().list(
                userId="me", q=query, maxResults=max_results, pageToken=page_token
            ).execute()
            ids += [m["id"] for m in resp.get("messages", []) or []]
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
            capped = True  # more pages exist than this poll will take
        if capped:
            print(f"[gmail] {cursor_key}: more than {max_results} messages match — "
                  f"will continue next poll (raise GMAIL_MAX_RESULTS to catch up faster)", flush=True)

        landed_email = landed_pdf = 0
        max_internal = int(after or 0)

        for mid in ids:
            # skip the (re-seen) boundary messages cheaply, before the full fetch
            if conn.execute("select 1 from gb_raw where source='gmail' and source_id=%s",
                            (mid,)).fetchone():
                continue
            try:
                full = svc.users().messages().get(userId="me", id=mid, format="full").execute()

                # attachments FIRST: a message is only marked done (its 'gmail' row
                # landed) once every PDF is safely in bronze, so a storage failure
                # re-polls the whole message instead of orphaning the deck.
                for pdf in pdf_parts(full.get("payload", {}) or {}):
                    data = pdf["data"]
                    if not data and pdf["attachment_id"]:
                        att = svc.users().messages().attachments().get(
                            userId="me", messageId=mid, id=pdf["attachment_id"]).execute()
                        data = att.get("data")
                    if not data:
                        continue
                    blob = _b64(data)
                    h = hashlib.sha256(blob).hexdigest()
                    storage_ref = storage.upload(f"{h}.pdf", blob, "application/pdf")
                    ppayload = {
                        "filename": pdf["filename"], "mime": pdf["mime"], "hash": h,
                        "storage_path": f"{h}.pdf", "storage_ref": storage_ref,
                        "gmail_message_id": mid, "thread_id": full.get("threadId"),
                        "gbrain_labels": ["call-notes"],
                    }
                    ins = conn.execute(
                        "insert into gb_raw (source, source_id, payload, storage_ref, content_hash) "
                        "values ('pdf', %s, %s::jsonb, %s, %s) "
                        "on conflict (source, source_id) do nothing returning id",
                        (h, json.dumps(ppayload), storage_ref, h),
                    ).fetchone()
                    if ins:
                        landed_pdf += 1

                payload = dict(full)
                payload["text"] = plain_text(full.get("payload", {}) or {})
                inserted = conn.execute(
                    "insert into gb_raw (source, source_id, payload, content_hash) "
                    "values ('gmail', %s, %s::jsonb, %s) "
                    "on conflict (source, source_id) do nothing returning id",
                    (mid, json.dumps(payload), full.get("id")),
                ).fetchone()
                if inserted:
                    landed_email += 1

                # advance high-water mark ONLY after the message fully landed
                max_internal = max(max_internal, _idate(full))
            except Exception as exc:  # one bad message must not abort the mailbox
                print(f"[gmail] {cursor_key}: message {mid} error: {exc!r}", flush=True)
                continue

        # advance cursor to the newest fully-landed message (after: is inclusive;
        # the boundary message is skipped next poll by the gb_raw existence check).
        if max_internal and max_internal != int(after or 0):
            _set_cursor(conn, cursor_key, {**cursor, "after": max_internal})

        return landed_email, landed_pdf, len(ids)
    finally:
        conn.execute("select pg_advisory_unlock(%s)", (lock_id,))


# ── loop ─────────────────────────────────────────────────────

def run(once: bool = False) -> None:
    conn = connect()
    accts = accounts()
    print(f"[gmail] up · {len(accts)} mailbox(es): "
          f"{', '.join(k.split(':', 1)[-1] for k, _ in accts)}", flush=True)
    while True:
        for key, svc in accts:
            mbox = key.split(":", 1)[-1]
            try:
                e, p, n = poll_once(conn, svc, key)
                print(f"[gmail] {mbox}: polled {n} · landed {e} email, {p} pdf", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[gmail] {mbox}: poll error: {exc!r}", flush=True)
                if getattr(conn, "closed", 0):   # DB dropped — reconnect for next mailbox/poll
                    try:
                        conn = connect()
                        print("[gmail] reconnected to DB", flush=True)
                    except Exception as e2:
                        print(f"[gmail] reconnect failed: {e2!r}", flush=True)
        if once:
            return
        time.sleep(int(os.environ.get("GMAIL_POLL_SECONDS", "60")))


if __name__ == "__main__":
    run(once="--once" in sys.argv)
