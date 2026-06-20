"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { type Company, inr } from "@/lib/types";
import { Badge } from "./ui";

type SortKey = "company" | "sector" | "stage" | "ask_inr_cr" | "valuation_inr_cr" | "revenue_inr_cr" | "last_interaction";

const num = (v: string | null) => (v === null || v === "" ? -Infinity : parseFloat(v));

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

  const Th = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => (
    <th
      onClick={() => (sort === k ? setAsc(!asc) : (setSort(k), setAsc(false)))}
      className={`px-3 py-2 cursor-pointer select-none hover:text-ink ${right ? "text-right" : "text-left"}`}>
      {label}{sort === k ? (asc ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap gap-2 items-center p-3 border-b border-line">
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search company, sector, summary…"
          className="flex-1 min-w-[220px] px-3 py-2 rounded-lg border border-line bg-[#FBFAF6] outline-none focus:border-accent" />
        <select value={sector} onChange={(e) => setSector(e.target.value)} className="px-2 py-2 rounded-lg border border-line bg-white">
          <option value="">All sectors</option>{sectors.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={stage} onChange={(e) => setStage(e.target.value)} className="px-2 py-2 rounded-lg border border-line bg-white">
          <option value="">All stages</option>{stages.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={poc} onChange={(e) => setPoc(e.target.value)} className="px-2 py-2 rounded-lg border border-line bg-white">
          <option value="">Any POC</option><option>High</option><option>Mid</option><option>Low</option>
        </select>
        <label className="flex items-center gap-1.5 text-sm text-dim px-1">
          <input type="checkbox" checked={dealsOnly} onChange={(e) => setDealsOnly(e.target.checked)} /> Deals only
        </label>
        <span className="text-dim text-sm ml-auto tabular-nums">{rows.length} of {companies.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-dim border-b border-line bg-[#F7F3EC]">
            <tr>
              <Th k="company" label="Company" /><Th k="sector" label="Sector" /><Th k="stage" label="Stage" />
              <th className="px-3 py-2 text-left">POC</th><th className="px-3 py-2 text-left">Fit</th>
              <Th k="ask_inr_cr" label="Ask" right /><Th k="valuation_inr_cr" label="Valuation" right />
              <Th k="revenue_inr_cr" label="Revenue" right /><Th k="last_interaction" label="Last" right />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.company} className="border-b border-line hover:bg-[#FAF7F1]">
                <td className="px-3 py-2">
                  <Link href={`/companies/${encodeURIComponent(c.company)}`} className="text-accent hover:underline font-medium">{c.company}</Link>
                  {c.has_deal && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-minttint text-mintdark font-semibold">DEAL</span>}
                </td>
                <td className="px-3 py-2">{c.sector ?? "—"}</td>
                <td className="px-3 py-2">{c.stage ?? "—"}</td>
                <td className="px-3 py-2"><Badge v={c.poc} /></td>
                <td className="px-3 py-2"><Badge v={c.fitment} /></td>
                <td className="px-3 py-2 text-right tabular-nums">{inr(c.ask_inr_cr)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{inr(c.valuation_inr_cr)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{inr(c.revenue_inr_cr)}</td>
                <td className="px-3 py-2 text-right text-dim tabular-nums">{c.last_interaction ? String(c.last_interaction).slice(0, 10) : "—"}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={9} className="px-3 py-10 text-center text-dim">No matches.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
