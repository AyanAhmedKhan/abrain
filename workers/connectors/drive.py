"""gbrain · Google Drive pitch-deck connector (public links, no auth).

Paste a Drive **file / Google Slides / Docs / folder** link → download the PDF(s)
→ bronze Storage → INSERT `gb_raw`. A "dumb connector": the 005 trigger then runs
normalize → preprocess → extract → embed → resolve unchanged. Idempotent (content
hash + gb_raw unique(source,source_id)).

Public/anyone-with-link only — no service account / OAuth. Decks (image or text)
are handled downstream by the multimodal extractor.

    python -m workers.connectors.drive <link> [<link> ...]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys

import httpx

from workers.lib import storage
from workers.lib.db import connect

_UA = {"User-Agent": "Mozilla/5.0 (gbrain deck ingest)"}
_ID = r"[A-Za-z0-9_-]{20,}"


def _parse(url: str):
    """Drive URL → (kind, id). kind ∈ slides|docs|sheet|file|folder, or (None,None)."""
    u = (url or "").strip()
    for pat, kind in (
        (r"/presentation/d/(" + _ID + ")", "slides"),
        (r"/document/d/(" + _ID + ")", "docs"),
        (r"/spreadsheets/d/(" + _ID + ")", "sheet"),
        (r"/file/d/(" + _ID + ")", "file"),
        (r"/(?:drive/)?folders/(" + _ID + ")", "folder"),
        (r"[?&]id=(" + _ID + ")", "file"),
    ):
        m = re.search(pat, u)
        if m:
            return kind, m.group(1)
    return None, None


def _export_url(kind: str, fid: str) -> str | None:
    return {
        "slides": f"https://docs.google.com/presentation/d/{fid}/export/pdf",
        "docs": f"https://docs.google.com/document/d/{fid}/export?format=pdf",
        "file": f"https://drive.google.com/uc?export=download&id={fid}",
    }.get(kind)


def _download(client: httpx.Client, kind: str, fid: str) -> tuple[bytes, str]:
    """Download bytes + best-effort filename. Handles the large-file confirm page."""
    r = client.get(_export_url(kind, fid), headers=_UA)
    if kind == "file" and "text/html" in r.headers.get("content-type", ""):
        m = re.search(r"confirm=([0-9A-Za-z_-]+)", r.text)
        r = client.get("https://drive.usercontent.google.com/download",
                       params={"id": fid, "export": "download", "confirm": m.group(1) if m else "t"},
                       headers=_UA)
    r.raise_for_status()
    cd = r.headers.get("content-disposition", "")
    fn = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    name = (fn.group(1) if fn else f"{kind}-{fid}").strip()
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return r.content, name


def _list_folder(client: httpx.Client, fid: str) -> list[str]:
    """Best-effort: scrape a PUBLIC folder page for file IDs (25–50 chars)."""
    r = client.get(f"https://drive.google.com/drive/folders/{fid}", headers=_UA)
    ids = {m for m in re.findall(r'"([A-Za-z0-9_-]{25,50})"', r.text)}
    ids.discard(fid)
    return sorted(ids)


def _store(conn, data: bytes, name: str, *, origin: str,
           source_url: str | None = None, drive_id: str | None = None) -> tuple[str, dict]:
    """Validate one PDF → bronze Storage → INSERT gb_raw (dumb connector; the 005
    trigger drives the rest). `origin` ∈ drive|computer|email tags provenance so the
    UI/Obsidian can say where the deck came from. Idempotent via content hash.
    Returns ('queued', {name,id}) or ('skipped', {url,reason})."""
    if not data or data[:5] != b"%PDF-":
        return "skipped", {"url": name, "reason": "not a valid PDF (private, corrupt, or non-PDF)"}
    h = hashlib.sha256(data).hexdigest()
    ref = storage.upload(f"{h}.pdf", data, "application/pdf")
    payload = {"filename": name, "mime": "application/pdf", "hash": h,
               "storage_path": f"{h}.pdf", "storage_ref": ref,
               "origin": origin, "gbrain_labels": ["deck"]}
    if source_url:
        payload["source_url"] = source_url
    if drive_id:
        payload["drive_id"] = drive_id
    ins = conn.execute(
        "insert into gb_raw (source, source_id, payload, storage_ref, content_hash) "
        "values ('pdf', %s, %s::jsonb, %s, %s) on conflict (source, source_id) do nothing returning id",
        (h, json.dumps(payload), ref, h)).fetchone()
    if ins:
        return "queued", {"name": name, "id": h}
    return "skipped", {"url": name, "reason": "duplicate (already ingested)"}


def ingest_bytes(data: bytes, filename: str, origin: str = "computer") -> dict:
    """Ingest a PDF uploaded directly (e.g. from the user's computer). Same pipeline,
    same idempotency as Drive links. Returns {queued:[...], skipped:[...]}."""
    name = (filename or "deck.pdf").strip() or "deck.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    status, detail = _store(connect(), data, name, origin=origin)
    return {"queued": [detail], "skipped": []} if status == "queued" else {"queued": [], "skipped": [detail]}


def ingest_url(url: str) -> dict:
    """Ingest one Drive link (file / Slides / Docs / folder). Returns
    {queued:[{name,id}], skipped:[{url,reason}]}."""
    conn = connect()
    queued, skipped = [], []
    kind, fid = _parse(url)
    if not fid:
        return {"queued": [], "skipped": [{"url": url, "reason": "unrecognized Google Drive link"}]}
    with httpx.Client(follow_redirects=True, timeout=180) as client:
        if kind == "sheet":
            return {"queued": [], "skipped": [{"url": url, "reason": "spreadsheet — not a deck"}]}
        if kind == "folder":
            targets = [("file", f) for f in _list_folder(client, fid)]
            if not targets:
                skipped.append({"url": url, "reason": "empty/private folder — share 'anyone with link' or paste file links"})
        else:
            targets = [(kind, fid)]
        for k, f in targets:
            try:
                data, name = _download(client, k, f)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"url": f, "reason": f"download failed: {str(exc)[:80]}"})
                continue
            status, detail = _store(conn, data, name, origin="drive", source_url=url, drive_id=f)
            (queued if status == "queued" else skipped).append(detail)
    return {"queued": queued, "skipped": skipped}


def remove_deck(envelope_id: str) -> dict:
    """Hard-remove one ingested deck: its envelope + everything extracted FROM it
    (chunks/embeddings, observations, tasks, graph edges, attachment) + the gb_raw
    row + the bronze PDF object(s). Shared knowledge-graph entities (company, people)
    are PRESERVED — only this deck's own contributions are removed. Guarded to
    source='pdf' so it can never delete an email. Idempotent.
    Returns {removed: bool, title?, objects?, reason?}."""
    conn = connect()
    env = conn.execute(
        "select id, source, raw_id, title from gb_envelope where id=%s", (envelope_id,)
    ).fetchone()
    if env is None:
        return {"removed": False, "reason": "not found"}
    if env["source"] != "pdf":
        return {"removed": False, "reason": "not a deck — only uploaded/Drive PDFs can be removed here"}

    # capture bronze refs before the rows go away (raw + attachment may share one object)
    refs = set()
    if env["raw_id"]:
        raw = conn.execute("select storage_ref from gb_raw where id=%s", (env["raw_id"],)).fetchone()
        if raw and raw["storage_ref"]:
            refs.add(raw["storage_ref"])
    for a in conn.execute("select storage_ref from gb_attachment where envelope_id=%s "
                          "and storage_ref is not null", (envelope_id,)).fetchall():
        refs.add(a["storage_ref"])

    # delete children first (no ON DELETE CASCADE), then the envelope, then its raw row.
    # gb_chunk has an FK to gb_attachment, so chunks must go before attachments.
    for tbl in ("gb_chunk", "gb_observation", "gb_task", "gb_edge", "gb_attachment"):
        conn.execute(f"delete from {tbl} where envelope_id=%s", (envelope_id,))
    conn.execute("delete from gb_envelope where id=%s", (envelope_id,))
    if env["raw_id"]:
        conn.execute("delete from gb_raw where id=%s", (env["raw_id"],))

    objects = 0
    for ref in refs:
        try:
            storage.delete(ref); objects += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[remove_deck] bronze delete failed {ref}: {exc!r}", flush=True)
    return {"removed": True, "title": env["title"], "objects": objects}


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    q = s = 0
    for url in sys.argv[1:]:
        res = ingest_url(url)
        for x in res["queued"]:
            print(f"[drive] queued: {x['name']}", flush=True); q += 1
        for x in res["skipped"]:
            print(f"[drive] skip: {x.get('reason')} ({x.get('url','')[:60]})", flush=True); s += 1
    print(f"[drive] {q} queued, {s} skipped", flush=True)


if __name__ == "__main__":
    main()
