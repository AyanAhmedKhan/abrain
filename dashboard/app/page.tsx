import { getStats, getCompanies, inr } from "@/lib/data";
import CompaniesTable from "@/components/CompaniesTable";
import { Stat } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [stats, companies] = await Promise.all([getStats(), getCompanies()]);
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold">Deal-flow overview</h1>
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <Stat label="Companies" value={stats?.companies ?? "—"} />
        <Stat label="Deals" value={stats?.deals ?? "—"} />
        <Stat label="People" value={stats?.people ?? "—"} />
        <Stat label="Notes" value={stats?.indexed_notes ?? "—"} />
        <Stat label="Sectors" value={stats?.sectors ?? "—"} />
        <Stat label="LLM spend" value={(() => {
          const n = parseFloat(stats?.llm_spend_usd ?? "");
          return Number.isFinite(n) ? `₹${Math.round(n * 85)}` : "—";
        })()} />
      </div>
      <CompaniesTable companies={companies} />
    </div>
  );
}
