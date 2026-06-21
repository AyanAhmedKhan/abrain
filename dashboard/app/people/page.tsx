import Link from "next/link";
import { getPeople } from "@/lib/data";
import { Avatar } from "@/components/Img";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

const th = "px-3 py-2.5 text-left font-semibold uppercase tracking-wider text-[11px]";

export default async function Page() {
  const people = await getPeople();
  const withProfile = people.filter((p) => p.has_profile).length;
  return (
    <div className="space-y-6">
      <PageHeader
        title="People"
        count={people.length}
        subtitle={withProfile > 0 ? `${withProfile} enriched with LinkedIn profiles` : undefined}
      />
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-dim bg-[#F7F3EC] border-b border-line">
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Headline / Role</th>
                <th className={th}>Company</th>
                <th className={th}>Location</th>
                <th className={th}>LinkedIn</th>
              </tr>
            </thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.entity_id} className="border-b border-line/70 last:border-0 hover:bg-[#FAF7F1] transition-colors">
                  <td className="px-3 py-2.5 font-medium">
                    <div className="flex items-center gap-2.5">
                      <Avatar src={p.photo_url} name={p.person} size={30} />
                      {p.has_profile
                        ? <Link className="text-accent hover:underline" href={`/people/${p.entity_id}`}>{p.person}</Link>
                        : <span>{p.person}</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-dim max-w-[28rem] truncate" title={p.headline ?? p.role ?? ""}>{p.headline ?? p.role ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    {(p.current_company ?? p.company)
                      ? <Link className="text-accent hover:underline" href={`/companies/${encodeURIComponent(p.current_company ?? p.company!)}`}>{p.current_company ?? p.company}</Link>
                      : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-dim">{p.location ?? "—"}</td>
                  <td className="px-3 py-2.5">{p.linkedin ? <a className="text-accent hover:underline font-medium" href={p.linkedin} target="_blank" rel="noreferrer">in ↗</a> : <span className="text-dim">—</span>}</td>
                </tr>
              ))}
              {people.length === 0 && <tr><td colSpan={5} className="px-3 py-12 text-center text-dim">No people yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
