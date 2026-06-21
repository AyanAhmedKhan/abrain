import { q } from "./db";
import type { Company, Stats, EmailRow, Person, PersonFull } from "./types";

export * from "./types"; // re-export types + inr for server pages

const CARD_COLS = `company, sector, sub_sector, stage, round_type, poc, fitment, hq,
  website, founded, ask_inr_cr, valuation_inr_cr, revenue_inr_cr, revenue_period,
  ebitda_inr_cr, has_deal, business_model, summary, risks, key_metrics, founders,
  existing_investors, referred_by, aliases, note_count, last_interaction`;

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
