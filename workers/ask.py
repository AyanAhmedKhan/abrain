"""gbrain · ask the brain (M5 — retrieval-augmented Q&A).

Answers a natural-language question over the indexed deal flow, grounding the
LLM in two retrieved contexts:

  1. a compact DEAL-FACTS table  — every indexed company's latest sector /
     stage / ask / revenue / valuation (handles aggregate & numeric questions
     like "which DeepTech deals are raising > ₹100 cr?").
  2. top-k SEMANTIC CHUNKS       — pgvector nearest neighbours to the question
     (handles qualitative questions like "summarize the Park+ call").

Then Gemini answers using ONLY that context and cites the companies it used.
No new tables; reads what the pipeline already produced. $0 retrieval, one
cheap Gemini call per question (FAKE mode answers without tokens).

Run:  python -m workers.ask "which fintech companies are raising the most?"
"""

from __future__ import annotations

import sys

from workers.lib.db import connect
from workers.lib.gemini import embed, generate_text

TOP_K = 8
MAX_CHUNK_CHARS = 700

PROMPT = """You are an analyst at Dexter Capital, an Indian investment bank and \
micro-VC. Answer the QUESTION using ONLY the CONTEXT below — it is drawn from \
the firm's own deal-flow database (call notes + structured deal data).

Rules:
- Be concise and specific. Cite the company names you used.
- Quote figures with their company and period (e.g. "Park+ — revenue ₹215 Cr (FY26)").
- For "which / list / compare" questions, use the DEAL FACTS table.
- If the answer isn't in the context, say: "I don't have that in the brain yet."
- Never invent companies or numbers.

QUESTION: {q}

=== MATCHED COMPANY DOSSIER (use this first if the question names a company) ===
{dossier}

=== DEAL FACTS (company · sector · stage · ask₹cr · revenue₹cr · valuation₹cr) ===
{facts}

=== RELEVANT CALL-NOTE EXCERPTS ===
{chunks}

ANSWER:"""


def deal_facts(conn) -> str:
    rows = conn.execute(
        """select distinct on (extraction->>'company_name')
                extraction->>'company_name' co, extraction->>'sector' sec,
                extraction->>'stage' stg, extraction->>'ask_inr_cr' ask,
                extraction->>'revenue_inr_cr' rev, extraction->>'valuation_inr_cr' val
           from gb_envelope
           where status='indexed' and extraction->>'company_name' is not null
             and extraction->>'company_name' <> ''
           order by extraction->>'company_name', ingested_at desc"""
    ).fetchall()
    out = []
    for r in rows:
        out.append(f"- {r['co']} · {r['sec'] or '?'} · {r['stg'] or '?'} · "
                   f"ask {r['ask'] or '-'} · rev {r['rev'] or '-'} · val {r['val'] or '-'}")
    return "\n".join(out) or "(no indexed companies yet)"


def dossier(conn, question: str) -> str:
    """If the question names companies we know, pull their full notes verbatim."""
    ql = question.lower()
    names = conn.execute(
        "select distinct extraction->>'company_name' co from gb_envelope "
        "where status='indexed' and coalesce(extraction->>'company_name','') <> ''"
    ).fetchall()
    hits = [r["co"] for r in names if r["co"] and len(r["co"]) >= 3 and r["co"].lower() in ql]
    out = []
    for co in hits[:4]:
        r = conn.execute(
            "select extraction n from gb_envelope where status='indexed' "
            "and extraction->>'company_name'=%s order by ingested_at desc limit 1", (co,)
        ).fetchone()
        n = r["n"] if r else None
        if not isinstance(n, dict):
            continue
        out.append(
            f"## {co}\nsector: {n.get('sector')} | stage: {n.get('stage')} | "
            f"ask ₹{n.get('ask_inr_cr')}cr | revenue ₹{n.get('revenue_inr_cr')}cr | "
            f"valuation ₹{n.get('valuation_inr_cr')}cr\n"
            f"business model: {n.get('business_model')}\n"
            f"summary: {n.get('summary')}\n"
            f"key metrics: {', '.join(n.get('key_metrics') or [])}\n"
            f"risks: {'; '.join(n.get('risks') or [])}")
    return "\n\n".join(out) or "(question doesn't name a known company)"


def retrieve(conn, question: str, k: int = TOP_K) -> list[dict]:
    qv = embed([question])[0]
    vstr = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
    return conn.execute(
        """select e.extraction->>'company_name' company, e.title, ch.text,
                  round((ch.embedding <=> %s::vector)::numeric, 3) dist
             from gb_chunk ch join gb_envelope e on e.id = ch.envelope_id
            where ch.embedding is not null and e.status='indexed'
            order by ch.embedding <=> %s::vector limit %s""",
        (vstr, vstr, k),
    ).fetchall()


def ask(question: str, k: int = TOP_K) -> dict:
    conn = connect()
    try:
        facts = deal_facts(conn)
        dos = dossier(conn, question)
        hits = retrieve(conn, question, k)
    finally:
        conn.close()  # one-shot per request — don't leak under the long-lived server
    chunks = "\n\n".join(
        f"[{h['company'] or '?'} — {(h['title'] or '').replace(chr(10),' ')[:60]}]\n"
        f"{(h['text'] or '').strip()[:MAX_CHUNK_CHARS]}" for h in hits
    ) or "(no matching excerpts)"
    answer = generate_text(PROMPT.format(q=question, dossier=dos, facts=facts, chunks=chunks))
    # de-duplicated source list, best match first
    seen, sources = set(), []
    for h in hits:
        key = (h["company"], h["title"])
        if key not in seen:
            seen.add(key)
            sources.append({"company": h["company"], "title": h["title"], "dist": float(h["dist"])})
    return {"answer": answer, "sources": sources}


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('usage: python -m workers.ask "your question"')
        sys.exit(1)
    res = ask(question)
    print("\n" + res["answer"] + "\n")
    print("— sources —")
    for s in res["sources"]:
        print(f"  · {s['company'] or '?'} — {(s['title'] or '')[:60]}  (dist {s['dist']})")


if __name__ == "__main__":
    main()
