import Link from "next/link";
import { getCompany, getCompanyEmails, inr } from "@/lib/data";
import { Badge, Pill } from "@/components/ui";

export const dynamic = "force-dynamic";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-dim text-xs uppercase tracking-wide font-semibold">{label}</div>
      <div className="mt-0.5">{children ?? "—"}</div>
    </div>
  );
}

export default async function Page({ params }: { params: { name: string } }) {
  let name: string;
  try {
    name = decodeURIComponent(params.name);
  } catch {
    name = params.name; // malformed %-encoding → use raw
  }
  const c = await getCompany(name);
  if (!c) {
    return (
      <div className="card p-8 text-center">
        <p className="text-dim">No company named “{name}”.</p>
        <Link href="/" className="text-accent hover:underline">← back to dashboard</Link>
      </div>
    );
  }
  const emails = await getCompanyEmails(name);
  const founders = c.founders ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <Link href="/" className="text-accent hover:underline text-sm">← Dashboard</Link>
        <h1 className="text-2xl font-bold">{c.company}</h1>
        {c.has_deal && <span className="text-xs px-2 py-0.5 rounded bg-minttint text-mintdark font-semibold">DEAL</span>}
        {(c.aliases ?? []).map((a) => <Pill key={a}>{a}</Pill>)}
      </div>

      <div className="card p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Field label="Sector">{c.sector}{c.sub_sector ? ` · ${c.sub_sector}` : ""}</Field>
        <Field label="Stage">{c.stage}{c.round_type ? ` · ${c.round_type}` : ""}</Field>
        <Field label="POC"><Badge v={c.poc} /></Field>
        <Field label="Fitment"><Badge v={c.fitment} /></Field>
        <Field label="Ask">{inr(c.ask_inr_cr)}</Field>
        <Field label="Valuation">{inr(c.valuation_inr_cr)}</Field>
        <Field label="Revenue">{inr(c.revenue_inr_cr)}{c.revenue_period ? ` (${c.revenue_period})` : ""}</Field>
        <Field label="EBITDA">{inr(c.ebitda_inr_cr)}</Field>
        <Field label="HQ">{c.hq}</Field>
        <Field label="Founded">{c.founded}</Field>
        <Field label="Website">{c.website ? <a href={c.website} className="text-accent hover:underline" target="_blank" rel="noreferrer">link</a> : "—"}</Field>
        <Field label="Last interaction">{c.last_interaction ? String(c.last_interaction).slice(0, 10) : "—"}</Field>
      </div>

      {c.summary && <section className="card p-5"><h2 className="font-semibold mb-2">About</h2><p className="text-[15px] leading-relaxed">{c.summary}</p></section>}
      {c.business_model && <section className="card p-5"><h2 className="font-semibold mb-2">Business model</h2><p className="text-[15px] leading-relaxed">{c.business_model}</p></section>}

      <div className="grid md:grid-cols-2 gap-5">
        {founders.length > 0 && (
          <section className="card p-5">
            <h2 className="font-semibold mb-3">People</h2>
            <ul className="space-y-1.5 text-sm">
              {founders.map((f, i) => (
                <li key={i}>
                  <span className="font-medium">{f.name}</span>{f.role ? <span className="text-dim"> — {f.role}</span> : null}
                  {f.linkedin ? <a href={f.linkedin} className="text-accent hover:underline ml-2" target="_blank" rel="noreferrer">in</a> : null}
                </li>
              ))}
            </ul>
          </section>
        )}
        {(c.key_metrics ?? []).length > 0 && (
          <section className="card p-5">
            <h2 className="font-semibold mb-3">Key metrics</h2>
            <ul className="list-disc pl-5 space-y-1 text-sm">{(c.key_metrics ?? []).map((m, i) => <li key={i}>{m}</li>)}</ul>
          </section>
        )}
        {(c.risks ?? []).length > 0 && (
          <section className="card p-5">
            <h2 className="font-semibold mb-3">Risks</h2>
            <ul className="list-disc pl-5 space-y-1 text-sm">{(c.risks ?? []).map((m, i) => <li key={i}>{m}</li>)}</ul>
          </section>
        )}
        {(c.existing_investors ?? []).length > 0 && (
          <section className="card p-5">
            <h2 className="font-semibold mb-3">Existing investors</h2>
            <div className="flex flex-wrap gap-2">{(c.existing_investors ?? []).map((m, i) => <Pill key={i}>{m}</Pill>)}</div>
            {c.referred_by && <p className="text-dim text-sm mt-3">Referred by: {c.referred_by}</p>}
          </section>
        )}
      </div>

      <section className="card p-5">
        <h2 className="font-semibold mb-3">Call notes ({emails.length})</h2>
        <div className="space-y-3">
          {emails.map((e, i) => (
            <div key={i} className="border-b border-line pb-3 last:border-0">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-dim tabular-nums">{e.date ?? "—"}</span>
                <span className="font-medium">{e.title}</span>
                <Badge v={e.poc} />
              </div>
              {e.summary && <p className="text-sm text-dim mt-1">{e.summary}</p>}
            </div>
          ))}
          {emails.length === 0 && <p className="text-dim text-sm">No call notes linked.</p>}
        </div>
      </section>
    </div>
  );
}
