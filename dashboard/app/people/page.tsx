import Link from "next/link";
import { getPeople } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function Page() {
  const people = await getPeople();
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold">People <span className="text-dim font-normal">({people.length})</span></h1>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-dim border-b border-line bg-[#F7F3EC]">
            <tr><th className="px-3 py-2 text-left">Name</th><th className="px-3 py-2 text-left">Role</th>
              <th className="px-3 py-2 text-left">Company</th><th className="px-3 py-2 text-left">Email</th></tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.person} className="border-b border-line hover:bg-[#FAF7F1]">
                <td className="px-3 py-2 font-medium">{p.person}</td>
                <td className="px-3 py-2 text-dim">{p.role ?? "—"}</td>
                <td className="px-3 py-2">{p.company ? <Link className="text-accent hover:underline" href={`/companies/${encodeURIComponent(p.company)}`}>{p.company}</Link> : "—"}</td>
                <td className="px-3 py-2 text-dim">{p.email ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
