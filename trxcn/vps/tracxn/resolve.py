"""
On-demand PDF resolver for statutory-filing documents.

WHY THIS DESIGN (best practice): a filing's real download URL is a *pre-signed,
expiring* S3 link that Tracxn derives server-side, and the derivation varies by
document type (verified live — unsigned URL construction returns 403). So rather
than reverse-engineer and guess fragile URLs, we let Tracxn's own viewer page
resolve the link in your authenticated session and intercept the PDF response.
This is universal (works for every doc type), uses the same session/proxy as the
rest of the tool, and never caches a link that will rot.

Usage
-----
  # one document
  python -m tracxn.resolve 68dbe00a33632f05f4345ecd --name "Form MGT-7" --out ./out/docs
  # from gbrain / code
  from tracxn.config import Config
  from tracxn.resolve import fetch_pdf, fetch_many
  data = fetch_pdf(Config(), document_id)            # -> bytes
  for did, path, err in fetch_many(Config(), items): ...

Needs Playwright + chromium (already used by the login fallback) and a valid
storage_state.json / TRACXN_COOKIE.
"""
from __future__ import annotations
import os
import re
import sys
import json
import logging
from typing import Iterable, List, Optional, Tuple

from .config import Config

log = logging.getLogger("tracxn.resolve")


def slugify(name: str) -> str:
    """Mirror Tracxn's viewer-route slug (lowercase, whitespace stripped)."""
    return re.sub(r"\s+", "", (name or "doc")).lower() or "doc"


def viewer_url(base: str, document_id: str, name: str = "doc") -> str:
    return f"{base}/a/d/document/{document_id}/{slugify(name)}"


def _is_pdf_response(url: str, content_type: str) -> bool:
    """True for the actual document file response (S3 PDF/XML)."""
    if not url:
        return False
    u = url.split("?")[0].lower()
    if "amazonaws" in url and (u.endswith(".pdf") or u.endswith(".xml")):
        return True
    if "application/pdf" in (content_type or "").lower():
        return True
    return False


def _safe_name(document_id: str, name: Optional[str]) -> str:
    base = slugify(name) if name else document_id
    base = re.sub(r"[^a-z0-9._-]+", "_", base)[:80]
    return f"{document_id}_{base}.pdf"


def _new_context(p, cfg: Config):
    launch = {"headless": True}
    if cfg.proxy:
        launch["proxy"] = {"server": cfg.proxy}
    browser = p.chromium.launch(**launch)
    ctx_args = {"user_agent": cfg.user_agent, "accept_downloads": True}
    if os.path.exists(cfg.storage_state_path):
        ctx_args["storage_state"] = cfg.storage_state_path
    ctx = browser.new_context(**ctx_args)
    return browser, ctx


def _capture_one(ctx, cfg: Config, document_id: str, name: Optional[str], timeout_ms: int) -> bytes:
    """Open the viewer for one document and return the intercepted PDF bytes."""
    page = ctx.new_page()
    captured = {"body": None}

    def on_response(resp):
        if captured["body"] is not None:
            return
        try:
            ctype = resp.headers.get("content-type", "")
            if _is_pdf_response(resp.url, ctype):
                captured["body"] = resp.body()
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(viewer_url(cfg.base, document_id, name or "doc"),
                  wait_until="domcontentloaded", timeout=timeout_ms)
        # poll until the file response is intercepted
        waited = 0
        while captured["body"] is None and waited < timeout_ms:
            page.wait_for_timeout(500)
            waited += 500
    finally:
        page.close()

    if captured["body"] is None:
        raise RuntimeError(f"no PDF response intercepted for {document_id} "
                           "(session expired, or the doc has no downloadable file)")
    return captured["body"]


def fetch_many(cfg: Config, items: Iterable, out_dir: Optional[str] = None,
               timeout_ms: int = 45000) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Resolve many documents reusing ONE browser context.

    `items` is an iterable of either document_id strings or (document_id, name)
    tuples. Returns a list of (document_id, saved_path_or_None, error_or_None).
    If out_dir is None, PDFs are not written (use fetch_pdf for raw bytes).
    """
    from playwright.sync_api import sync_playwright

    norm = [(i if isinstance(i, (tuple, list)) else (i, None)) for i in items]
    results: List[Tuple[str, Optional[str], Optional[str]]] = []
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        browser, ctx = _new_context(p, cfg)
        try:
            for document_id, name in norm:
                try:
                    body = _capture_one(ctx, cfg, document_id, name, timeout_ms)
                    if out_dir:
                        path = os.path.join(out_dir, _safe_name(document_id, name))
                        with open(path, "wb") as fh:
                            fh.write(body)
                        results.append((document_id, path, None))
                        log.info("resolved %s -> %s (%d bytes)", document_id, path, len(body))
                    else:
                        results.append((document_id, None, None))
                        log.info("resolved %s (%d bytes, not saved)", document_id, len(body))
                except Exception as e:
                    results.append((document_id, None, str(e)))
                    log.warning("resolve failed %s: %s", document_id, e)
        finally:
            browser.close()
    return results


def fetch_pdf(cfg: Config, document_id: str, name: Optional[str] = None,
              out_dir: Optional[str] = None, timeout_ms: int = 45000) -> bytes:
    """Resolve ONE document and return its PDF bytes (also saved if out_dir set)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx = _new_context(p, cfg)
        try:
            body = _capture_one(ctx, cfg, document_id, name, timeout_ms)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
                path = os.path.join(out_dir, _safe_name(document_id, name))
                with open(path, "wb") as fh:
                    fh.write(body)
                log.info("resolved %s -> %s (%d bytes)", document_id, path, len(body))
            return body
        finally:
            browser.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Resolve a Tracxn filing document to a PDF")
    ap.add_argument("document_id")
    ap.add_argument("--name", help="document name (for a nicer filename/slug)")
    ap.add_argument("--out", default="out/docs", help="directory to save the PDF into")
    ap.add_argument("--timeout", type=int, default=45000, help="ms to wait for the PDF")
    a = ap.parse_args()
    data = fetch_pdf(Config(), a.document_id, a.name, out_dir=a.out, timeout_ms=a.timeout)
    print(f"OK: {len(data)} bytes -> {a.out}")
