-- ============================================================
-- gbrain · 009 · rich person profiles (Apify LinkedIn scraper)
-- Deterministic profile storage (NO LLM). One row per person; full raw
-- JSON kept verbatim + flattened columns + nested arrays as JSONB.
-- Idempotent.
-- ============================================================

create table if not exists gb_person_profile (
  person_id        uuid primary key references gb_entity(id) on delete cascade,
  linkedin_url     text,
  public_id        text,
  headline         text,
  about            text,
  location_city    text,
  location_country text,
  current_title    text,
  current_company  text,
  current_company_id text,
  photo_url        text,
  followers        int,
  connections      int,
  skills           text[],
  experience       jsonb,
  education        jsonb,
  certifications   jsonb,
  honors           jsonb,
  projects         jsonb,
  raw              jsonb,
  scraped_at       timestamptz not null default now()
);
create index if not exists gb_pprofile_company_idx on gb_person_profile(current_company);
create index if not exists gb_pprofile_public_idx  on gb_person_profile(public_id);
alter table gb_person_profile enable row level security;

-- async profile-scrape queue (enrich enqueues after it finds a LinkedIn URL)
do $$ begin perform pgmq.create('gb_q_profile'); exception when others then null; end $$;

-- person card enriched with profile fields (drop+recreate: column set changes)
drop view if exists gb_person_card;
create view gb_person_card as
select e.canonical                              as person,
       e.attrs->>'role'                         as role,
       e.attrs->>'company'                      as company,
       coalesce(p.linkedin_url, e.attrs->>'linkedin') as linkedin,
       e.keys->>'email'                         as email,
       e.keys->>'phone'                         as phone,
       p.headline,
       p.current_title,
       p.current_company,
       nullif(concat_ws(', ', p.location_city, p.location_country), '') as location,
       p.photo_url,
       p.followers,
       p.public_id,
       (p.person_id is not null)                as has_profile,
       e.id                                     as entity_id
from gb_entity e
left join gb_person_profile p on p.person_id = e.id
where e.type='person';

-- full profile (for the dashboard person detail page)
create or replace view gb_person_full as
select e.canonical as person, e.id as entity_id, p.*
from gb_person_profile p join gb_entity e on e.id = p.person_id;
