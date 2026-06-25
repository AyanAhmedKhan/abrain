"""
Central config, all from environment (12-factor). Nothing secret is hard-coded;
the VPS operator sets these (e.g. in /etc/tracxn.env or a systemd EnvironmentFile).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Config:
    base: str = os.environ.get("TRACXN_BASE", "https://platform.tracxn.com")

    # --- auth (cookie primary, login fallback) ---
    # Path to a Playwright storage_state.json (preferred) OR a raw Cookie header.
    storage_state_path: str = os.environ.get("TRACXN_STORAGE_STATE", "storage_state.json")
    cookie_header: Optional[str] = os.environ.get("TRACXN_COOKIE") or None
    email: Optional[str] = os.environ.get("TRACXN_EMAIL") or None
    password: Optional[str] = os.environ.get("TRACXN_PASSWORD") or None
    login_url: str = os.environ.get("TRACXN_LOGIN_URL", "https://platform.tracxn.com/a/login")
    allow_login_fallback: bool = os.environ.get("TRACXN_LOGIN_FALLBACK", "1") != "0"

    # --- politeness / resilience ---
    delay_ms: int = _i("TRACXN_DELAY_MS", 1500)        # pause between companies
    max_retries: int = _i("TRACXN_MAX_RETRIES", 3)
    backoff_base_ms: int = _i("TRACXN_BACKOFF_MS", 2000)
    timeout_s: float = _f("TRACXN_TIMEOUT_S", 30.0)
    proxy: Optional[str] = os.environ.get("TRACXN_PROXY") or os.environ.get("HTTPS_PROXY") or None

    # --- output ---
    jsonl_path: str = os.environ.get("TRACXN_JSONL", "out/tracxn.jsonl")
    state_path: str = os.environ.get("TRACXN_STATE", "out/processed_ids.txt")

    # --- gbrain REST sink ---
    gbrain_url: Optional[str] = os.environ.get("GBRAIN_WEBHOOK_URL") or None
    gbrain_api_key: Optional[str] = os.environ.get("GBRAIN_API_KEY") or None
    gbrain_auth_header: str = os.environ.get("GBRAIN_AUTH_HEADER", "Authorization")
    gbrain_auth_scheme: str = os.environ.get("GBRAIN_AUTH_SCHEME", "Bearer")
    gbrain_batch: int = _i("GBRAIN_BATCH", 1)          # companies per POST (1 = one-at-a-time)
    gbrain_dry_run: bool = os.environ.get("GBRAIN_DRY_RUN", "0") == "1"

    user_agent: str = os.environ.get(
        "TRACXN_UA",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )

    @property
    def delay_s(self) -> float:
        return self.delay_ms / 1000.0
