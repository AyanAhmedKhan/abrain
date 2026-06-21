import Link from "next/link";
import { getPeople } from "@/lib/data";
import { Avatar } from "@/components/Img";

export const dynamic = "force-dynamic";

export default async function Page() {
  const people = await getPeople();
  const withProfile = people.filter((p) => p.has_profile).length;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold">
        People <span className="text-dim font-normal">({people.length})</span>
        {withProfile > 0 && <span className="text-dim font-normal text-sm"> · {withProfile} LinkedIn profiles</span>}
      </h1>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-dim border-b border-line bg-[#F7F3EC]">
            <tr>
              <th className="px-3 py-2 text-left">Name</th>
              <th className="px-3 py-2 text-left">Headline / Role</th>
              <th className="px-3 py-2 text-left">Company</th>
              <th className="px-3 py-2 text-left">Location</th>
              <th className="px-3 py-2 text-left">LinkedIn</th>
            </tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.entity_id} className="border-b border-line hover:bg-[#FAF7F1]">
                <td className="px-3 py-2 font-medium">
                  <div className="flex items-center gap-2">
                    <Avatar src={p.photo_url} name={p.person} size={28} />
                    {p.has_profile
                      ? <Link className="text-accent hover:underline" href={`/people/${p.entity_id}`}>{p.person}</Link>
                      : <span>{p.person}</span>}
                  </div>
                </td>
                <td className="px-3 py-2 text-dim max-w-[28rem] truncate" title={p.headline ?? p.role ?? ""}>{p.headline ?? p.role ?? "—"}</td>
                <td className="px-3 py-2">
                  {(p.current_company ?? p.company)
                    ? <Link className="text-accent hover:underline" href={`/companies/${encodeURIComponent(p.current_company ?? p.company!)}`}>{p.current_company ?? p.company}</Link>
                    : "—"}
                </td>
                <td className="px-3 py-2 text-dim">{p.location ?? "—"}</td>
                <td className="px-3 py-2">{p.linkedin ? <a className="text-accent hover:underline" href={p.linkedin} target="_blank" rel="noreferrer">in ↗</a> : <span className="text-dim">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
