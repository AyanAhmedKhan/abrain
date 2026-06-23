import Link from "next/link";
import { getInbox, inr } from "@/lib/data";
import { PageHeader } from "@/components/ui";
import TaskRow from "@/components/TaskRow";

export const dynamic = "force-dynamic";

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="section-title mb-3">{title} <span className="text-dim font-normal">({count})</span></h2>
      {count === 0 ? <p className="text-dim text-sm">Nothing here.</p> : children}
    </section>
  );
}

export default async function Page() {
  const { tasks, newDeals, quiet, freshFinancials } = await getInbox();
  const overdue = tasks.filter((t) => t.overdue).length;
  return (
    <div className="space-y-5">
      <PageHeader title="Inbox" subtitle={overdue ? `${overdue} overdue follow-up${overdue > 1 ? "s" : ""}` : "Follow-ups & signals"} />
      <div className="grid lg:grid-cols-2 gap-5">
        <Section title="Follow-ups" count={tasks.length}>
          <ul>{tasks.map((t) => <TaskRow key={t.id} t={t} />)}</ul>
        </Section>

        <div className="space-y-5">
          <Section title="New this week" count={newDeals.length}>
            <ul className="space-y-1.5 text-sm">
              {newDeals.map((d, i) => (
                <li key={i} className="flex items-center justify-between gap-2">
                  <Link href={`/companies/${encodeURIComponent(d.company)}`} className="text-accent hover:underline truncate">{d.company}</Link>
                  <span className="text-dim text-xs shrink-0">{[d.sector, inr(d.ask_inr_cr) !== "—" ? inr(d.ask_inr_cr) : null].filter(Boolean).join(" · ")}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Going quiet (21d+)" count={quiet.length}>
            <ul className="space-y-1.5 text-sm">
              {quiet.map((d, i) => (
                <li key={i} className="flex items-center justify-between gap-2">
                  <Link href={`/companies/${encodeURIComponent(d.company)}`} className="text-accent hover:underline truncate">{d.company}</Link>
                  <span className="text-dim text-xs shrink-0 tabular-nums">{d.last_interaction ? String(d.last_interaction).slice(0, 10) : ""}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Fresh financials (7d)" count={freshFinancials.length}>
            <ul className="space-y-1.5 text-sm">
              {freshFinancials.map((f, i) => (
                <li key={i} className="flex items-center justify-between gap-2">
                  <Link href={`/companies/${encodeURIComponent(f.company)}`} className="text-accent hover:underline truncate">{f.company}</Link>
                  <span className="text-dim text-xs shrink-0 tabular-nums">{f.metric} {inr(f.value_num)}{f.period ? ` (${f.period})` : ""}</span>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </div>
  );
}
