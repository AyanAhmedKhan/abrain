-- ============================================================
-- gbrain · 010 · rich company profiles (Apify LinkedIn company scraper)
-- Deterministic company storage (NO LLM). One row per company entity; full raw
-- JSON kept verbatim + flattened columns. Mirrors the person-profile design (009).
-- Company LinkedIn URLs are harvested FOR FREE from person experience entries
-- (companyLinkedinUrl / companyId) and stamped onto gb_entity.attrs.linkedin;
-- this table holds the full scraped company record. Idempotent.
-- ============================================================

create table if not exists gb_company_profile (
  company_id      uuid primary key references gb_entity(id) on delete cascade,
  linkedin_url    text,
  public_id       text,
  tagline         text,
  description     text,
  industry        text,
  company_size    text,
  employee_count  int,
  hq              text,
  founded         text,
  website         text,
  followers       int,
  specialties     text[],
  locations       jsonb,
  logo_url        text,
  raw             jsonb,
  scraped_at      timestamptz not null default now()
);
create index if not exists gb_cprofile_public_idx on gb_company_profile(public_id);
alter table gb_company_profile enable row level security;

-- async company-scrape queue (free harvest + enrich enqueue after finding a URL)
do $$ begin perform pgmq.create('gb_q_company'); exception when others then null; end $$;

-- full company profile (for the dashboard company detail page + Obsidian)
create or replace view gb_company_full as
select e.canonical as company, e.id as entity_id, cp.*
from gb_company_profile cp join gb_entity e on e.id = cp.company_id;
