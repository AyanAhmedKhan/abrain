"""
Authenticated Tracxn API client.

Auth model (validated live): the internal API authenticates on the ambient
session cookie alone — a POST with the right cookies returns 200, no CSRF/token
header required. So on a VPS we:

  1. PRIMARY: load cookies from a Playwright storage_state.json (captured once in
     a real browser via `python -m tracxn.client login`) or from TRACXN_COOKIE.
  2. FALLBACK: if a request comes back unauthenticated and creds are present,
     do a headless Playwright login, re-save storage_state, and retry.

Nothing secret is logged. The operator supplies the cookie / credentials.
"""
from __future__ import annotations
import json
import os
import sys
import time
import logging
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional

import httpx

from .config import Config

log = logging.getLogger("tracxn.client")


class AuthError(RuntimeError):
    pass


def _cookies_from_storage_state(path: str, base: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        log.warning("could not read storage_state %s: %s", path, e)
        return {}
    host = httpx.URL(base).host
    jar: Dict[str, str] = {}
    for c in data.get("cookies", []):
        dom = (c.get("domain") or "").lstrip(".")
        if dom and (dom in host or host in dom or dom.endswith("tracxn.com")):
            jar[c["name"]] = c["value"]
    return jar


def _cookies_from_header(header: str) -> Dict[str, str]:
    sc = SimpleCookie()
    sc.load(header)
    return {k: m.value for k, m in sc.items()}


class TracxnClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client: Optional[httpx.Client] = None
        self._build_client()

    # ---- session construction --------------------------------------------
    def _load_cookies(self) -> Dict[str, str]:
        if self.cfg.cookie_header:
            return _cookies_from_header(self.cfg.cookie_header)
        return _cookies_from_storage_state(self.cfg.storage_state_path, self.cfg.base)

    def _build_client(self) -> None:
        cookies = self._load_cookies()
        if not cookies:
            log.warning("no cookies loaded (storage_state=%s / TRACXN_COOKIE set=%s)",
                        self.cfg.storage_state_path, bool(self.cfg.cookie_header))
        headers = {
            "user-agent": self.cfg.user_agent,
            "origin": self.cfg.base,
            "referer": self.cfg.base + "/",
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
        }
        if self._client:
            self._client.close()
        self._client = httpx.Client(
            base_url=self.cfg.base,
            headers=headers,
            cookies=cookies,
            timeout=self.cfg.timeout_s,
            proxy=self.cfg.proxy,     # httpx>=0.28 uses singular `proxy`
            follow_redirects=False,   # a 3xx to /login means auth expired
        )

    # ---- low-level POST with retry + auth refresh ------------------------
    def post(self, path: str, body: dict) -> Any:
        attempted_login = False
        for attempt in range(self.cfg.max_retries + 1):
            try:
                r = self._client.post(path, content=json.dumps(body))
            except httpx.RequestError as e:
                self._sleep_backoff(attempt, f"network error: {e}")
                continue

            if r.status_code in (429, 503):
                self._sleep_backoff(attempt + 1, f"rate-limited {r.status_code}")
                continue

            if self._looks_unauthenticated(r):
                if not attempted_login and self._try_login_refresh():
                    attempted_login = True
                    continue
                raise AuthError(f"unauthenticated on {path} (status {r.status_code}); "
                                "cookie likely expired and login fallback unavailable/failed")

            if r.status_code >= 400:
                # surface a short, non-secret error
                raise RuntimeError(f"HTTP {r.status_code} on {path}: {r.text[:200]}")
            return r.json()
        raise RuntimeError(f"exhausted retries on {path}")

    @staticmethod
    def _looks_unauthenticated(r: httpx.Response) -> bool:
        if r.status_code in (401, 403):
            return True
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location", "")
            return "login" in loc.lower() or "signin" in loc.lower()
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype:   # API should return JSON; HTML => login page
            return True
        return False

    def _sleep_backoff(self, attempt: int, why: str) -> None:
        wait = (self.cfg.backoff_base_ms / 1000.0) * (2 ** max(0, attempt - 1))
        log.warning("%s — backing off %.1fs", why, wait)
        time.sleep(wait)

    # ---- Playwright login fallback ---------------------------------------
    def _try_login_refresh(self) -> bool:
        if not self.cfg.allow_login_fallback:
            return False
        if not (self.cfg.email and self.cfg.password):
            log.error("auth expired but TRACXN_EMAIL/TRACXN_PASSWORD not set — cannot refresh")
            return False
        log.info("session expired -> attempting headless login refresh")
        try:
            headless_login(self.cfg)   # writes storage_state_path
        except Exception as e:
            log.error("headless login failed: %s", e)
            return False
        self._build_client()           # reload cookies
        return True

    # ---- validated endpoints ---------------------------------------------
    def companies(self, ids: List[str], view: str = "profile", size: Optional[int] = None) -> List[dict]:
        body = {"view": view, "filter": {"id": ids}, "from": 0, "size": size or len(ids)}
        return self.post("/api/4.0/companies", body).get("result", [])

    def profile(self, company_id: str) -> Optional[dict]:
        res = self.companies([company_id], size=1)
        return res[0] if res else None

    def autocomplete(self, term: str, size: int = 10) -> List[dict]:
        r = self.post("/api/2.2/autocomplete", {"term": term, "query": {"name": "company", "size": size}})
        return r if isinstance(r, list) else []

    def resolve_ids(self, term: str, size: int = 10) -> List[Dict[str, str]]:
        out = []
        for x in self.autocomplete(term, size):
            p = x.get("payload") or {}
            if p.get("domainProfileId"):
                out.append({
                    "id": p["domainProfileId"], "name": p.get("companyName", ""),
                    "stage": p.get("companyStage", ""),
                    "country": (p.get("location") or {}).get("country", ""),
                    "website": p.get("domainName", ""),
                })
        return out

    def discover(self, filter_obj: dict, page_size: int = 50, max_records: int = 1000) -> List[Dict[str, str]]:
        """Page a filtered company query (filter copied from a list/sector page)."""
        out, frm = [], 0
        while frm < max_records:
            body = {"view": "profile", "filter": filter_obj, "from": frm, "size": page_size}
            res = self.post("/api/4.0/companies", body)
            batch = res.get("result", [])
            out += [{"id": c.get("id"), "name": c.get("name")} for c in batch]
            log.info("discover: %d/%s", len(out), res.get("total_count", "?"))
            if len(batch) < page_size:
                break
            frm += page_size
            time.sleep(self.cfg.delay_s)
        return out

    def statutory_financials(self, legal_entity_id: str) -> dict:
        agg = self.post("/api/4.0/statutoryfilings/aggregation", {
            "dataset": "query",
            "filter": {"documentType": ["Financial Documents", "Annual Reports"],
                       "legalEntityId": [legal_entity_id], "tracxnUrl": "t_all"},
            "aggMap": [{"field": "documentType", "includeBucket": ["Financial Documents"],
                        "aggMap": [{"field": "id", "size": 5, "operation": "sort",
                                    "sort": [{"sortField": "metaPropertiesCurrentYearStartDate", "order": "DESC"}]}]}],
        })
        ids = _collect_filing_ids(agg)
        if not ids:
            return {"filings": [], "note": "no filing ids"}
        return self.post("/api/4.0/statutoryfilings/india",
                         {"dataset": "query", "filter": {"id": ids[:10]}})

    def list_filings(self, legal_entity_id, since_year=None, page_size=50, max_records=5000):
        """List ALL statutory filings for a legal entity (paginated).

        Returns the raw filing records (id, name, documentType, filingDate, ...).
        `since_year` keeps only filings on/after that filing year (client-side).
        """
        out, frm = [], 0
        while frm < max_records:
            body = {"dataset": "query", "filter": {"legalEntityId": [legal_entity_id]},
                    "from": frm, "size": page_size,
                    "sort": [{"sortField": "filingDate", "order": "DESC"}]}
            res = self.post("/api/4.0/statutoryfilings/india", body)
            batch = res.get("result", [])
            if not batch:
                break
            for rec in batch:
                if since_year:
                    fy = (rec.get("filingDate") or {}).get("year")
                    if fy and fy < since_year:
                        return out          # sorted DESC -> everything after is older
                out.append(rec)
            total = res.get("total_count")
            log.info("filings %s: %d%s", legal_entity_id, len(out), "/" + str(total) if total else "")
            if len(batch) < page_size or (total and len(out) >= total):
                break
            frm += page_size
            time.sleep(self.cfg.delay_s)
        return out

    def close(self) -> None:
        if self._client:
            self._client.close()


def _collect_filing_ids(obj: Any) -> List[str]:
    found: List[str] = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "id" and isinstance(v, str) and len(v) == 24:
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    # de-dupe, keep order
    seen, out = set(), []
    for i in found:
        if i not in seen:
            seen.add(i); out.append(i)
    return out


# ---- Playwright login (used both for the CLI 'login' seed and the fallback) ---
def headless_login(cfg: Config, headless: bool = True) -> str:
    """Log in with Playwright and write cfg.storage_state_path. Returns the path.

    Selectors target Tracxn's standard email+password form. If the form changes
    or MFA is enabled, run `python -m tracxn.client login` once with headless=False
    to complete it interactively (incl. OTP) and capture the session.
    """
    from playwright.sync_api import sync_playwright

    if not (cfg.email and cfg.password) and headless:
        raise AuthError("TRACXN_EMAIL/TRACXN_PASSWORD required for headless login")

    launch_args = {"headless": headless}
    ctx_args: Dict[str, Any] = {"user_agent": cfg.user_agent}
    if cfg.proxy:
        launch_args["proxy"] = {"server": cfg.proxy}

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_args)
        ctx = browser.new_context(**ctx_args)
        page = ctx.new_page()
        page.goto(cfg.login_url, wait_until="domcontentloaded")

        if headless:
            _fill_login_form(page, cfg.email, cfg.password)
        else:
            print("Complete the login (and any OTP) in the opened browser window...",
                  file=sys.stderr)

        # wait until we're authenticated (dashboard reachable / cookie present)
        try:
            page.wait_for_url("**/a/**", timeout=120_000 if not headless else 45_000)
        except Exception:
            page.wait_for_timeout(3000)

        ctx.storage_state(path=cfg.storage_state_path)
        browser.close()
    log.info("saved session -> %s", cfg.storage_state_path)
    return cfg.storage_state_path


def _fill_login_form(page, email: str, password: str) -> None:
    # email (handles single-page and email-first flows)
    for sel in ['input[type="email"]', 'input[name="email"]', '#email', 'input[name="username"]']:
        if page.locator(sel).count():
            page.fill(sel, email)
            break
    # some flows need a Continue before the password appears
    for sel in ['button:has-text("Continue")', 'button:has-text("Next")']:
        loc = page.locator(sel)
        if loc.count() and not page.locator('input[type="password"]').count():
            loc.first.click()
            page.wait_for_timeout(800)
            break
    for sel in ['input[type="password"]', 'input[name="password"]', '#password']:
        if page.locator(sel).count():
            page.fill(sel, password)
            break
    for sel in ['button[type="submit"]', 'button:has-text("Log in")',
                'button:has-text("Sign in")', 'button:has-text("Login")']:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            break


if __name__ == "__main__":
    # `python -m tracxn.client login`  -> headful capture of a session
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config()
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        headless_login(cfg, headless=False)
        print(f"Session saved to {cfg.storage_state_path}")
    else:
        # quick connectivity check
        c = TracxnClient(cfg)
        hits = c.resolve_ids("Lenskart", 3)
        print(json.dumps(hits, indent=1))
        c.close()
