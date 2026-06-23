import { q } from "./db";
import type {
  Company, Stats, EmailRow, Person, PersonFull, CompanyProfile, OrgPerson,
  PipelineDeal, FinPoint, Inbox, Task,
} from "./types";
import { PIPELINE_STAGES } from "./types";

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

// ── pipeline (Kanban) ────────────────────────────────────────
export const getPipeline = () =>
  safe(q<PipelineDeal>(
    `select company, entity_id, pipeline_stage, owner, sector, round_stage, round_type,
            ask_inr_cr, valuation_inr_cr, revenue_inr_cr, poc, fitment, last_interaction, has_deal
       from gb_deal_pipeline
      order by ask_inr_cr desc nulls last, company`), [], "getPipeline");

// move a deal to a stage (writes attrs.pipeline_stage on the company entity).
export async function setDealStage(entityId: string, stage: string): Promise<boolean> {
  if (!(PIPELINE_STAGES as readonly string[]).includes(stage)) return false;
  try {
    await q("update gb_entity set attrs = attrs || jsonb_build_object('pipeline_stage', $1::text) where id = $2 and type='company'", [stage, entityId]);
    return true;
  } catch (e) { console.error("[data] setDealStage", e); return false; }
}

export async function setDealOwner(entityId: string, owner: string): Promise<boolean> {
  try {
    await q("update gb_entity set attrs = attrs || jsonb_build_object('deal_owner', $1::text) where id = $2 and type='company'", [owner, entityId]);
    return true;
  } catch (e) { console.error("[data] setDealOwner", e); return false; }
}

// ── financial trends ─────────────────────────────────────────
export const getCompanyFinancials = (name: string) =>
  safe(q<FinPoint>(
    `select metric, value_num, period, as_of, created_at
       from gb_company_financials where company = $1
      order by metric, coalesce(as_of, created_at::date), created_at`, [name]), [], "getCompanyFinancials");

// ── inbox (follow-ups, new deals, quiet, fresh financials) ───
export const getInbox = (): Promise<Inbox> => safe((async () => {
  const [tasks, newDeals, quiet, freshFinancials] = await Promise.all([
    q<Task>(`select id, description, owner, due_date, priority, company, company_id, overdue
               from gb_open_tasks order by overdue desc, due_date asc nulls last, created_at desc limit 50`),
    q<{ company: string; sector: string | null; ask_inr_cr: string | null; seen: string }>(
      `with firstseen as (
         select extraction->>'company_name' company, min(occurred_at) seen
           from gb_envelope where status='indexed' and coalesce(extraction->>'company_name','')<>''
          group by 1)
       select c.company, c.sector, c.ask_inr_cr, f.seen
         from gb_company_card c join firstseen f on f.company = c.company
        where f.seen >= now() - interval '7 days' order by f.seen desc limit 25`),
    q<{ company: string; sector: string | null; last_interaction: string | null }>(
      `select company, sector, last_interaction from gb_company_card
        where has_deal and last_interaction is not null
          and last_interaction < current_date - interval '21 days'
        order by last_interaction asc limit 20`),
    q<{ company: string; metric: string; value_num: string | null; period: string | null; as_of: string | null }>(
      `select company, metric, value_num, period, as_of from gb_company_financials
        where created_at >= now() - interval '7 days'
        order by created_at desc limit 25`),
  ]);
  return { tasks, newDeals, quiet, freshFinancials };
})(), { tasks: [], newDeals: [], quiet: [], freshFinancials: [] }, "getInbox");

export async function markTaskDone(id: string): Promise<boolean> {
  try { await q("update gb_task set status='done' where id = $1", [id]); return true; }
  catch (e) { console.error("[data] markTaskDone", e); return false; }
}

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
    `select e.canonical as person, e.id as entity_id,
            max(coalesce(other.props->>'title', p.current_title, e.attrs->>'role')) as role,
            max(e.attrs->>'headline') as headline,
            max(coalesce(p.linkedin_url, e.attrs->>'linkedin')) as linkedin,
            max(p.photo_url) as photo_url,
            bool_or(p.person_id is not null) as has_profile,
            bool_or(coalesce((me.props->>'current')::bool, true)
                    and coalesce((other.props->>'current')::bool, true)) as current,
            max(d.canonical) as company
       from gb_edge me
       join gb_edge other on other.dst = me.dst and other.rel = 'works_at'
       join gb_entity d on d.id = me.dst and d.type = 'company'
       join gb_entity e on e.id = other.src and e.type = 'person'
       left join gb_person_profile p on p.person_id = e.id
      where me.src = $1 and me.rel = 'works_at' and other.src <> $1
        and ${NOT_PLACEHOLDER}
      group by e.id, e.canonical
      order by current desc, has_profile desc, person limit 60`, [id]
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
     select e.canonical as person, e.id as entity_id,
            max(coalesce(ed.props->>'title', p.current_title, e.attrs->>'role')) as role,
            max(e.attrs->>'headline') as headline,
            max(coalesce(p.linkedin_url, e.attrs->>'linkedin')) as linkedin,
            max(p.photo_url) as photo_url,
            bool_or(p.person_id is not null) as has_profile,
            bool_or(coalesce((ed.props->>'current')::bool, true)) as current,
            max(nullif(concat_ws(' – ', ed.props->>'start', ed.props->>'end'), '')) as tenure
       from gb_edge ed
       join cluster cl on cl.id = ed.dst
       join gb_entity e on e.id = ed.src and e.type='person'
       left join gb_person_profile p on p.person_id = e.id
      where ed.rel = 'works_at' and ${NOT_PLACEHOLDER}
      group by e.id, e.canonical
      order by current desc, has_profile desc, person`, [name]
  ), [], "getCompanyPeople");
