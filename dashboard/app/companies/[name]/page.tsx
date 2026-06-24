import Link from "next/link";
import { getCompany, getCompanyEmails, getCompanyProfile, getCompanyPeople, getCompanyFinancials, getIntroPaths, inr } from "@/lib/data";
import { Badge, Pill, Chip } from "@/components/ui";
import { Logo, Avatar } from "@/components/Img";
import { Metric } from "@/components/Chart";
import { OpenDeck } from "@/components/OpenDeck";
import { RemoveDeck } from "@/components/RemoveDeck";

export const dynamic = "force-dynamic";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-dim text-[11px] uppercase tracking-wider font-semibold">{label}</div>
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
  const [emails, lp, orgPeople, fin, intro] = await Promise.all([
    getCompanyEmails(name), getCompanyProfile(name), getCompanyPeople(name), getCompanyFinancials(name),
    getIntroPaths(name, c.referred_by),
  ]);
  const founders = c.founders ?? [];
  const hasIntro = !!intro.referred_by || intro.bridges.length > 0 || intro.classmates.length > 0 || intro.investors.length > 0;

  // group the financial time-series by metric → points for the trend charts
  const series = (m: string) => fin
    .filter((f) => f.metric === m && f.value_num != null)
    .map((f) => ({ label: f.period || (f.as_of ? String(f.as_of).slice(0, 7) : ""), value: parseFloat(f.value_num as string) }))
    .filter((p) => !Number.isNaN(p.value));
  const rev = series("revenue"), val = series("valuation"), ebitda = series("ebitda");
  const lastRev = rev.at(-1)?.value, lastVal = val.at(-1)?.value;
  const multiple = lastRev && lastVal ? (lastVal / lastRev).toFixed(1) : null;
  const hasTrends = rev.length + val.length + ebitda.length > 0;

  return (
    <div className="space-y-5">
      <Link href="/" className="text-accent hover:underline text-sm">← Dashboard</Link>

      <div className="card p-5 flex items-center gap-4 flex-wrap">
        {lp?.logo_url && <Logo src={lp.logo_url} name={c.company} size={48} />}
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-2xl font-bold tracking-tight">{c.company}</h1>
            {c.has_deal && <span className="text-xs px-2 py-0.5 rounded-full bg-accenttint text-accentink font-semibold ring-1 ring-inset ring-accent/15">DEAL</span>}
          </div>
          <div className="flex items-center gap-2 flex-wrap mt-1.5 text-sm">
            {(c.sector || c.stage) && <span className="text-dim">{[c.sector, c.stage].filter(Boolean).join(" · ")}</span>}
            {lp?.linkedin_url && <a href={lp.linkedin_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">LinkedIn ↗</a>}
            {(c.aliases ?? []).map((a) => <Pill key={a}>{a}</Pill>)}
          </div>
        </div>
      </div>

      {lp && (
        <section className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="section-title">LinkedIn</h2>
            <span className="text-dim text-xs">via Apify{lp.scraped_at ? ` · ${String(lp.scraped_at).slice(0, 10)}` : ""}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Field label="Industry">{lp.industry}</Field>
            <Field label="Company size">{lp.company_size}</Field>
            <Field label="Employees on LinkedIn">{lp.employee_count?.toLocaleString() ?? null}</Field>
            <Field label="Followers">{lp.followers?.toLocaleString() ?? null}</Field>
            <Field label="HQ">{lp.hq}</Field>
            <Field label="Founded">{lp.founded}</Field>
            <Field label="Website">{lp.website ? <a href={lp.website} className="text-accent hover:underline" target="_blank" rel="noreferrer">link</a> : null}</Field>
            <Field label="LinkedIn ID">{lp.public_id}</Field>
          </div>
          {lp.description && <p className="text-[15px] leading-relaxed mt-4 whitespace-pre-line">{lp.description}</p>}
          {(lp.specialties ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-4">
              {(lp.specialties ?? []).map((s) => <Chip key={s}>{s}</Chip>)}
            </div>
          )}
        </section>
      )}

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

      {hasTrends && (
        <section className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="section-title">Financial trends</h2>
            {multiple && <span className="text-dim text-xs">Valuation / Revenue ≈ <b className="text-ink tabular-nums">{multiple}×</b></span>}
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <Metric title="Revenue" points={rev} />
            <Metric title="Valuation" points={val} />
            <Metric title="EBITDA" points={ebitda} />
          </div>
        </section>
      )}

      {(() => {
        const current = orgPeople.filter((op) => op.current !== false);
        const past = orgPeople.filter((op) => op.current === false);
        const grid = (list: typeof orgPeople) => (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {list.map((op) => (
              <div key={op.entity_id} className="flex items-center gap-3 border border-line rounded-xl p-2.5 transition-colors hover:border-accent/40 hover:bg-wash">
                <Avatar src={op.photo_url} name={op.person} size={36} />
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">
                    {op.has_profile
                      ? <Link href={`/people/${op.entity_id}`} className="text-accent hover:underline">{op.person}</Link>
                      : op.person}
                  </div>
                  <div className="text-dim text-xs truncate" title={op.headline ?? op.role ?? ""}>
                    {op.role ?? op.headline ?? ""}{op.tenure ? <span className="opacity-70"> · {op.tenure}</span> : null}
                  </div>
                </div>
                {op.linkedin && <a href={op.linkedin} target="_blank" rel="noreferrer" className="text-accent hover:underline text-xs shrink-0">in ↗</a>}
              </div>
            ))}
          </div>
        );
        return (
          <>
            {current.length > 0 && (
              <section className="card p-5">
                <h2 className="section-title mb-3">Current team <span className="text-dim font-normal">({current.length})</span></h2>
                {grid(current)}
              </section>
            )}
            {past.length > 0 && (
              <section className="card p-5">
                <h2 className="section-title mb-3">Past employees <span className="text-dim font-normal">({past.length})</span></h2>
                {grid(past)}
              </section>
            )}
          </>
        );
      })()}

      {c.summary && <section className="card p-5"><h2 className="section-title mb-2">About</h2><p className="text-[15px] leading-relaxed">{c.summary}</p></section>}
      {c.business_model && <section className="card p-5"><h2 className="section-title mb-2">Business model</h2><p className="text-[15px] leading-relaxed">{c.business_model}</p></section>}

      <div className="grid md:grid-cols-2 gap-5">
        {founders.length > 0 && (
          <section className="card p-5">
            <h2 className="section-title mb-3">People</h2>
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
            <h2 className="section-title mb-3">Key metrics</h2>
            <ul className="list-disc pl-5 space-y-1 text-sm marker:text-accent">{(c.key_metrics ?? []).map((m, i) => <li key={i}>{m}</li>)}</ul>
          </section>
        )}
        {(c.risks ?? []).length > 0 && (
          <section className="card p-5">
            <h2 className="section-title mb-3">Risks</h2>
            <ul className="list-disc pl-5 space-y-1 text-sm marker:text-rose-400">{(c.risks ?? []).map((m, i) => <li key={i}>{m}</li>)}</ul>
          </section>
        )}
        {(c.existing_investors ?? []).length > 0 && (
          <section className="card p-5">
            <h2 className="section-title mb-3">Existing investors</h2>
            <div className="flex flex-wrap gap-2">{(c.existing_investors ?? []).map((m, i) => <Pill key={i}>{m}</Pill>)}</div>
            {c.referred_by && <p className="text-dim text-sm mt-3">Referred by: {c.referred_by}</p>}
          </section>
        )}
      </div>

      {hasIntro && (
        <section className="card p-5">
          <h2 className="section-title mb-3">Warm intro paths</h2>
          <div className="space-y-3 text-sm">
            {intro.referred_by && (
              <div>↪ Introduced by <span className="font-medium">{intro.referred_by}</span></div>
            )}
            {intro.investors.length > 0 && (
              <div>
                <div className="text-dim text-xs uppercase tracking-wider font-semibold mb-1">Via investors</div>
                <div className="flex flex-wrap gap-2">
                  {intro.investors.map((iv) => (
                    <Link key={iv.investor_id} href={`/investors/${encodeURIComponent(iv.investor)}`} className="px-2 py-0.5 rounded-full text-xs bg-accenttint text-accentink hover:underline">
                      {iv.investor}{iv.portfolio > 1 ? ` · ${iv.portfolio} deals` : ""}
                    </Link>
                  ))}
                </div>
              </div>
            )}
            {intro.bridges.length > 0 && (
              <div>
                <div className="text-dim text-xs uppercase tracking-wider font-semibold mb-1">Shared-employer connectors</div>
                <ul className="space-y-1">
                  {intro.bridges.map((b, i) => (
                    <li key={i} className="leading-snug">
                      <span className="font-medium">{b.connector}</span>{b.is_dexter && <span className="ml-1 text-[10px] font-semibold text-accentink bg-accenttint rounded px-1">DEXTER</span>}
                      <span className="text-dim"> → both at <span className="text-ink">{b.via_company}</span> → reach <span className="text-ink">{b.person}</span></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {intro.classmates.length > 0 && (
              <div>
                <div className="text-dim text-xs uppercase tracking-wider font-semibold mb-1">Classmate connectors</div>
                <ul className="space-y-1">
                  {intro.classmates.map((b, i) => (
                    <li key={i} className="leading-snug">
                      <span className="font-medium">{b.connector}</span>{b.is_dexter && <span className="ml-1 text-[10px] font-semibold text-accentink bg-accenttint rounded px-1">DEXTER</span>}
                      <span className="text-dim"> → both studied at <span className="text-ink">{b.via_company}</span> → reach <span className="text-ink">{b.person}</span></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}

      <section className="card p-5">
        <h2 className="section-title mb-3">Sources ({emails.length})</h2>
        <div className="space-y-3">
          {emails.map((e, i) => (
            <div key={i} className="border-b border-line pb-3 last:border-0">
              <div className="flex items-center gap-2 text-sm flex-wrap">
                <span className="text-dim tabular-nums">{e.date ?? "—"}</span>
                <span className={`text-[10px] font-semibold rounded px-1.5 py-0.5 ${e.source === "pdf" ? "bg-accenttint text-accentink" : "bg-wash text-dim"}`}>{e.kind ?? (e.source === "pdf" ? "Pitch deck" : "Email")}</span>
                <span className="font-medium">{e.title}</span>
                <Badge v={e.poc} />
                {e.source === "pdf" && <OpenDeck deckRef={e.deck_ref} sourceUrl={e.source_url} />}
                {e.source === "pdf" && e.envelope_id && (
                  <span className="ml-auto"><RemoveDeck envelopeId={e.envelope_id} company={e.company ?? undefined} title={e.title} /></span>
                )}
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
