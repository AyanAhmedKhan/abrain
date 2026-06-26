-- ============================================================
-- gbrain · 016 · financial provenance tracks (Management vs Verified)
-- Two-track model so founder/deck numbers and Tracxn/MCA filings are shown
-- SIDE BY SIDE, never merged into one ambiguous "current" figure:
--   management = founder call / pitch deck observations (confidence High|Medium)
--   verified   = Tracxn / MCA statutory filings        (confidence Verified)
-- Both surfaces (dashboard + Obsidian) read these views. Nothing is overwritten;
-- every figure stays a gb_observation row with source + as_of + confidence.
-- Idempotent (create or replace / new view). Append-only — never edit a shipped one.
-- ============================================================

-- trends feed + provenance: every observation, tagged with its track.
create or replace view gb_company_financials as
select en.canonical             as company,
       en.id                    as entity_id,
       o.metric, o.value_num, o.unit, o.period, o.as_of, o.created_at,
       o.envelope_id, o.source, o.confidence,
       case when o.confidence = 'Verified'
              or o.source ilike 'tracxn%' or o.source ilike 'mca%'
            then 'verified' else 'management' end as track
from gb_observation o
join gb_entity en on en.id = o.entity_id and en.type = 'company'
where o.value_num is not null;

-- latest value per (company, metric, TRACK): exactly one Management and one
-- Verified figure per metric, resolved by most-recent as_of then confidence.
-- Drives the two-track panels on the company page and Obsidian frontmatter/table.
create or replace view gb_company_financials_latest as
select distinct on (entity_id, metric, track)
       company, entity_id, metric, track,
       value_num, unit, period, as_of, source, confidence, created_at
from gb_company_financials
order by entity_id, metric, track,
         as_of desc nulls last,
         case confidence when 'Verified' then 4 when 'High' then 3
                         when 'Medium' then 2 else 1 end desc,
         created_at desc;
