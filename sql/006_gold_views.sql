-- ============================================================
-- gbrain · 006 · Gold / dashboard views
-- Flatten the JSONB knowledge (gb_envelope.extraction + gb_entity.attrs
-- + gb_observation) into clean, columnar, one-row-per-thing views so a
-- web dashboard can `select *` without parsing JSON per row.
-- Idempotent (create or replace). Append-only — never edit a shipped one.
-- ============================================================

-- safe numeric cast (returns null instead of erroring on bad text)
create or replace function gb_num(t text)
returns numeric language plpgsql immutable as $$
begin
  return t::numeric;
exception when others then
  return null;
end $$;

-- ── one row per company (latest extraction merged with entity attrs + obs) ──
create or replace view gb_company_card as
with latest as (
  select distinct on (extraction->>'company_name')
         extraction->>'company_name' as company,
         extraction               as ex,
         occurred_at
  from gb_envelope
  where status='indexed' and coalesce(extraction->>'company_name','') <> ''
  order by extraction->>'company_name', occurred_at desc nulls last
),
agg as (
  select extraction->>'company_name' as company,
         count(*)        as note_count,
         max(occurred_at) as last_interaction
  from gb_envelope
  where status='indexed' and coalesce(extraction->>'company_name','') <> ''
  group by 1
),
obs as (
  select e.canonical as company,
         max(o.value_num) filter (where o.metric='revenue')     as revenue_inr_cr,
         max(o.value_num) filter (where o.metric='valuation')   as valuation_inr_cr,
         max(o.value_num) filter (where o.metric='funding_ask') as ask_inr_cr,
         max(o.value_num) filter (where o.metric='ebitda')      as ebitda_inr_cr
  from gb_observation o
  join gb_entity e on e.id=o.entity_id and e.type='company'
  group by 1
)
select
  l.company,
  coalesce(e.attrs->>'sector',     l.ex->>'sector')      as sector,
  coalesce(e.attrs->>'sub_sector', l.ex->>'sub_sector')  as sub_sector,
  coalesce(e.attrs->>'stage',      l.ex->>'stage')       as stage,
  l.ex->>'round_type'                                    as round_type,
  coalesce(e.attrs->>'poc',        l.ex->>'poc')         as poc,
  coalesce(e.attrs->>'fitment',    l.ex->>'fitment')     as fitment,
  coalesce(e.attrs->>'hq',         l.ex->>'hq')          as hq,
  coalesce(e.attrs->>'website',    l.ex->>'website')     as website,
  coalesce(e.attrs->>'founded',    l.ex->>'founded')     as founded,
  coalesce(gb_num(l.ex->>'ask_inr_cr'),        obs.ask_inr_cr)        as ask_inr_cr,
  coalesce(gb_num(l.ex->>'valuation_inr_cr'),  obs.valuation_inr_cr)  as valuation_inr_cr,
  coalesce(gb_num(l.ex->>'revenue_inr_cr'),    obs.revenue_inr_cr)    as revenue_inr_cr,
  l.ex->>'revenue_period'                                as revenue_period,
  coalesce(gb_num(l.ex->>'ebitda_inr_cr'),     obs.ebitda_inr_cr)     as ebitda_inr_cr,
  (gb_num(l.ex->>'ask_inr_cr') is not null
     or coalesce(l.ex->>'round_type','') <> '')          as has_deal,
  l.ex->>'business_model'                                as business_model,
  l.ex->>'summary'                                       as summary,
  l.ex->'risks'                                          as risks,
  l.ex->'key_metrics'                                    as key_metrics,
  l.ex->'founders'                                       as founders,
  l.ex->'existing_investors'                             as existing_investors,
  l.ex->>'referred_by'                                   as referred_by,
  coalesce(e.attrs->'aliases', l.ex->'aliases')          as aliases,
  agg.note_count,
  agg.last_interaction,
  e.id                                                   as entity_id
from latest l
left join gb_entity e on e.type='company' and e.canonical = l.company
left join agg on agg.company = l.company
left join obs on obs.company = l.company;

-- ── deals only (companies with a live ask / round) ──
create or replace view gb_deal_card as
select * from gb_company_card where has_deal;

-- ── one row per person ──
create or replace view gb_person_card as
select e.canonical               as person,
       e.attrs->>'role'          as role,
       e.attrs->>'company'       as company,
       e.attrs->>'linkedin'      as linkedin,
       e.keys->>'email'          as email,
       e.keys->>'phone'          as phone,
       e.id                      as entity_id
from gb_entity e
where e.type='person';

-- ── flat email / call-note log ──
create or replace view gb_email_log as
select to_char(occurred_at,'YYYY-MM-DD')  as date,
       occurred_at,
       source,
       title,
       extraction->>'company_name'        as company,
       extraction->>'summary'             as summary,
       extraction->>'poc'                 as poc,
       extraction->>'fitment'             as fitment,
       actors->>'from'                    as from_actor,
       id                                 as envelope_id
from gb_envelope
where source in ('gmail','pdf') and status='indexed'
order by occurred_at desc nulls last;

-- ── one-row dashboard summary ──
create or replace view gb_dashboard_stats as
select (select count(*) from gb_company_card)                          as companies,
       (select count(*) from gb_company_card where has_deal)           as deals,
       (select count(*) from gb_entity where type='person')            as people,
       (select count(*) from gb_envelope where status='indexed')       as indexed_notes,
       (select count(distinct sector) from gb_company_card
          where sector is not null)                                    as sectors,
       (select round(sum(coalesce(usd,0)),4) from gb_cost_log)         as llm_spend_usd;
