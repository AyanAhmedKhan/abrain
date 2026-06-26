import { q } from "./db";
import type {
  Company, Stats, EmailRow, Person, PersonFull, CompanyProfile, OrgPerson,
  PipelineDeal, FinPoint, FinLatest, CompanyDoc, Inbox, Task, InvestorRow, CompanyInvestor, Bridge, IntroPaths,
  InvestorPortfolioRow, CoInvestor,
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
    `select date, source, title, company, summary, poc, fitment, from_actor,
            kind, deck_ref, source_url, envelope_id
       from gb_email_log where company = $1 order by date desc nulls last`,
    [name],
  ), [], "getCompanyEmails");

// ── investors & co-investment ────────────────────────────────
export const getInvestors = () =>
  safe(q<InvestorRow>(
    `select s.investor, s.investor_id, s.portfolio,
            (select string_agg(distinct cc.sector, ', ') from gb_investor_portfolio p
               join gb_company_card cc on cc.company = p.company
              where p.investor_id = s.investor_id and cc.sector is not null) as sectors,
            (select array_agg(p.company order by p.company) from gb_investor_portfolio p
              where p.investor_id = s.investor_id) as companies
       from gb_investor_stats s
      order by s.portfolio desc, s.investor`), [], "getInvestors");

// one investor's portfolio (companies we've seen them in) + co-investors
export const getInvestorPortfolio = (name: string) =>
  safe(q<InvestorPortfolioRow>(
    `select p.company, cc.sector, cc.stage, cc.ask_inr_cr, cc.last_interaction
       from gb_investor_portfolio p left join gb_company_card cc on cc.company = p.company
      where p.investor = $1
      order by cc.last_interaction desc nulls last, p.company`, [name]), [], "getInvestorPortfolio");

export const getCoinvestors = (name: string) =>
  safe(q<CoInvestor>(
    `select case when investor_a = $1 then investor_b else investor_a end as investor, shared
       from gb_coinvestors where investor_a = $1 or investor_b = $1
      order by shared desc, investor limit 40`, [name]), [], "getCoinvestors");

// investors of one company + how many other deals each is in
export const getCompanyInvestors = (name: string) =>
  safe(q<CompanyInvestor>(
    `select ci.investor, ci.investor_id, st.portfolio
       from gb_investor_portfolio ci join gb_investor_stats st on st.investor_id = ci.investor_id
      where ci.company = $1 order by st.portfolio desc, ci.investor`, [name]), [], "getCompanyInvestors");

// warm-intro paths to a company: referrer, shared-employer bridges (incl. past
// employers/orgs), classmate (shared-school) bridges, and its investors.
const _dexter = `exists(select 1 from gb_edge de join gb_entity dd on dd.id = de.dst
        where de.src = conn.id and de.rel='works_at' and dd.canonical='Dexter Capital') as is_dexter`;

export const getIntroPaths = async (name: string, referred_by: string | null): Promise<IntroPaths> => {
  const [bridges, classmates, investors] = await Promise.all([
    safe(q<Bridge>(
      `select distinct conn.canonical as connector, conn.id as connector_id,
              bridge.canonical as via_company, px.canonical as person, ${_dexter}
         from gb_edge ex
         join gb_entity tgt on tgt.id = ex.dst and tgt.type='company' and tgt.canonical = $1
         join gb_entity px on px.id = ex.src and px.type='person'
         join gb_edge eb on eb.src = px.id and eb.rel='works_at' and eb.dst <> ex.dst
         join gb_entity bridge on bridge.id = eb.dst and bridge.type in ('company','org')
         join gb_edge ec on ec.dst = eb.dst and ec.rel='works_at' and ec.src <> px.id
         join gb_entity conn on conn.id = ec.src and conn.type='person'
        where ex.rel='works_at'
          and not exists(select 1 from gb_edge xx where xx.src=conn.id and xx.rel='works_at' and xx.dst=tgt.id)
        order by is_dexter desc, connector limit 15`, [name]), [], "introBridges"),
    safe(q<Bridge>(
      `select distinct conn.canonical as connector, conn.id as connector_id,
              sch.canonical as via_company, px.canonical as person, ${_dexter}
         from gb_edge ex
         join gb_entity tgt on tgt.id = ex.dst and tgt.type='company' and tgt.canonical = $1
         join gb_entity px on px.id = ex.src and px.type='person'
         join gb_edge es on es.src = px.id and es.rel='studied_at'
         join gb_entity sch on sch.id = es.dst and sch.type='school'
         join gb_edge ec on ec.dst = es.dst and ec.rel='studied_at' and ec.src <> px.id
         join gb_entity conn on conn.id = ec.src and conn.type='person'
        where ex.rel='works_at'
          and not exists(select 1 from gb_edge xx where xx.src=conn.id and xx.rel='works_at' and xx.dst=tgt.id)
        order by is_dexter desc, connector limit 15`, [name]), [], "introClassmates"),
    getCompanyInvestors(name),
  ]);
  return { referred_by, bridges, classmates, investors };
};

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
    await q("update gb_entity set attrs = coalesce(attrs,'{}'::jsonb) || jsonb_build_object('pipeline_stage', $1::text) where id = $2 and type='company'", [stage, entityId]);
    return true;
  } catch (e) { console.error("[data] setDealStage", e); return false; }
}

export async function setDealOwner(entityId: string, owner: string): Promise<boolean> {
  try {
    await q("update gb_entity set attrs = coalesce(attrs,'{}'::jsonb) || jsonb_build_object('deal_owner', $1::text) where id = $2 and type='company'", [owner, entityId]);
    return true;
  } catch (e) { console.error("[data] setDealOwner", e); return false; }
}

// owner autocomplete: previously-used owners ∪ people linked to Dexter Capital
export const getOwnerSuggestions = () =>
  safe(q<{ o: string }>(
    `select distinct o from (
        select attrs->>'deal_owner' as o from gb_entity where type='company' and attrs ? 'deal_owner'
        union
        select s.canonical from gb_edge ed
          join gb_entity s on s.id=ed.src and s.type='person'
          join gb_entity d on d.id=ed.dst and d.type='company'
         where ed.rel='works_at' and d.canonical='Dexter Capital'
      ) x where coalesce(o,'')<>'' order by o`).then((r) => r.map((x) => x.o)), [], "getOwnerSuggestions");

// ── financial trends (per source/track) ──────────────────────
export const getCompanyFinancials = (name: string) =>
  safe(q<FinPoint>(
    `select metric, value_num, period, as_of, created_at, source, track
       from gb_company_financials where company = $1
      order by metric, track, coalesce(as_of, created_at::date), created_at`, [name]), [], "getCompanyFinancials");

// ── two-track latest: Management (founder/deck) vs Verified (Tracxn/MCA) ──
export const getCompanyFinancialsLatest = (name: string) =>
  safe(q<FinLatest>(
    `select metric, track, value_num, period, as_of, source, confidence
       from gb_company_financials_latest where company = $1
      order by metric, track`, [name]), [], "getCompanyFinancialsLatest");

// ── material MCA statutory filings (Tracxn) for a company ──
export const getCompanyDocuments = (name: string) =>
  safe(q<CompanyDoc>(
    `select kind, title, filing_date, url, doc_type, registrar
       from gb_company_documents where company = $1
      order by filing_date desc nulls last, kind`, [name]), [], "getCompanyDocuments");

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
