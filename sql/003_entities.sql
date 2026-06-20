-- ============================================================
-- gbrain · 003 · Typed knowledge layer (all sources feed this)
-- The ingestion core (001) is source-agnostic: WhatsApp, Gmail,
-- Calendar, Drive, PDF, dashboard all land as gb_envelope rows.
-- This migration adds the *knowledge* model they populate — the
-- Company/Person/Investor/Deal/Meeting/Document entities, the
-- temporal financial store, and follow-up tasks — grounded in the
-- Second Brain Blueprint's note templates.
-- Idempotent. Run after 001 + 002.
-- ============================================================

-- ── deterministic-match index on entity keys (Phase 4) ──────
--   keys jsonb holds {phone, email, domain, deal_id, gstin, cin, …}
--   used to resolve fuzzy mentions from any source to one entity.
create index if not exists gb_entity_keys_idx on gb_entity using gin (keys);
create index if not exists gb_entity_type_idx on gb_entity (type);
create index if not exists gb_edge_dst_idx    on gb_edge (dst, rel);
create index if not exists gb_edge_env_idx     on gb_edge (envelope_id);

-- ── edge relationship vocabulary (documented, not hard-locked) ─
--   gb_edge.rel is free text so Phase 4+ can extend without a
--   migration. Canonical set:
--     works_at · founded · deal_owner_of · on_deal_team · involves
--     mentions · attended · organized · sent_by · sent_to
--     invested_in · shown_to · about · attached_to · follows_up
--     competitor_of · related_to
-- ============================================================

-- ── ENTITY ATTR CONTRACTS (gb_entity.attrs jsonb per type) ──
-- gb_entity stays ONE table (deterministic resolution target).
-- attrs shape per type, surfaced by the views below:
--
-- company : { sector, sub_sector, tagline, founding_year, hq, url,
--             founders[], business_model, stage, poc, fitment,
--             has_deal, deal_owner, deal_team[], priority,
--             next_follow_up, revenue_inr_cr, revenue_period,
--             revenue_source, revenue_as_of, ebitda_inr_cr,
--             ebitda_period, valuation_inr_cr, total_funding_inr_cr,
--             employee_count, enrichment_as_of }
-- person  : { role, title, company, email, phone, linkedin, is_internal }
-- investor: { investor_type, aum_inr_cr, stage_focus[], sector_focus[],
--             ticket_size_inr_cr, portfolio[], website }
-- deal     : { company, stage, deal_owner, deal_team[], round_type,
--             ask_inr_cr, valuation_inr_cr, investors_shown[],
--             priority, next_follow_up, status }
-- meeting : { event_type, occurred_at, meeting_link, organizer,
--             attendees_internal[], attendees_external[], company,
--             status, calendar_id, recurrence_id, source_event_id }
-- document: { doc_type, file_type, company, source_url, storage_ref,
--             confidentiality, pages, doc_date }

-- ── typed VIEWS over gb_entity (CRM-style queryability) ─────

create or replace view gb_company as
select id,
       canonical                                   as name,
       attrs->>'sector'                            as sector,
       attrs->>'stage'                             as stage,
       attrs->>'poc'                               as poc,
       attrs->>'fitment'                           as fitment,
       coalesce((attrs->>'has_deal')::boolean,false) as has_deal,
       attrs->>'deal_owner'                        as deal_owner,
       attrs->'deal_team'                          as deal_team,
       attrs->>'priority'                          as priority,
       (attrs->>'next_follow_up')::date            as next_follow_up,
       attrs->>'hq'                                as hq,
       (attrs->>'founding_year')::int              as founding_year,
       attrs->>'url'                               as url,
       (attrs->>'revenue_inr_cr')::numeric         as revenue_inr_cr,
       attrs->>'revenue_period'                    as revenue_period,
       attrs->>'revenue_source'                    as revenue_source,
       (attrs->>'ebitda_inr_cr')::numeric          as ebitda_inr_cr,
       (attrs->>'valuation_inr_cr')::numeric       as valuation_inr_cr,
       (attrs->>'total_funding_inr_cr')::numeric   as total_funding_inr_cr,
       (attrs->>'employee_count')::int             as employee_count,
       keys, attrs
from gb_entity where type = 'company';

create or replace view gb_person as
select id,
       canonical                  as name,
       attrs->>'role'             as role,
       attrs->>'title'            as title,
       attrs->>'company'          as company,
       attrs->>'email'            as email,
       attrs->>'phone'            as phone,
       attrs->>'linkedin'         as linkedin,
       coalesce((attrs->>'is_internal')::boolean,false) as is_internal,
       keys, attrs
from gb_entity where type = 'person';

create or replace view gb_investor as
select id,
       canonical                          as name,
       attrs->>'investor_type'            as investor_type,
       (attrs->>'aum_inr_cr')::numeric    as aum_inr_cr,
       attrs->'stage_focus'               as stage_focus,
       attrs->'sector_focus'              as sector_focus,
       attrs->'portfolio'                 as portfolio,
       attrs->>'website'                  as website,
       keys, attrs
from gb_entity where type = 'investor';

create or replace view gb_deal as
select id,
       canonical                          as name,
       attrs->>'company'                  as company,
       attrs->>'stage'                    as stage,
       attrs->>'deal_owner'               as deal_owner,
       attrs->'deal_team'                 as deal_team,
       attrs->>'round_type'               as round_type,
       (attrs->>'ask_inr_cr')::numeric    as ask_inr_cr,
       (attrs->>'valuation_inr_cr')::numeric as valuation_inr_cr,
       attrs->'investors_shown'           as investors_shown,
       attrs->>'priority'                 as priority,
       (attrs->>'next_follow_up')::date   as next_follow_up,
       attrs->>'status'                   as status,
       keys, attrs
from gb_entity where type = 'deal';

create or replace view gb_meeting as
select id,
       canonical                          as title,
       attrs->>'event_type'               as event_type,
       (attrs->>'occurred_at')::timestamptz as occurred_at,
       attrs->>'company'                  as company,
       attrs->>'organizer'                as organizer,
       attrs->'attendees_internal'        as attendees_internal,
       attrs->'attendees_external'        as attendees_external,
       attrs->>'meeting_link'             as meeting_link,
       attrs->>'status'                   as status,
       keys, attrs
from gb_entity where type = 'meeting';

create or replace view gb_document as
select id,
       canonical                  as title,
       attrs->>'doc_type'         as doc_type,
       attrs->>'file_type'        as file_type,
       attrs->>'company'          as company,
       attrs->>'source_url'       as source_url,
       attrs->>'confidentiality'  as confidentiality,
       (attrs->>'doc_date')::date as doc_date,
       keys, attrs
from gb_entity where type = 'document';

-- ── FINANCIAL OBSERVATIONS (temporal, provenance + confidence) ─
--   Blueprint Part 11: revenue/EBITDA/valuation are time-series with
--   source + as_of + confidence. Frontmatter shows the most-recent
--   HIGH-confidence value; history is preserved here.
create table if not exists gb_observation (
  id           uuid primary key default gen_random_uuid(),
  entity_id    uuid references gb_entity(id),   -- usually a company
  metric       text not null,                   -- revenue|ebitda|valuation|funding|employees|margin…
  value_num    numeric,                         -- standardized numeric (e.g. INR Cr)
  unit         text default 'INR_Cr',
  value_text   text,                            -- raw as stated, if non-numeric
  period       text,                            -- "FY27", "Q1FY27", "TTM"
  as_of        date,                            -- when this figure was reported/observed
  source       text,                            -- Founder call|Tracxn|MCA|Crunchbase|PitchBook|News
  confidence   text,                            -- High|Medium|Low|Verified
  envelope_id  uuid references gb_envelope(id), -- provenance: which ingested item
  created_at   timestamptz default now()
);
create index if not exists gb_obs_entity_idx on gb_observation (entity_id, metric, as_of desc);

-- most-recent High/Verified value per (entity, metric) — drives "current" figures
create or replace view gb_observation_latest as
select distinct on (entity_id, metric)
       entity_id, metric, value_num, unit, period, as_of, source, confidence
from gb_observation
where confidence in ('High','Verified')
order by entity_id, metric, as_of desc nulls last;

-- ── TASKS / FOLLOW-UPS (action items from any source) ───────
create table if not exists gb_task (
  id            uuid primary key default gen_random_uuid(),
  description   text not null,
  owner         text,                           -- Dexter team member
  due_date      date,
  status        text not null default 'open',   -- open|in_progress|done|cancelled
  priority      text,                            -- High|Mid|Low
  company_id    uuid references gb_entity(id),
  deal_id       uuid references gb_entity(id),
  envelope_id   uuid references gb_envelope(id), -- where it was extracted from
  created_at    timestamptz default now(),
  constraint gb_task_status_chk check (status in ('open','in_progress','done','cancelled'))
);
create index if not exists gb_task_owner_idx  on gb_task (owner, status);
create index if not exists gb_task_due_idx    on gb_task (due_date) where status <> 'done';

-- ── lock new tables out of the public API ───────────────────
alter table gb_observation enable row level security;
alter table gb_task        enable row level security;

-- ── a CRM-style pipeline view (blueprint Deal Pipeline.base) ─
create or replace view gb_pipeline as
select c.name, c.sector, c.stage, c.poc, c.fitment, c.deal_owner,
       c.next_follow_up, c.priority,
       l.value_num as revenue_inr_cr, l.period as revenue_period
from gb_company c
left join gb_observation_latest l
       on l.entity_id = c.id and l.metric = 'revenue'
where c.has_deal
order by c.next_follow_up nulls last;
