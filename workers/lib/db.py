"""gbrain · shared Postgres connection.

Workers connect with the *direct* Supabase connection string
(db.<ref>.supabase.co:5432) or the session-mode pooler — NOT the
transaction-mode pooler, which can interfere with pgmq visibility
timeouts and long-lived worker loops.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Load .env from the project root so manual runs work without `source .env`.
# (systemd also injects these via EnvironmentFile; load_dotenv won't override
# vars already set in the environment, so the two don't conflict.)
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass


def connect() -> psycopg.Connection:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
