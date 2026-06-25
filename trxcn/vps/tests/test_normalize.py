"""
Regression test: the Python normalizer must reproduce the exact numbers the
JS flattener produced live against Lenskart, Paytm, Stripe and Zerodha.

Run:  python tests/test_normalize.py     (no pytest needed)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracxn.normalize import flatten  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDS = json.load(open(os.path.join(HERE, "fixture_live.json"), encoding="utf-8"))
BY_NAME = {flatten(r)["name"]: flatten(r) for r in RECORDS}

# Expected values = what the validated JS flattener returned live.
EXPECT = {
    "Lenskart": {  # full financials, INR base, growth CAGRs
        "country": "India", "stage": "Public",
        "revenue_inr_cr": 7009.28, "revenue_usd_m": 829.13, "revenue_growth_1y": 25,
        "ebitda_inr_cr": 1332.26, "valuation_inr_cr": 35940.08,
        "investors": "SoftBank Vision Fund; Chiratae Ventures; TPG",
        "sector_starts": "Consumer > Fashion Tech",
    },
    "Paytm": {  # loss-making -> NEGATIVE net profit
        "country": "India", "revenue_inr_cr": 7624.9, "ebitda_inr_cr": 43.8,
        "net_profit_inr_cr": -663.2, "valuation_inr_cr": 115789.94, "valuation_usd_m": 15619.75,
    },
    "Stripe": {  # foreign HQ, USD base, no Indian revenue filed
        "country": "United States", "stage": "Series I",
        "revenue_inr_cr": "", "valuation_usd_m": 159000.0,
    },
    "Zerodha": {  # bootstrapped -> empty investors, profitable
        "country": "India", "stage": "Unfunded", "investors": "",
        "revenue_inr_cr": 8868.21, "ebitda_inr_cr": 5663.77, "net_profit_inr_cr": 4236.72,
    },
}


def main() -> int:
    failures = []
    for name, exp in EXPECT.items():
        row = BY_NAME.get(name)
        if not row:
            failures.append(f"{name}: missing from fixture")
            continue
        for key, want in exp.items():
            if key == "sector_starts":
                got = row["sector"]
                ok = isinstance(got, str) and got.startswith(want)
            else:
                got = row.get(key)
                ok = got == want
            status = "ok " if ok else "FAIL"
            print(f"  [{status}] {name}.{key}: got={got!r} want={want!r}")
            if not ok:
                failures.append(f"{name}.{key}: got {got!r}, want {want!r}")

    print("-" * 60)
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print("   -", f)
        return 1
    print(f"PASS — {len(EXPECT)} companies, all edge cases reproduced "
          "(negatives, missing financials, foreign/USD base, empty investors).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
