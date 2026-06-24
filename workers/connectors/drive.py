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
            if not data or data[:5] != b"%PDF-":
                skipped.append({"url": f, "reason": "not a downloadable PDF (private or non-PDF)"})
                continue
            h = hashlib.sha256(data).hexdigest()
            ref = storage.upload(f"{h}.pdf", data, "application/pdf")
            payload = {"filename": name, "mime": "application/pdf", "hash": h,
                       "storage_path": f"{h}.pdf", "storage_ref": ref, "drive_id": f,
                       "source_url": url, "gbrain_labels": ["deck"]}
            ins = conn.execute(
                "insert into gb_raw (source, source_id, payload, storage_ref, content_hash) "
                "values ('pdf', %s, %s::jsonb, %s, %s) on conflict (source, source_id) do nothing returning id",
                (h, json.dumps(payload), ref, h)).fetchone()
            if ins:
                queued.append({"name": name, "id": f})
            else:
                skipped.append({"url": f, "reason": "duplicate (already ingested)"})
    return {"queued": queued, "skipped": skipped}


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
