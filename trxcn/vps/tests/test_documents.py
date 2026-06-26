"""
Regression test for the document normalizer (flatten_document).
Fixture mirrors a real statutoryfilings/india record observed live (Lenskart MGT-7).

Run:  python tests/test_documents.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracxn.normalize import flatten_document  # noqa: E402

COMPANY = {"id": "52bfc960e4b0420b03968ee8", "name": "Lenskart"}
BASE = "https://platform.tracxn.com"

REC = {
    "id": "68dbe00a33632f05f4345ecd",
    "name": "Form MGT-7",
    "documentType": "Annual Returns",
    "category": "Annual Reports",
    "filingType": "Annual Return",
    "registrar": "mca.gov.in",
    "filingDate": {"day": 24, "month": 9, "year": 2025},
    "documentCode": "MGT7",
    "metaProperties": {"cin": "U33100DL2008PLC178355"},
}

EXPECT = {
    "kind": "document",
    "company_id": "52bfc960e4b0420b03968ee8",
    "company_name": "Lenskart",
    "id": "68dbe00a33632f05f4345ecd",
    "name": "Form MGT-7",
    "document_type": "Annual Returns",
    "filing_date": "2025-09-24",
    "cin": "U33100DL2008PLC178355",
    "viewer_url": "https://platform.tracxn.com/a/d/document/68dbe00a33632f05f4345ecd/formmgt-7",
}


def main() -> int:
    row = flatten_document(REC, COMPANY, BASE)
    failures = []
    for k, want in EXPECT.items():
        got = row.get(k)
        ok = got == want
        print(f"  [{'ok ' if ok else 'FAIL'}] {k}: {got!r}")
        if not ok:
            failures.append(f"{k}: got {got!r}, want {want!r}")
    # empty/edge: missing id -> no viewer_url, no crash
    edge = flatten_document({"name": "x"}, COMPANY, BASE)
    if edge["viewer_url"] != "":
        failures.append("edge: missing id should yield empty viewer_url")
    print("-" * 60)
    if failures:
        print("FAILED:")
        for f in failures:
            print("   -", f)
        return 1
    print("PASS — document normalizer maps filing -> {metadata + viewer_url}, slug + date correct.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
