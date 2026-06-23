import Link from "next/link";
import { getInvestorPortfolio, getCoinvestors, inr } from "@/lib/data";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: { name: string } }) {
  let name: string;
  try { name = decodeURIComponent(params.name); } catch { name = params.name; }
  const [portfolio, coinvestors] = await Promise.all([getInvestorPortfolio(name), getCoinvestors(name)]);

  if (portfolio.length === 0) {
    return (
      <div className="card p-8 text-center">
        <p className="text-dim">No portfolio recorded for “{name}”.</p>
        <Link href="/investors" className="text-accent hover:underline">← back to investors</Link>
      </div>
    );
  }
  const sectors = Array.from(new Set(portfolio.map((p) => p.sector).filter(Boolean))) as string[];

  return (
    <div className="space-y-5">
      <Link href="/investors" className="text-accent hover:underline text-sm">← Investors</Link>
      <PageHeader title={name} subtitle={`${portfolio.length} deal${portfolio.length > 1 ? "s" : ""} seen${sectors.length ? ` · ${sectors.slice(0, 4).join(", ")}` : ""}`} />

      <section className="card p-5">
        <h2 className="section-title mb-3">Portfolio (seen in our deal flow)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-dim border-b border-line">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Company</th>
                <th className="px-3 py-2 text-left font-semibold">Sector</th>
                <th className="px-3 py-2 text-left font-semibold">Stage</th>
                <th className="px-3 py-2 text-left font-semibold">Ask</th>
                <th className="px-3 py-2 text-left font-semibold">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.map((p) => (
                <tr key={p.company} className="border-b border-line/70 last:border-0 hover:bg-[#FAF7F1]">
                  <td className="px-3 py-2 font-medium"><Link href={`/companies/${encodeURIComponent(p.company)}`} className="text-accent hover:underline">{p.company}</Link></td>
                  <td className="px-3 py-2 text-dim">{p.sector ?? "—"}</td>
                  <td className="px-3 py-2 text-dim">{p.stage ?? "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{inr(p.ask_inr_cr)}</td>
                  <td className="px-3 py-2 text-dim tabular-nums">{p.last_interaction ? String(p.last_interaction).slice(0, 10) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {coinvestors.length > 0 && (
        <section className="card p-5">
          <h2 className="section-title mb-3">Co-investors <span className="text-dim font-normal">({coinvestors.length})</span></h2>
          <div className="flex flex-wrap gap-2">
            {coinvestors.map((ci) => (
              <Link key={ci.investor} href={`/investors/${encodeURIComponent(ci.investor)}`}
                className="px-2.5 py-1 rounded-full text-xs bg-wash border border-line hover:border-accent/40">
                {ci.investor}{ci.shared > 1 ? <span className="text-dim"> · {ci.shared}</span> : null}
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
