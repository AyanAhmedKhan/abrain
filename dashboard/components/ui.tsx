import Link from "next/link";

export function Badge({ v }: { v: string | null }) {
  if (!v) return <span className="text-dim">—</span>;
  const k = v.toLowerCase();
  const c =
    k === "high" ? "bg-minttint text-mintdark"
    : k === "mid" ? "bg-amber-100 text-amber-700"
    : k === "low" ? "bg-rose-100 text-rose-700"
    : "bg-cream text-ink/70";
  return <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${c}`}>{v}</span>;
}

export function Pill({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return <span className="px-2 py-0.5 rounded-full text-xs bg-minttint text-mintdark font-medium">{children}</span>;
}

export function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-dim text-xs uppercase tracking-wide font-semibold">{label}</div>
      <div className="text-2xl font-bold mt-1 tabular-nums">{value}</div>
    </div>
  );
}

export function CompanyLink({ name }: { name: string }) {
  return (
    <Link href={`/companies/${encodeURIComponent(name)}`} className="text-accent hover:underline font-medium">
      {name}
    </Link>
  );
}
