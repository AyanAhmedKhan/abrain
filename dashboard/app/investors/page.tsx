import Link from "next/link";
import { getInvestors } from "@/lib/data";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";
const th = "px-3 py-2.5 text-left font-semibold uppercase tracking-wider text-[11px]";

export default async function Page() {
  const investors = await getInvestors();
  const multi = investors.filter((i) => i.portfolio > 1).length;
  return (
    <div className="space-y-5">
      <PageHeader title="Investors" count={investors.length} subtitle={`${multi} appear in multiple deals`} />
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-dim bg-[#F7F3EC] border-b border-line">
              <tr>
                <th className={th}>Investor</th>
                <th className={th}>Deals</th>
                <th className={th}>Sectors</th>
                <th className={th}>Portfolio (seen)</th>
              </tr>
            </thead>
            <tbody>
              {investors.map((iv) => (
                <tr key={iv.investor_id} className="border-b border-line/70 last:border-0 hover:bg-[#FAF7F1]">
                  <td className="px-3 py-2.5 font-medium"><Link href={`/investors/${encodeURIComponent(iv.investor)}`} className="text-accent hover:underline">{iv.investor}</Link></td>
                  <td className="px-3 py-2.5 tabular-nums">{iv.portfolio}</td>
                  <td className="px-3 py-2.5 text-dim max-w-[16rem] truncate" title={iv.sectors ?? ""}>{iv.sectors ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-x-2 gap-y-0.5">
                      {(iv.companies ?? []).slice(0, 8).map((co) => (
                        <Link key={co} href={`/companies/${encodeURIComponent(co)}`} className="text-accent hover:underline">{co}</Link>
                      ))}
                      {(iv.companies ?? []).length > 8 && <span className="text-dim text-xs">+{(iv.companies ?? []).length - 8}</span>}
                    </div>
                  </td>
                </tr>
              ))}
              {investors.length === 0 && <tr><td colSpan={4} className="px-3 py-12 text-center text-dim">No investors captured yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
