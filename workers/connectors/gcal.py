"""gbrain · standalone Google Calendar connector (M3).

Polls each connected account's primary calendar and lands raw rows for the
pipeline. It stays DUMB (build spec §6): fetch + INSERT only — no parsing, no
LLM, no classification. The 005 trigger enqueues gb_q_normalize on insert;
normalize's map_calendar (kind='event') + the signal gate decide downstream,
and resolve turns indexed events into meeting entities + attended edges.

Sync model — Calendar's incremental syncToken:
  first poll   events.list(timeMin=now-CAL_INITIAL_DAYS, singleEvents=True)
               → pages → nextSyncToken saved in gb_sync_cursor 'calendar:<email>'
  later polls  events.list(syncToken=…) → only changed events
  HTTP 410     token expired → drop it and full-resync (one-time)

Versioned landing: source_id = '<event id>@<updated>' so an edited event lands
again as a new row (envelope idempotency_key dedups identical replays).
Cancelled occurrences are skipped (no content to index).

Auth: SAME OAuth tokens as Gmail (GMAIL_TOKEN_DIR, one <email>.json per
mailbox) — the token must carry the calendar.readonly scope; tokens without it
are skipped with a re-mint hint (workers/connectors/gmail_auth.py now mints
gmail+calendar together).

Config (env):
  CAL_INITIAL_DAYS    first-sync lookback (default 30)
  CAL_MAX_RESULTS     max events per page (default 250)
  CAL_POLL_SECONDS    loop sleep between polls (default 300)

Run:  python -m workers.connectors.gcal --once   (one poll, used by the timer)
      python -m workers.connectors.gcal          (continuous loop)
"""

from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import os
import sys
import time

from workers.lib.db import connect

CAL_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


# ── auth (reuse the Gmail token dir) ─────────────────────────

def _build(creds):
    from googleapiclient.discovery import build  # deferred import
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _token_paths() -> list[str]:
    paths: list[str] = []
    token_dir = os.environ.get("GMAIL_TOKEN_DIR", "/opt/gbrain/tokens")
    if token_dir and os.path.isdir(token_dir):
        paths += sorted(glob.glob(os.path.join(token_dir, "*.json")))
    token_file = os.environ.get("GMAIL_TOKEN_FILE")
    if token_file and os.path.exists(token_file):
        paths.append(token_file)
    return list(dict.fromkeys(paths))


def accounts() -> list[tuple[str, object]]:
    """[(cursor_key, calendar_service)] for every token that has the calendar
    scope. Tokens without it are skipped loudly (re-mint via gmail_auth)."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    out: list[tuple[str, object]] = []
    for p in _token_paths():
        try:
            raw = json.load(open(p))
            email = os.path.basename(p).rsplit(".json", 1)[0]
            if CAL_SCOPE not in (raw.get("scopes") or []):
                print(f"[gcal] SKIP {email}: token lacks calendar scope — "
                      f"re-run gmail_auth to re-consent (adds gmail+calendar)", flush=True)
                continue
            creds = Credentials.from_authorized_user_file(p)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                try:
                    with open(p, "w") as fh:
                        fh.write(creds.to_json())
                    os.chmod(p, 0o600)
                except OSError as e:
                    print(f"[gcal] warn: could not persist refreshed token {p}: {e}", flush=True)
            out.append((f"calendar:{email}", _build(creds)))
        except Exception as e:  # one bad token must not blind the others
            print(f"[gcal] SKIP token {os.path.basename(p)}: {type(e).__name__}: {e!r}", flush=True)
    return out


# ── cursor (per account) ─────────────────────────────────────

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


# ── one poll ─────────────────────────────────────────────────

def _list_events(svc, page_token=None, sync_token=None, max_results=250):
    params = {"calendarId": "primary", "maxResults": max_results,
              "singleEvents": True, "pageToken": page_token}
    if sync_token:
        params["syncToken"] = sync_token
    else:
        days = int(os.environ.get("CAL_INITIAL_DAYS", "30"))
        t0 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        params["timeMin"] = t0.isoformat()
    return svc.events().list(**{k: v for k, v in params.items() if v is not None}).execute()


def poll_once(conn, svc, cursor_key: str) -> tuple[int, int]:
    from googleapiclient.errors import HttpError

    lock_id = int(hashlib.sha1(cursor_key.encode()).hexdigest()[:15], 16)
    if not conn.execute("select pg_try_advisory_lock(%s) ok", (lock_id,)).fetchone()["ok"]:
        print(f"[gcal] {cursor_key}: previous poll still running, skipping", flush=True)
        return 0, 0
    try:
        cursor = _get_cursor(conn, cursor_key)
        sync_token = cursor.get("syncToken")
        max_results = int(os.environ.get("CAL_MAX_RESULTS", "250"))

        landed = seen = 0
        page_token = None
        while True:
            try:
                resp = _list_events(svc, page_token, sync_token, max_results)
            except HttpError as e:
                if e.resp.status == 410 and sync_token:   # token expired → full resync
                    print(f"[gcal] {cursor_key}: syncToken expired, full resync", flush=True)
                    sync_token = None
                    page_token = None
                    continue
                raise
            for ev in resp.get("items", []) or []:
                seen += 1
                if ev.get("status") == "cancelled":       # deletion delta — nothing to index
                    continue
                sid = f"{ev.get('id')}@{ev.get('updated', '')}"
                ins = conn.execute(
                    "insert into gb_raw (source, source_id, payload, content_hash) "
                    "values ('calendar', %s, %s::jsonb, %s) "
                    "on conflict (source, source_id) do nothing returning id",
                    (sid, json.dumps(ev),
                     hashlib.sha256((ev.get("id", "") + ev.get("updated", "")).encode()).hexdigest()),
                ).fetchone()
                if ins:
                    landed += 1
            page_token = resp.get("nextPageToken")
            if not page_token:
                new_token = resp.get("nextSyncToken")
                if new_token:
                    _set_cursor(conn, cursor_key, {"syncToken": new_token})
                break
        return landed, seen
    finally:
        conn.execute("select pg_advisory_unlock(%s)", (lock_id,))


# ── loop ─────────────────────────────────────────────────────

def run(once: bool = False) -> None:
    conn = connect()
    accts = accounts()
    if not accts:
        print("[gcal] no calendar-scoped tokens — re-run gmail_auth to add the scope", flush=True)
        if once:
            return
    else:
        print(f"[gcal] up · {len(accts)} account(s): "
              f"{', '.join(k.split(':', 1)[-1] for k, _ in accts)}", flush=True)
    while True:
        for key, svc in accts:
            acct = key.split(":", 1)[-1]
            try:
                landed, seen = poll_once(conn, svc, key)
                print(f"[gcal] {acct}: saw {seen} change(s) · landed {landed}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[gcal] {acct}: poll error: {exc!r}", flush=True)
                if getattr(conn, "closed", 0):
                    try:
                        conn = connect()
                        print("[gcal] reconnected to DB", flush=True)
                    except Exception as e2:
                        print(f"[gcal] reconnect failed: {e2!r}", flush=True)
        if once:
            return
        time.sleep(int(os.environ.get("CAL_POLL_SECONDS", "300")))


if __name__ == "__main__":
    run(once="--once" in sys.argv)
