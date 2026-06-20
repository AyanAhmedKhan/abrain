-- ============================================================
-- gbrain · 007 · Canonical sectors in the dashboard layer
-- Mirrors workers/lib/taxonomy.canon_sector so gb_company_card.sector is
-- the canonical name (raw kept as sector_raw). Idempotent.
-- ============================================================

create or replace function gb_canon_sector(s text)
returns text language sql immutable as $$
  select case lower(trim(coalesce(s,'')))
    when '' then null
    -- canonical self-maps (case-insensitive parity with taxonomy.canon_sector)
    when 'adtech' then 'AdTech' when 'b2b' then 'B2B'
    when 'beauty & personal care' then 'Beauty & Personal Care'
    when 'climate' then 'Climate' when 'consumer' then 'Consumer'
    when 'consumer tech' then 'Consumer Tech' when 'deep tech' then 'Deep Tech'
    when 'defence' then 'Defence' when 'e-commerce' then 'E-commerce'
    when 'fintech' then 'Fintech' when 'food' then 'Food'
    when 'healthcare' then 'Healthcare' when 'logistics' then 'Logistics'
    when 'manufacturing' then 'Manufacturing' when 'media' then 'Media'
    when 'real estate' then 'Real Estate' when 'saas' then 'SaaS'
    when 'services' then 'Services' when 'venture capital' then 'Venture Capital'
    when 'private equity' then 'Private Equity' when 'venture debt' then 'Venture Debt'
    when 'asset management' then 'Asset Management'
    when 'advertising' then 'AdTech' when 'marketing tech' then 'AdTech' when 'martech' then 'AdTech'
    when 'b2b commerce' then 'B2B' when 'b2b marketplace' then 'B2B' when 'b2b services' then 'B2B'
    when 'beauty' then 'Beauty & Personal Care' when 'personal care' then 'Beauty & Personal Care'
    when 'cleantech' then 'Climate' when 'clean tech' then 'Climate' when 'sustainability' then 'Climate'
      when 'carbon markets' then 'Climate' when 'climate tech' then 'Climate'
    when 'consumer brands' then 'Consumer' when 'fmcg' then 'Consumer' when 'cpg' then 'Consumer'
    when 'consumer internet' then 'Consumer Tech' when 'consumer technology' then 'Consumer Tech'
    when 'deeptech' then 'Deep Tech'
    when 'defence tech' then 'Defence' when 'defense' then 'Defence' when 'defense tech' then 'Defence'
    when 'marketplace' then 'E-commerce' when 'ecommerce' then 'E-commerce' when 'e commerce' then 'E-commerce'
    when 'financial services' then 'Fintech' when 'banking' then 'Fintech' when 'nbfc' then 'Fintech'
      when 'financial' then 'Fintech' when 'finance' then 'Fintech'
    when 'f&b' then 'Food' when 'food & beverage' then 'Food' when 'food and beverage' then 'Food'
      when 'beverages' then 'Food' when 'foodtech' then 'Food'
    when 'health & wellness' then 'Healthcare' when 'health and wellness' then 'Healthcare'
      when 'hospitals' then 'Healthcare' when 'health' then 'Healthcare'
      when 'healthtech' then 'Healthcare' when 'health tech' then 'Healthcare'
    when 'supply chain' then 'Logistics'
      when 'logistics & mobility' then 'Logistics' when 'logistics and mobility' then 'Logistics'
    when 'vc' then 'Venture Capital'
    when 'pe' then 'Private Equity'
    when 'venture debt' then 'Venture Debt' when 'private credit' then 'Venture Debt'
    when 'asset management' then 'Asset Management' when 'am' then 'Asset Management'
    when 'industrial' then 'Manufacturing' when 'engineering services' then 'Manufacturing'
      when 'industrials' then 'Manufacturing'
    when 'entertainment' then 'Media' when 'media & entertainment' then 'Media'
    when 'proptech' then 'Real Estate' when 'prop tech' then 'Real Estate' when 'real-estate' then 'Real Estate'
    when 'software' then 'SaaS' when 'enterprise software' then 'SaaS'
      when 'enterprise tech' then 'SaaS' when 'enterprise technology' then 'SaaS'
    when 'it services' then 'Services' when 'professional services' then 'Services'
    else trim(s)
  end
$$;

-- recreate the company card with canonical sector (+ raw kept).
-- drop dependents first (column order changes; create-or-replace can't reorder).
drop view if exists gb_dashboard_stats;
drop view if exists gb_deal_card;
drop view if exists gb_company_card;
create view gb_company_card as
with latest as (
  select distinct on (extraction->>'company_name')
         extraction->>'company_name' as company, extraction as ex, occurred_at
  from gb_envelope
  where status='indexed' and coalesce(extraction->>'company_name','') <> ''
  order by extraction->>'company_name', occurred_at desc nulls last
),
agg as (
  select extraction->>'company_name' as company, count(*) as note_count,
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
  from gb_observation o join gb_entity e on e.id=o.entity_id and e.type='company'
  group by 1
)
select
  l.company,
  gb_canon_sector(coalesce(e.attrs->>'sector', l.ex->>'sector'))     as sector,
  coalesce(e.attrs->>'sector', l.ex->>'sector')                      as sector_raw,
  coalesce(e.attrs->>'sub_sector', l.ex->>'sub_sector')             as sub_sector,
  coalesce(e.attrs->>'stage',  l.ex->>'stage')                      as stage,
  l.ex->>'round_type'                                               as round_type,
  coalesce(e.attrs->>'poc',     l.ex->>'poc')                       as poc,
  coalesce(e.attrs->>'fitment', l.ex->>'fitment')                   as fitment,
  coalesce(e.attrs->>'hq',      l.ex->>'hq')                        as hq,
  coalesce(e.attrs->>'website', l.ex->>'website')                  as website,
  coalesce(e.attrs->>'founded', l.ex->>'founded')                  as founded,
  coalesce(gb_num(l.ex->>'ask_inr_cr'),       obs.ask_inr_cr)       as ask_inr_cr,
  coalesce(gb_num(l.ex->>'valuation_inr_cr'), obs.valuation_inr_cr) as valuation_inr_cr,
  coalesce(gb_num(l.ex->>'revenue_inr_cr'),   obs.revenue_inr_cr)   as revenue_inr_cr,
  l.ex->>'revenue_period'                                          as revenue_period,
  coalesce(gb_num(l.ex->>'ebitda_inr_cr'),    obs.ebitda_inr_cr)    as ebitda_inr_cr,
  (gb_num(l.ex->>'ask_inr_cr') is not null
     or coalesce(l.ex->>'round_type','') <> '')                    as has_deal,
  l.ex->>'business_model'                                          as business_model,
  l.ex->>'summary'                                                 as summary,
  l.ex->'risks'                                                    as risks,
  l.ex->'key_metrics'                                              as key_metrics,
  l.ex->'founders'                                                 as founders,
  l.ex->'existing_investors'                                       as existing_investors,
  l.ex->>'referred_by'                                             as referred_by,
  coalesce(e.attrs->'aliases', l.ex->'aliases')                    as aliases,
  agg.note_count, agg.last_interaction, e.id as entity_id
from latest l
left join gb_entity e on e.type='company' and e.canonical = l.company
left join agg on agg.company = l.company
left join obs on obs.company = l.company;

-- recreate deals view on top of the new card
create view gb_deal_card as select * from gb_company_card where has_deal;

-- recreate dashboard stats on top of the new card
create view gb_dashboard_stats as
select (select count(*) from gb_company_card)                          as companies,
       (select count(*) from gb_company_card where has_deal)           as deals,
       (select count(*) from gb_entity where type='person')            as people,
       (select count(*) from gb_envelope where status='indexed')       as indexed_notes,
       (select count(distinct sector) from gb_company_card
          where sector is not null)                                    as sectors,
       (select round(sum(coalesce(usd,0)),4) from gb_cost_log)         as llm_spend_usd;
