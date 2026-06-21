import Link from "next/link";
import { getPerson, getPersonCompanies } from "@/lib/data";
import { Avatar } from "@/components/Img";

export const dynamic = "force-dynamic";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-dim text-xs uppercase tracking-wide font-semibold">{label}</div>
      <div className="mt-0.5">{children ?? "—"}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="font-semibold mb-3">{title}</h2>
      {children}
    </section>
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
  const companies = await getPersonCompanies(params.id);
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

      <div className="card p-5 flex items-start gap-4">
        <Avatar src={p.photo_url} name={p.person} size={80} />
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">{p.person}</h1>
          {p.headline && <p className="text-dim mt-1">{p.headline}</p>}
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-dim">
            {loc && <span>📍 {loc}</span>}
            {p.followers != null && <span>{p.followers.toLocaleString()} followers</span>}
            {p.connections != null && <span>{p.connections.toLocaleString()} connections</span>}
            {p.linkedin_url && (
              <a href={p.linkedin_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                {p.public_id ? `in/${p.public_id}` : "LinkedIn ↗"}
              </a>
            )}
          </div>
        </div>
      </div>

      <div className="card p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Field label="Current role">{p.current_title}</Field>
        <Field label="Current company">{p.current_company}</Field>
        <Field label="LinkedIn ID">{p.public_id}</Field>
        <Field label="Linked companies">
          {companies.length
            ? <div className="flex flex-wrap gap-1">{companies.map((c) => (
                <Link key={c} href={`/companies/${encodeURIComponent(c)}`} className="text-accent hover:underline">{c}</Link>
              ))}</div>
            : "—"}
        </Field>
      </div>

      {p.about && (
        <Section title="About">
          <p className="text-[15px] leading-relaxed whitespace-pre-line">{p.about}</p>
        </Section>
      )}

      {exp.length > 0 && (
        <Section title="Experience">
          <ul className="space-y-3">
            {exp.map((e, i) => (
              <li key={i} className="border-l-2 border-line pl-3">
                <div className="font-medium">{[e.position, e.companyName].filter(Boolean).join(" — ")}</div>
                <div className="text-dim text-xs">
                  {[[e.start, e.end].filter(Boolean).join(" – "), e.duration, e.employmentType, e.workplaceType, e.location].filter(Boolean).join(" · ")}
                </div>
                {e.description && <p className="text-sm mt-1">{e.description}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {edu.length > 0 && (
        <Section title="Education">
          <ul className="space-y-2">
            {edu.map((e, i) => (
              <li key={i}>
                <div className="font-medium">{e.schoolName}</div>
                <div className="text-dim text-xs">{[[e.degree, e.fieldOfStudy].filter(Boolean).join(", "), e.period, e.insights].filter(Boolean).join(" · ")}</div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {skills.length > 0 && (
        <Section title="Skills">
          <div className="flex flex-wrap gap-1.5">
            {skills.map((s) => <span key={s} className="px-2 py-0.5 rounded-full text-xs bg-cream text-ink/70">{s}</span>)}
          </div>
        </Section>
      )}

      {certs.length > 0 && (
        <Section title="Certifications">
          <ul className="space-y-1.5 text-sm">
            {certs.map((c, i) => (
              <li key={i}>
                {c.link ? <a href={c.link} target="_blank" rel="noreferrer" className="text-accent hover:underline">{c.title}</a> : c.title}
                {(c.issuedBy || c.issuedAt) && <span className="text-dim"> — {[c.issuedBy, c.issuedAt].filter(Boolean).join(" · ")}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {honors.length > 0 && (
        <Section title="Honors & Awards">
          <ul className="space-y-2 text-sm">
            {honors.map((h, i) => (
              <li key={i}>
                <span className="font-medium">{h.title}</span>
                {(h.issuedBy || h.issuedAt) && <span className="text-dim"> — {[h.issuedBy, h.issuedAt].filter(Boolean).join(" · ")}</span>}
                {h.description && <p className="text-dim mt-0.5">{h.description}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {projects.length > 0 && (
        <Section title="Projects">
          <ul className="space-y-1.5 text-sm">
            {projects.map((pr, i) => (
              <li key={i}><span className="font-medium">{pr.title}</span>{pr.description ? <span className="text-dim"> — {pr.description}</span> : null}</li>
            ))}
          </ul>
        </Section>
      )}

      {p.scraped_at && <p className="text-dim text-xs">Profile scraped {String(p.scraped_at).slice(0, 10)} · LinkedIn via Apify</p>}
    </div>
  );
}
