"""gbrain · Supabase Storage (bronze) helper.

Raw files live once in the private `gbrain-bronze` bucket, keyed by
content hash, and are referenced everywhere by `storage_ref`.
Uses the Storage REST API with the service_role key (server-side only).
"""

from __future__ import annotations

import os

import httpx

BUCKET = os.environ.get("BRONZE_BUCKET", "gbrain-bronze")


def _base() -> tuple[str, dict]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (see .env.example)")
    return url, {"Authorization": f"Bearer {key}", "apikey": key}


MAX_FILE_MB = int(os.environ.get("GMAIL_MAX_FILE_MB", "100"))


def upload(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Idempotent upload (upsert). Returns the storage_ref `bucket/path`."""
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise RuntimeError(f"attachment too large: {len(data)//1024//1024}MB > {MAX_FILE_MB}MB")
    url, headers = _base()
    headers = {**headers, "Content-Type": content_type, "x-upsert": "true"}
    r = httpx.post(f"{url}/storage/v1/object/{BUCKET}/{path}",
                   content=data, headers=headers, timeout=300)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"storage upload failed {r.status_code}: {r.text[:300]}")
    return f"{BUCKET}/{path}"


def download(storage_ref: str) -> bytes:
    """storage_ref is `bucket/path` (as stored in gb_raw/gb_attachment)."""
    url, headers = _base()
    bucket, _, path = storage_ref.partition("/")
    r = httpx.get(f"{url}/storage/v1/object/{bucket}/{path}",
                  headers=headers, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"storage download failed {r.status_code}: {r.text[:300]}")
    return r.content


def signed_url(storage_ref: str, expires: int = 600) -> str:
    """Short-lived public URL to view/download a private bronze object (e.g. open
    the original deck PDF from the dashboard). Service key never leaves the server."""
    url, headers = _base()
    bucket, _, path = storage_ref.partition("/")
    r = httpx.post(f"{url}/storage/v1/object/sign/{bucket}/{path}",
                   headers={**headers, "Content-Type": "application/json"},
                   json={"expiresIn": expires}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"storage sign failed {r.status_code}: {r.text[:200]}")
    signed = r.json()["signedURL"]          # relative to /storage/v1, e.g. /object/sign/...
    if signed.startswith("http"):
        return signed
    if not signed.startswith("/"):
        signed = "/" + signed
    if not signed.startswith("/storage/v1"):
        signed = "/storage/v1" + signed
    return url + signed
