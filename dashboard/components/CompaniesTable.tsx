"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { type Company, inr } from "@/lib/types";
import { Badge } from "./ui";

type SortKey = "company" | "sector" | "stage" | "ask_inr_cr" | "valuation_inr_cr" | "revenue_inr_cr" | "last_interaction";

const num = (v: string | null) => (v === null || v === "" ? -Infinity : parseFloat(v));

const selectCls =
  "px-2.5 py-2 rounded-lg border border-line bg-panel text-sm text-ink outline-none transition-colors hover:border-accent/40 focus:border-accent focus:ring-2 focus:ring-accent/15";

export default function CompaniesTable({ companies }: { companies: Company[] }) {
  const [search, setSearch] = useState("");
  const [sector, setSector] = useState("");
  const [stage, setStage] = useState("");
  const [poc, setPoc] = useState("");
  const [dealsOnly, setDealsOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("last_interaction");
  const [asc, setAsc] = useState(false);

  const sectors = useMemo(() => [...new Set(companies.map((c) => c.sector).filter(Boolean))].sort() as string[], [companies]);
  const stages = useMemo(() => [...new Set(companies.map((c) => c.stage).filter(Boolean))].sort() as string[], [companies]);

  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    let out = companies.filter((c) => {
      if (sector && c.sector !== sector) return false;
      if (stage && c.stage !== stage) return false;
      if (poc && (c.poc || "") !== poc) return false;
      if (dealsOnly && !c.has_deal) return false;
      if (s) {
        const hay = `${c.company} ${c.sector ?? ""} ${c.summary ?? ""} ${(c.aliases ?? []).join(" ")}`.toLowerCase();
        if (!hay.includes(s)) return false;
      }
      return true;
    });
    out = out.sort((a, b) => {
      let r = 0;
      if (sort === "ask_inr_cr" || sort === "valuation_inr_cr" || sort === "revenue_inr_cr")
        r = num(a[sort]) - num(b[sort]);
      else r = String(a[sort] ?? "").localeCompare(String(b[sort] ?? ""));
      return asc ? r : -r;
    });
    return out;
  }, [companies, search, sector, stage, poc, dealsOnly, sort, asc]);

  const Th = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => {
    const on = sort === k;
    return (
      <th
        onClick={() => (on ? setAsc(!asc) : (setSort(k), setAsc(false)))}
        className={`px-3 py-2.5 cursor-pointer select-none whitespace-nowrap font-semibold uppercase tracking-wider text-[11px] transition-colors ${on ? "text-ink" : "hover:text-ink"} ${right ? "text-right" : "text-left"}`}>
        {label}
        <span className={`ml-1 ${on ? "text-accent" : "text-transparent"}`}>{on ? (asc ? "↑" : "↓") : "↓"}</span>
      </th>
    );
  };

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap gap-2 items-center p-3 border-b border-line bg-panel">
        <div className="relative flex-1 min-w-[220px]">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-dim pointer-events-none" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search company, sector, summary…"
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-line bg-raised text-sm outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/15" />
        </div>
        <select value={sector} onChange={(e) => setSector(e.target.value)} className={selectCls}>
          <option value="">All sectors</option>{sectors.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={stage} onChange={(e) => setStage(e.target.value)} className={selectCls}>
          <option value="">All stages</option>{stages.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={poc} onChange={(e) => setPoc(e.target.value)} className={selectCls}>
          <option value="">Any POC</option><option>High</option><option>Mid</option><option>Low</option>
        </select>
        <button
          type="button"
          onClick={() => setDealsOnly((v) => !v)}
          aria-pressed={dealsOnly}
          className={`px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${dealsOnly ? "bg-accenttint text-accentink border-accent/30" : "bg-panel text-dim border-line hover:text-ink hover:border-accent/40"}`}>
          Deals only
        </button>
        <span className="text-dim text-sm ml-auto tabular-nums">
          <span className="font-semibold text-ink">{rows.length}</span> of {companies.length}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-dim bg-raised border-b border-line">
            <tr>
              <Th k="company" label="Company" /><Th k="sector" label="Sector" /><Th k="stage" label="Stage" />
              <th className="px-3 py-2.5 text-left font-semibold uppercase tracking-wider text-[11px]">POC</th>
              <th className="px-3 py-2.5 text-left font-semibold uppercase tracking-wider text-[11px]">Fit</th>
              <Th k="ask_inr_cr" label="Ask" right /><Th k="valuation_inr_cr" label="Valuation" right />
              <Th k="revenue_inr_cr" label="Revenue" right /><Th k="last_interaction" label="Last" right />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.company} className="border-b border-line/70 last:border-0 hover:bg-wash transition-colors">
                <td className="px-3 py-2.5">
                  <Link href={`/companies/${encodeURIComponent(c.company)}`} className="text-accent hover:underline font-medium">{c.company}</Link>
                  {c.has_deal && <span className="ml-2 align-middle text-[10px] px-1.5 py-0.5 rounded-full bg-accenttint text-accentink font-semibold ring-1 ring-inset ring-accent/15">DEAL</span>}
                </td>
                <td className="px-3 py-2.5">{c.sector ?? "—"}</td>
                <td className="px-3 py-2.5">{c.stage ?? "—"}</td>
                <td className="px-3 py-2.5"><Badge v={c.poc} /></td>
                <td className="px-3 py-2.5"><Badge v={c.fitment} /></td>
                <td className="px-3 py-2.5 text-right tabular-nums">{inr(c.ask_inr_cr)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{inr(c.valuation_inr_cr)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{inr(c.revenue_inr_cr)}</td>
                <td className="px-3 py-2.5 text-right text-dim tabular-nums">{c.last_interaction ? String(c.last_interaction).slice(0, 10) : "—"}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={9} className="px-3 py-12 text-center text-dim">No matches.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
