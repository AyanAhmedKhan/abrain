"""
Output sinks.

  - JsonlSink: always-on local backup/audit (one JSON object per line).
  - GbrainSink: POST normalized companies to gbrain's REST/webhook endpoint.

GbrainSink is intentionally simple and configurable so it fits whatever gbrain
expects: per-company or batched POST, custom auth header/scheme, dry-run.
"""
from __future__ import annotations
import json
import os
import time
import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import Config

log = logging.getLogger("tracxn.sinks")


class JsonlSink:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    def push(self, row: Dict[str, Any]) -> None:
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class GbrainSink:
    """POST companies to gbrain's HTTP endpoint.

    Payload shape per request:
      batch == 1 : {"source":"tracxn","company": {...}}
      batch  > 1 : {"source":"tracxn","companies": [ {...}, ... ]}
    Adjust `_envelope` if gbrain expects a different schema.
    """
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.enabled = bool(cfg.gbrain_url)
        self._buf: List[Dict[str, Any]] = []
        headers = {"content-type": "application/json"}
        if cfg.gbrain_api_key:
            scheme = (cfg.gbrain_auth_scheme + " ") if cfg.gbrain_auth_scheme else ""
            headers[cfg.gbrain_auth_header] = f"{scheme}{cfg.gbrain_api_key}"
        # gbrain is usually your own infra -> no proxy
        self._client = httpx.Client(timeout=cfg.timeout_s, headers=headers)
        if not self.enabled:
            log.warning("GBRAIN_WEBHOOK_URL not set — gbrain push disabled (JSONL still written)")

    def _envelope(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self.cfg.gbrain_batch <= 1:
            return {"source": "tracxn", "company": rows[0]}
        return {"source": "tracxn", "companies": rows}

    def push(self, row: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._buf.append(row)
        if len(self._buf) >= max(1, self.cfg.gbrain_batch):
            self.flush()

    def flush(self) -> None:
        if not self.enabled or not self._buf:
            return
        rows, self._buf = self._buf, []
        payload = self._envelope(rows)
        if self.cfg.gbrain_dry_run:
            log.info("[dry-run] would POST %d company(ies) to gbrain", len(rows))
            return
        for attempt in range(self.cfg.max_retries + 1):
            try:
                r = self._client.post(self.cfg.gbrain_url, content=json.dumps(payload, ensure_ascii=False))
                if r.status_code in (429, 503):
                    wait = (self.cfg.backoff_base_ms / 1000.0) * (2 ** attempt)
                    log.warning("gbrain %s — retry in %.1fs", r.status_code, wait)
                    time.sleep(wait); continue
                r.raise_for_status()
                log.info("gbrain <- %d company(ies) [%s]", len(rows), r.status_code)
                return
            except httpx.HTTPError as e:
                if attempt >= self.cfg.max_retries:
                    log.error("gbrain push FAILED after retries: %s (rows kept in JSONL)", e)
                    return
                time.sleep((self.cfg.backoff_base_ms / 1000.0) * (2 ** attempt))

    def close(self) -> None:
        self.flush()
        self._client.close()


class FanoutSink:
    """Write to several sinks; one failing never blocks the others."""
    def __init__(self, sinks: List[Any]):
        self.sinks = sinks

    def push(self, row: Dict[str, Any]) -> None:
        for s in self.sinks:
            try:
                s.push(row)
            except Exception as e:
                log.error("sink %s push error: %s", type(s).__name__, e)

    def close(self) -> None:
        for s in self.sinks:
            try:
                s.close()
            except Exception as e:
                log.error("sink %s close error: %s", type(s).__name__, e)
