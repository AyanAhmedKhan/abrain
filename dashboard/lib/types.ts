// Client-safe types + formatters (NO server/db imports — safe for the browser bundle).

export type Company = {
  company: string;
  sector: string | null;
  sub_sector: string | null;
  stage: string | null;
  round_type: string | null;
  poc: string | null;
  fitment: string | null;
  hq: string | null;
  website: string | null;
  founded: string | null;
  ask_inr_cr: string | null;
  valuation_inr_cr: string | null;
  revenue_inr_cr: string | null;
  revenue_period: string | null;
  ebitda_inr_cr: string | null;
  has_deal: boolean;
  business_model: string | null;
  summary: string | null;
  risks: string[] | null;
  key_metrics: string[] | null;
  founders: { name?: string; role?: string; linkedin?: string }[] | null;
  existing_investors: string[] | null;
  referred_by: string | null;
  aliases: string[] | null;
  note_count: number;
  last_interaction: string | null;
};

export type Stats = {
  companies: number; deals: number; people: number;
  indexed_notes: number; sectors: number; llm_spend_usd: string | null;
};

export type EmailRow = {
  date: string | null; source: string; title: string | null;
  company: string | null; summary: string | null;
  poc: string | null; fitment: string | null; from_actor: string | null;
};

export type Person = {
  person: string; role: string | null; company: string | null;
  linkedin: string | null; email: string | null;
  headline: string | null; current_title: string | null; current_company: string | null;
  location: string | null; photo_url: string | null; followers: number | null;
  public_id: string | null; has_profile: boolean; entity_id: string;
};

// One LinkedIn experience / education / cert / honor / project row (Apify, JSONB).
export type Job = {
  position?: string; companyName?: string; location?: string; employmentType?: string;
  workplaceType?: string; duration?: string; description?: string; start?: string; end?: string;
};
export type Edu = {
  schoolName?: string; degree?: string; fieldOfStudy?: string; period?: string; insights?: string;
};
export type Cert = { title?: string; issuedBy?: string; issuedAt?: string; link?: string };
export type Honor = { title?: string; issuedBy?: string; issuedAt?: string; description?: string };
export type Project = { title?: string; description?: string };

export type PersonFull = {
  person: string; entity_id: string; linkedin_url: string | null; public_id: string | null;
  headline: string | null; about: string | null; location_city: string | null;
  location_country: string | null; current_title: string | null; current_company: string | null;
  photo_url: string | null; followers: number | null; connections: number | null;
  skills: string[] | null; experience: Job[] | null; education: Edu[] | null;
  certifications: Cert[] | null; honors: Honor[] | null; projects: Project[] | null;
  scraped_at: string | null;
};

export const inr = (v: string | number | null): string => {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(n)) return "—";
  return `₹${n % 1 === 0 ? n : n.toFixed(2)} Cr`;
};
