"""gbrain · safe numeric coercion (mirrors SQL gb_num).

Gemini's number fields are sometimes strings — "40-60", "~40", "$5M", "₹50 Cr",
"" — which would crash a numeric INSERT. safe_num() returns a float or None,
never raises.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def safe_num(val) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    # "$5M" / "$1.1B" → crore (matches the project's $1M = ₹8.5 Cr basis)
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*([mb])\b", s, re.I)
    if m:
        n = float(m.group(1))
        return round(n * (8.5 if m.group(2).lower() == "m" else 8500.0), 4)
    # first number in the string (handles "₹40 Cr", "~40", "40-60" → 40)
    m = _NUM.search(s)
    return float(m.group(0)) if m else None
