import { getStats, getCompanies } from "@/lib/data";
import CompaniesTable from "@/components/CompaniesTable";
import { Stat, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [stats, companies] = await Promise.all([getStats(), getCompanies()]);
  const spend = (() => {
    const n = parseFloat(stats?.llm_spend_usd ?? "");
    return Number.isFinite(n) ? `₹${Math.round(n * 85).toLocaleString("en-IN")}` : "—";
  })();
  return (
    <div className="space-y-6">
      <PageHeader title="Deal-flow overview" subtitle="Every company, deal and signal across the pipeline — one brain." />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Stat label="Companies" value={stats?.companies ?? "—"} />
        <Stat label="Deals" value={stats?.deals ?? "—"} hint="active in pipeline" />
        <Stat label="People" value={stats?.people ?? "—"} />
        <Stat label="Notes" value={stats?.indexed_notes ?? "—"} hint="indexed" />
        <Stat label="Sectors" value={stats?.sectors ?? "—"} />
        <Stat label="LLM spend" value={spend} hint="Gemini · lifetime" />
      </div>
      <CompaniesTable companies={companies} />
    </div>
  );
}
