-- ============================================================
-- gbrain · 017 · company statutory documents (Tracxn/MCA filings)
-- One row per MATERIAL filing (financials / annual return / charge / allotment /
-- valuation / deposits) linked to its company via the document→company 'about'
-- edge. Administrative churn is filtered at load (load_tracxn._doc_kind), and this
-- view keeps only Tracxn filings (attrs has 'filing_kind'), excluding the email/
-- deck document nodes the pipeline already creates. The PDF is resolved on demand
-- (tracxn.resolve) — we store the durable viewer url only.
-- Idempotent. Append-only.
-- ============================================================
create or replace view gb_company_documents as
select co.canonical                          as company,
       co.id                                 as company_id,
       d.id                                  as document_id,
       d.attrs->>'filing_kind'               as kind,
       d.attrs->>'doc_type'                  as doc_type,
       split_part(d.canonical, ' — ', 2)     as title,
       (d.attrs->>'doc_date')                as filing_date,
       d.attrs->>'source_url'                as url,
       d.attrs->>'registrar'                 as registrar,
       d.keys->>'tracxn_doc_id'              as tracxn_doc_id
from gb_edge ed
join gb_entity d  on d.id = ed.src and d.type = 'document' and d.attrs ? 'filing_kind'
join gb_entity co on co.id = ed.dst and co.type = 'company'
where ed.rel = 'about';
