"""gbrain · Gmail call-notes classifier.

Decides, for every Gmail message pulled by the broad receiver, whether it
is INDEXED (call note / deal-relevant) or SKIPPED (confidential, personal,
automated, or low-signal). Confidential/personal mail is never extracted,
embedded, or made searchable.

Priority (first match wins):
  0. Trusted label   → INDEX (call-notes)            — "if labelled, good"
  1. Automated/bulk  → SKIP  (newsletter|automated)
  2. Confidential    → SKIP  (security|finance|hr)   — never indexed
  3. Deal signals    → INDEX (deal-flow)             — subject/attachment/sender/mention
  4. Default         → SKIP  (low_signal)            — under-index beats indexing noise

EDIT the lists below to tune. `GMAIL_DEAL_LABEL_IDS` (env, comma-separated
Gmail label IDs) makes label-trust fire for your "Call Notes" label even
though Gmail exposes custom labels as opaque IDs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from workers.lib.signal_score import _DEAL_RE  # reuse the deal vocabulary

# ── config (editable) ────────────────────────────────────────
DEAL_LABEL_IDS = {x.strip() for x in
                  os.environ.get("GMAIL_DEAL_LABEL_IDS", "").split(",") if x.strip()}
# Gmail's own buckets we treat as bulk:
GMAIL_BULK_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS", "SPAM"}

CALL_NOTE_SUBJECT = re.compile(
    r"\b(call notes?|meeting notes?|mom|minutes of meeting|notes from|debrief|"
    r"intro(duction)? (call|to)|recap)\b", re.I)

# strong deal subject cues beyond the shared DEAL vocabulary
DEAL_SUBJECT = re.compile(
    r"\b(pitch|deck|teaser|cim|one[- ]pager|opportunity|mandate|"
    r"raising|fundrais|investment|term sheet|data ?room|due diligence)\b", re.I)

# ── confidential / personal — NEVER index ────────────────────
# NB: the word "confidential" alone is NOT a trigger — decks/CIMs are
# routinely marked confidential. We target security, personal finance, HR.
SECURITY = re.compile(
    r"\b(otp|one[- ]time password|verification code|login code|2fa|"
    r"password reset|reset your password|security code|authentication code)\b", re.I)
PERSONAL_FINANCE = re.compile(
    r"\b(payslip|pay slip|salary slip|salary credited|ctc|bank statement|"
    r"account statement|e-statement|credit card statement|mini statement|"
    r"upi|emi due|policy premium|itr|form 16)\b", re.I)
HR = re.compile(
    r"\b(offer letter|appointment letter|relieving letter|appraisal|"
    r"increment letter|performance review|leave (request|approval)|reimbursement)\b", re.I)

# automated/no-reply sender fragments
AUTOMATED_SENDERS = ("no-reply", "noreply", "no_reply", "donotreply", "do-not-reply",
                     "notifications@", "notification@", "mailer@", "mailer-daemon",
                     "bounce", "newsletter@", "updates@", "alerts@", "auto@")


@dataclass
class Decision:
    action: str            # 'index' | 'skip'
    labels: list[str] = field(default_factory=list)
    reason: str = ""


def _header(p: dict, name: str) -> str:
    for h in (p.get("payload", {}) or {}).get("headers", []) or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value") or ""
    return p.get(name) or p.get(name.lower()) or ""


_STRIP_PREFIX = re.compile(r"^\s*((re|fwd|fw|aw)\s*:\s*)+", re.I)


def classify_gmail(payload: dict, body: str, has_pdf: bool,
                   spine_terms: set[str] | None = None,
                   known_senders: set[str] | None = None) -> Decision:
    label_ids = set(payload.get("labelIds", []) or [])
    subject = _STRIP_PREFIX.sub("", _header(payload, "Subject")).strip()
    from_raw = _header(payload, "From").lower()
    text = f"{subject}\n{body or ''}"

    # 0 ── trusted label → always index
    if label_ids & DEAL_LABEL_IDS:
        return Decision("index", ["call-notes"], "trusted_label")

    # 1 ── automated / bulk
    if _header(payload, "List-Unsubscribe") or _header(payload, "List-Id"):
        return Decision("skip", reason="newsletter")
    if (_header(payload, "Auto-Submitted") not in ("", "no")) or \
       _header(payload, "Precedence").lower() in ("bulk", "list", "junk"):
        return Decision("skip", reason="automated")
    if any(s in from_raw for s in AUTOMATED_SENDERS):
        return Decision("skip", reason="automated")
    if label_ids & GMAIL_BULK_LABELS:
        return Decision("skip", reason="newsletter")

    # 2 ── confidential / personal — never index (checked on SUBJECT)
    if SECURITY.search(subject):
        return Decision("skip", reason="confidential_security")
    if PERSONAL_FINANCE.search(subject):
        return Decision("skip", reason="confidential_finance")
    if HR.search(subject):
        return Decision("skip", reason="confidential_hr")

    # 3 ── deal signals → index
    if CALL_NOTE_SUBJECT.search(subject):
        return Decision("index", ["call-notes"], "subject_callnote")
    if DEAL_SUBJECT.search(text) or _DEAL_RE.search(text):
        return Decision("index", ["deal-flow"], "subject_deal")
    if has_pdf and (DEAL_SUBJECT.search(text) or _DEAL_RE.search(text)):
        return Decision("index", ["deal-flow"], "attachment_deal")
    if known_senders and any(s and s in from_raw for s in known_senders):
        return Decision("index", ["deal-flow"], "known_sender")
    if spine_terms:
        low = text.lower()
        if any(t in low for t in spine_terms):
            return Decision("index", ["deal-flow"], "mention")

    # 4 ── default: don't index
    return Decision("skip", reason="low_signal")
