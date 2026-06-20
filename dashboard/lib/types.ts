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
};

export const inr = (v: string | number | null): string => {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(n)) return "—";
  return `₹${n % 1 === 0 ? n : n.toFixed(2)} Cr`;
};
