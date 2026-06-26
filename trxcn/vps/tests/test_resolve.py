"""
Unit tests for the resolver's pure helpers (no browser needed).
Run:  python tests/test_resolve.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracxn.resolve import slugify, viewer_url, _is_pdf_response, _safe_name  # noqa: E402

cases = []
def check(label, got, want):
    ok = got == want
    cases.append((label, ok, got, want))

# slug mirrors Tracxn's viewer route
check("slug-mgt7", slugify("Form MGT-7"), "formmgt-7")
check("slug-allottees", slugify("List of Allottees"), "listofallottees")
check("slug-empty", slugify(""), "doc")

# viewer url
check("viewer", viewer_url("https://platform.tracxn.com", "abc123", "Form MGT-7"),
      "https://platform.tracxn.com/a/d/document/abc123/formmgt-7")

# pdf-response predicate
check("s3-pdf", _is_pdf_response("https://x.s3.amazonaws.com/a/b/Form.pdf?X-Amz-Signature=z", "application/octet-stream"), True)
check("s3-xml", _is_pdf_response("https://x.s3.amazonaws.com/a/b/Form.xml", ""), True)
check("by-ctype", _is_pdf_response("https://x/anything", "application/pdf; charset=binary"), True)
check("not-pdf-api", _is_pdf_response("https://platform.tracxn.com/api/4.0/companies", "application/json"), False)
check("not-pdf-img", _is_pdf_response("https://i.tracxn.com/logo.png", "image/png"), False)

# safe filename
check("safe-name", _safe_name("68dbe00a", "Form MGT-7"), "68dbe00a_formmgt-7.pdf")
check("safe-name-fallback", _safe_name("abc", None), "abc_abc.pdf")

fails = [c for c in cases if not c[1]]
for label, ok, got, want in cases:
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: {got!r}")
print("-" * 60)
if fails:
    print(f"FAILED ({len(fails)})")
    sys.exit(1)
print(f"PASS — {len(cases)} resolver-helper checks (slug, viewer URL, PDF predicate, filename).")
