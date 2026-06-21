import Link from "next/link";
import { getPerson, getPersonCompanies, getColleagues } from "@/lib/data";
import { Avatar } from "@/components/Img";
import { SectionCard, Chip } from "@/components/ui";

export const dynamic = "force-dynamic";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-dim text-[11px] uppercase tracking-wider font-semibold">{label}</div>
      <div className="mt-0.5">{children ?? "—"}</div>
    </div>
  );
}

export default async function Page({ params }: { params: { id: string } }) {
  const p = await getPerson(params.id);
  if (!p) {
    return (
      <div className="card p-8 text-center">
        <p className="text-dim">No profile found.</p>
        <Link href="/people" className="text-accent hover:underline">← back to people</Link>
      </div>
    );
  }
  const [companies, colleagues] = await Promise.all([
    getPersonCompanies(params.id), getColleagues(params.id),
  ]);
  const loc = [p.location_city, p.location_country].filter(Boolean).join(", ");
  const exp = p.experience ?? [];
  const edu = p.education ?? [];
  const skills = p.skills ?? [];
  const certs = p.certifications ?? [];
  const honors = p.honors ?? [];
  const projects = p.projects ?? [];

  return (
    <div className="space-y-5">
      <Link href="/people" className="text-accent hover:underline text-sm">← People</Link>

      {/* hero */}
      <div className="card overflow-hidden">
        <div className="h-20 bg-gradient-to-r from-brand2 to-brand1" />
        <div className="px-5 pb-5 -mt-10 flex items-end gap-4 flex-wrap">
          <div className="rounded-full ring-4 ring-panel">
            <Avatar src={p.photo_url} name={p.person} size={80} />
          </div>
          <div className="min-w-0 flex-1 pb-0.5">
            <h1 className="text-2xl font-bold tracking-tight">{p.person}</h1>
            {p.headline && <p className="text-dim mt-1">{p.headline}</p>}
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-dim">
              {loc && <span>📍 {loc}</span>}
              {p.followers != null && <span><b className="text-ink font-semibold tabular-nums">{p.followers.toLocaleString()}</b> followers</span>}
              {p.connections != null && <span><b className="text-ink font-semibold tabular-nums">{p.connections.toLocaleString()}</b> connections</span>}
              {p.linkedin_url && (
                <a href={p.linkedin_url} target="_blank" rel="noreferrer" className="text-accent hover:underline font-medium">
                  {p.public_id ? `in/${p.public_id}` : "LinkedIn ↗"}
                </a>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="card p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Field label="Current role">{p.current_title}</Field>
        <Field label="Current company">{p.current_company}</Field>
        <Field label="LinkedIn ID">{p.public_id}</Field>
        <Field label="Linked companies">
          {companies.length
            ? <div className="flex flex-wrap gap-x-2 gap-y-0.5">{companies.map((c) => (
                <Link key={c} href={`/companies/${encodeURIComponent(c)}`} className="text-accent hover:underline">{c}</Link>
              ))}</div>
            : "—"}
        </Field>
      </div>

      {p.about && (
        <SectionCard title="About">
          <p className="text-[15px] leading-relaxed whitespace-pre-line">{p.about}</p>
        </SectionCard>
      )}

      {exp.length > 0 && (
        <SectionCard title="Experience">
          <ul className="space-y-4">
            {exp.map((e, i) => (
              <li key={i} className="relative pl-5">
                <span className="absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full bg-accent ring-4 ring-accent/15" />
                <span className="absolute left-[4.5px] top-4 bottom-[-1rem] w-px bg-line last:hidden" />
                <div className="font-medium">{[e.position, e.companyName].filter(Boolean).join(" · ")}</div>
                <div className="text-dim text-xs mt-0.5">
                  {[[e.start, e.end].filter(Boolean).join(" – "), e.duration, e.employmentType, e.workplaceType, e.location].filter(Boolean).join(" · ")}
                </div>
                {e.description && <p className="text-sm mt-1.5 leading-relaxed">{e.description}</p>}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {edu.length > 0 && (
        <SectionCard title="Education">
          <ul className="space-y-2.5">
            {edu.map((e, i) => (
              <li key={i}>
                <div className="font-medium">{e.schoolName}</div>
                <div className="text-dim text-xs mt-0.5">{[[e.degree, e.fieldOfStudy].filter(Boolean).join(", "), e.period, e.insights].filter(Boolean).join(" · ")}</div>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {skills.length > 0 && (
        <SectionCard title="Skills">
          <div className="flex flex-wrap gap-1.5">{skills.map((s) => <Chip key={s}>{s}</Chip>)}</div>
        </SectionCard>
      )}

      {certs.length > 0 && (
        <SectionCard title="Certifications">
          <ul className="space-y-1.5 text-sm">
            {certs.map((c, i) => (
              <li key={i}>
                {c.link ? <a href={c.link} target="_blank" rel="noreferrer" className="text-accent hover:underline">{c.title}</a> : c.title}
                {(c.issuedBy || c.issuedAt) && <span className="text-dim"> — {[c.issuedBy, c.issuedAt].filter(Boolean).join(" · ")}</span>}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {honors.length > 0 && (
        <SectionCard title="Honors & Awards">
          <ul className="space-y-2 text-sm">
            {honors.map((h, i) => (
              <li key={i}>
                <span className="font-medium">{h.title}</span>
                {(h.issuedBy || h.issuedAt) && <span className="text-dim"> — {[h.issuedBy, h.issuedAt].filter(Boolean).join(" · ")}</span>}
                {h.description && <p className="text-dim mt-0.5">{h.description}</p>}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {projects.length > 0 && (
        <SectionCard title="Projects">
          <ul className="space-y-1.5 text-sm">
            {projects.map((pr, i) => (
              <li key={i}><span className="font-medium">{pr.title}</span>{pr.description ? <span className="text-dim"> — {pr.description}</span> : null}</li>
            ))}
          </ul>
        </SectionCard>
      )}

      {colleagues.length > 0 && (
        <SectionCard title={`Colleagues (${colleagues.length})`}>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {colleagues.map((co) => (
              <div key={co.entity_id} className="flex items-center gap-3 border border-line rounded-xl p-2.5 transition-colors hover:border-accent/40 hover:bg-wash">
                <Avatar src={co.photo_url} name={co.person} size={36} />
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">
                    {co.has_profile
                      ? <Link href={`/people/${co.entity_id}`} className="text-accent hover:underline">{co.person}</Link>
                      : co.person}
                  </div>
                  <div className="text-dim text-xs truncate" title={co.headline ?? co.role ?? ""}>
                    {co.role ?? co.headline ?? ""}{co.company ? ` · ${co.company}` : ""}
                  </div>
                </div>
                {co.linkedin && <a href={co.linkedin} target="_blank" rel="noreferrer" className="text-accent hover:underline text-xs shrink-0">in ↗</a>}
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {p.scraped_at && <p className="text-dim text-xs">Profile scraped {String(p.scraped_at).slice(0, 10)} · LinkedIn via Apify</p>}
    </div>
  );
}
