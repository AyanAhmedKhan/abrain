"""gbrain · tiny localhost HTTP wrapper around workers.ask (for the dashboard).

Stdlib only (no Flask) — single-user, 127.0.0.1. The dashboard proxies to it
server-side so all LLM access stays in Python.

    POST /ask           {"question": "..."} → {"answer": str, "sources": [...]}
    POST /ingest-drive  {"url": "..."}      → {"queued": [...], "skipped": [...]}
    GET  /deck?ref=<bronze ref>             → {"url": <short-lived signed URL>}
    GET  /health                            → {"ok": true}

Env: ASK_PORT (default 8090).
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from workers.ask import ask
from workers.connectors.drive import ingest_url
from workers.lib import storage

BUCKET = os.environ.get("BRONZE_BUCKET", "gbrain-bronze")


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/health"):
            return self._send({"ok": True})
        if u.path.rstrip("/") == "/deck":
            ref = (parse_qs(u.query).get("ref") or [""])[0]
            if not ref or not ref.startswith(BUCKET + "/"):  # SSRF guard: bronze only
                return self._send({"error": "bad ref"}, 400)
            try:
                return self._send({"url": storage.signed_url(ref)})
            except Exception as exc:  # noqa: BLE001
                return self._send({"error": str(exc)[:200]}, 502)
        self._send({"error": "not found"}, 404)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or "{}")

    def do_POST(self):
        path = self.path.rstrip("/")
        try:
            body = self._body()
        except Exception:  # noqa: BLE001
            return self._send({"error": "bad request"}, 400)
        if path == "/ask":
            q = (body.get("question") or "").strip()
            if not q:
                return self._send({"error": "empty question"}, 400)
            try:
                return self._send(ask(q))
            except Exception as exc:  # noqa: BLE001
                return self._send({"error": str(exc)[:300]}, 500)
        if path == "/ingest-drive":
            url = (body.get("url") or "").strip()
            if not url:
                return self._send({"error": "empty url"}, 400)
            try:
                return self._send(ingest_url(url))
            except Exception as exc:  # noqa: BLE001
                return self._send({"error": str(exc)[:300]}, 500)
        self._send({"error": "not found"}, 404)

    def log_message(self, *a):  # quiet
        pass


def main():
    port = int(os.environ.get("ASK_PORT", "8090"))
    print(f"[ask] serving on 127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
