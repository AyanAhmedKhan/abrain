import { q } from "./db";
import type { Company, Stats, EmailRow, Person, PersonFull, CompanyProfile, OrgPerson } from "./types";

export * from "./types"; // re-export types + inr for server pages

const CARD_COLS = `company, sector, sub_sector, stage, round_type, poc, fitment, hq,
  website, founded, ask_inr_cr, valuation_inr_cr, revenue_inr_cr, revenue_period,
  ebitda_inr_cr, has_deal, business_model, summary, risks, key_metrics, founders,
  existing_investors, referred_by, aliases, note_count, last_interaction`;

// exclude placeholder "person" entities (role/section labels the pipeline created,
// e.g. "Active US Founder", "CEO-Founder", "HR Operations") from people listings.
const NOT_PLACEHOLDER =
  `e.canonical !~* '\\y(founder|co-?founder|ceo|cfo|cto|coo|cmo|cxo|chairman|investor|advisor|partner|principal|associate|analyst|team|deals?|mentions?|unknown|active|dormant|hr|hrops|operations|finance|sales|marketing|admin|accounts?|legal|promoters?)\\y'`;

// All getters fail soft: a transient DB error returns a safe fallback (null/[])
// so the page renders a graceful "no data" state instead of a 500. (app/error.tsx
// remains the backstop for anything unexpected.)
async function safe<T>(p: Promise<T>, fallback: T, label: string): Promise<T> {
  try {
    return await p;
  } catch (e) {
    console.error(`[data] ${label} failed:`, e);
    return fallback;
  }
}

export const getStats = () =>
  safe(q<Stats>("select * from gb_dashboard_stats").then((r) => r[0] ?? null), null, "getStats");

export const getCompanies = () =>
  safe(q<Company>(`select ${CARD_COLS} from gb_company_card order by last_interaction desc nulls last, company`), [], "getCompanies");

export const getDeals = () =>
  safe(q<Company>(`select ${CARD_COLS} from gb_deal_card order by ask_inr_cr desc nulls last`), [], "getDeals");

export const getCompany = (name: string) =>
  safe(q<Company>(`select ${CARD_COLS} from gb_company_card where company = $1`, [name]).then((r) => r[0] ?? null), null, "getCompany");

export const getCompanyProfile = (name: string) =>
  safe(q<CompanyProfile>(
    `select company, entity_id, linkedin_url, public_id, tagline, description,
            industry, company_size, employee_count, hq, founded, website, followers,
            specialties, logo_url, scraped_at
       from gb_company_full where company = $1`, [name]
  ).then((r) => r[0] ?? null), null, "getCompanyProfile");

export const getCompanyEmails = (name: string) =>
  safe(q<EmailRow>(
    `select date, source, title, company, summary, poc, fitment, from_actor
       from gb_email_log where company = $1 order by date desc nulls last`,
    [name],
  ), [], "getCompanyEmails");

export const getPeople = () =>
  safe(q<Person>(
    `select person, role, company, linkedin, email, headline, current_title,
            current_company, location, photo_url, followers, public_id,
            has_profile, entity_id
       from gb_person_card
      order by has_profile desc, followers desc nulls last, person`), [], "getPeople");

export const getPerson = (id: string) =>
  safe(q<PersonFull>(`select * from gb_person_full where entity_id = $1`, [id]).then((r) => r[0] ?? null), null, "getPerson");

// companies this person is linked to in the graph (works_at edges → company notes)
export const getPersonCompanies = (id: string) =>
  safe(q<{ company: string }>(
    `select d.canonical as company
       from gb_edge e join gb_entity d on d.id = e.dst
      where e.src = $1 and e.rel = 'works_at' order by d.canonical`, [id]
  ).then((r) => r.map((x) => x.company)), [], "getPersonCompanies");

// colleagues: people who share a works_at company with this person (graph join).
export const getColleagues = (id: string) =>
  safe(q<OrgPerson & { company: string }>(
    `select distinct e.canonical as person, e.id as entity_id,
            coalesce(p.current_title, e.attrs->>'role') as role,
            e.attrs->>'headline' as headline,
            coalesce(p.linkedin_url, e.attrs->>'linkedin') as linkedin,
            p.photo_url, (p.person_id is not null) as has_profile,
            d.canonical as company
       from gb_edge me
       join gb_edge other on other.dst = me.dst and other.rel = 'works_at'
       join gb_entity d on d.id = me.dst and d.type = 'company'
       join gb_entity e on e.id = other.src and e.type = 'person'
       left join gb_person_profile p on p.person_id = e.id
      where me.src = $1 and me.rel = 'works_at' and other.src <> $1
        and ${NOT_PLACEHOLDER}
      order by has_profile desc, person limit 60`, [id]
  ), [], "getColleagues");

// people who work at this org (LinkedIn works_at edges). Cluster-aware: also
// counts edges pointing at duplicate company nodes (shared website / mutual
// aliases) so all employees show even before any merge.
export const getCompanyPeople = (name: string) =>
  safe(q<OrgPerson>(
    `with target as (
       select id, attrs from gb_entity where type='company' and canonical = $1 limit 1
     ), cluster as (
       select e.id from gb_entity e, target t
        where e.type='company' and (
          e.id = t.id
          or e.canonical in (select jsonb_array_elements_text(coalesce(t.attrs->'aliases','[]'::jsonb)))
          or $1 in (select jsonb_array_elements_text(coalesce(e.attrs->'aliases','[]'::jsonb)))
          or (nullif(e.attrs->>'website','') is not null and e.attrs->>'website' = t.attrs->>'website')
        )
     )
     select distinct e.canonical as person, e.id as entity_id,
            coalesce(p.current_title, e.attrs->>'role') as role,
            e.attrs->>'headline' as headline,
            coalesce(p.linkedin_url, e.attrs->>'linkedin') as linkedin,
            p.photo_url, (p.person_id is not null) as has_profile
       from gb_edge ed
       join cluster cl on cl.id = ed.dst
       join gb_entity e on e.id = ed.src and e.type='person'
       left join gb_person_profile p on p.person_id = e.id
      where ed.rel = 'works_at' and ${NOT_PLACEHOLDER}
      order by has_profile desc, person`, [name]
  ), [], "getCompanyPeople");
