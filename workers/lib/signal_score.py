"""gbrain · signal scoring — the LLM gate (build spec §8).

Cheap, deterministic, runs at normalize. Output 0–1; below THRESHOLD
the envelope is `skipped` and never reaches the LLM.

Tune by SKIP RATE, not by gut:
  near-zero skip rate  → gate too loose (paying for noise)
  very high skip rate  → gate too tight (dropping signal)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

THRESHOLD = float(os.environ.get("SIGNAL_THRESHOLD", "0.35"))

SOURCE_PRIORS = {
    "calendar": 0.6,
    "dashboard": 0.9,
    "pdf": 0.7,
    "drive_doc": 0.5,
    "gmail": 0.3,
    "whatsapp": 0.4,
}

# Deal vocabulary — extend freely; lowercase, matched on word boundaries.
DEAL_TERMS = [
    "round", "raise", "raising", "fundraise", "valuation", "term sheet",
    "termsheet", "arr", "mrr", "ebitda", "revenue", "runway", "cap table",
    "pre-money", "post-money", "due diligence", "dd", "cim", "teaser",
    "one-pager", "pitch deck", "deck", "investor", "lp", "gp", "series a",
    "series b", "seed", "pre-seed", "bridge", "convertible", "safe",
    "equity", "stake", "exit", "acquisition", "mandate", "engagement",
    "crore", "cr", "lakh", "₹",
]
_DEAL_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in DEAL_TERMS) + r")\b", re.IGNORECASE
)


@dataclass
class ScoreInput:
    source: str
    title: str | None = None
    body_clean: str | None = None
    labels: list[str] = field(default_factory=list)
    sender_is_known: bool = False
    has_doc_attachment: bool = False


def has_deal_terms(*texts: str | None) -> bool:
    return any(t and _DEAL_RE.search(t) for t in texts)


def signal_score(env: ScoreInput) -> float:
    s = SOURCE_PRIORS.get(env.source, 0.3)

    # calendar: internal-only events (standups, reminders — no non-Dexter
    # attendee) are noise unless they carry explicit deal language below.
    if env.source == "calendar" and "external-meeting" not in env.labels:
        s -= 0.40

    if env.sender_is_known:
        s += 0.20
    if has_deal_terms(env.title, env.body_clean):
        s += 0.25
    if env.has_doc_attachment:
        s += 0.20

    if "newsletter" in env.labels or "receipt" in env.labels:
        s -= 0.40

    body_len = len(env.body_clean or "")
    if body_len < 20 and not env.has_doc_attachment:
        s -= 0.30  # one-word "ok" messages

    # ALWAYS-EXTRACT override applied last, so penalties can't erode it.
    # (The spec's §8 pseudocode applies this before the length floor,
    # which lets a terse call-notes email slip under the threshold.)
    if "call-notes" in env.labels:
        s = max(s, 0.95)

    return max(0.0, min(1.0, s))
