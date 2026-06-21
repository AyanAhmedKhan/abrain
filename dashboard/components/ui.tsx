import Link from "next/link";

export function Badge({ v }: { v: string | null }) {
  if (!v) return <span className="text-dim">—</span>;
  const k = v.toLowerCase();
  const c =
    k === "high" ? "bg-accenttint text-accentink ring-accent/20"
    : k === "mid" ? "bg-amber-100 text-amber-700 ring-amber-500/20 dark:bg-amber-400/15 dark:text-amber-300 dark:ring-amber-400/20"
    : k === "low" ? "bg-rose-100 text-rose-700 ring-rose-500/20 dark:bg-rose-400/15 dark:text-rose-300 dark:ring-rose-400/20"
    : "bg-line/50 text-dim ring-line";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ring-1 ring-inset ${c}`}>
      {v}
    </span>
  );
}

export function Pill({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs bg-accenttint text-accentink font-medium ring-1 ring-inset ring-accent/15">
      {children}
    </span>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-raised text-dim ring-1 ring-inset ring-line">
      {children}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="card card-hover px-4 py-3.5">
      <div className="text-dim text-[11px] uppercase tracking-wider font-semibold">{label}</div>
      <div className="text-[1.7rem] leading-none font-bold mt-2 tabular-nums tracking-tight">{value}</div>
      {hint != null && <div className="text-dim text-xs mt-1.5">{hint}</div>}
    </div>
  );
}

export function PageHeader({ title, count, subtitle, children }: {
  title: string; count?: number | string; subtitle?: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {title}
          {count != null && <span className="text-dim font-normal"> ({count})</span>}
        </h1>
        {subtitle && <p className="text-dim text-sm mt-1">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function SectionCard({ title, aside, children }: {
  title: string; aside?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="section-title">{title}</h2>
        {aside && <span className="text-dim text-xs">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

export function CompanyLink({ name }: { name: string }) {
  return (
    <Link href={`/companies/${encodeURIComponent(name)}`} className="text-accent hover:underline font-medium">
      {name}
    </Link>
  );
}
