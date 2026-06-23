// Dependency-free inline SVG line+area chart (server component — pure render).
export function MiniChart({ points }: { points: { label: string; value: number }[] }) {
  if (points.length < 2) return null;
  const W = 280, H = 84, P = 10;
  const ys = points.map((p) => p.value);
  const minY = Math.min(...ys, 0), maxY = Math.max(...ys);
  const sx = (i: number) => P + (W - 2 * P) * (i / (points.length - 1));
  const sy = (v: number) => H - P - (H - 2 * P) * ((v - minY) / ((maxY - minY) || 1));
  const line = points.map((p, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
  const area = `${line} L${sx(points.length - 1).toFixed(1)},${H - P} L${sx(0).toFixed(1)},${H - P} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20 text-accent" preserveAspectRatio="none">
      <path d={area} fill="currentColor" opacity="0.10" />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {points.map((p, i) => <circle key={i} cx={sx(i)} cy={sy(p.value)} r="2.5" fill="currentColor" />)}
    </svg>
  );
}

const crore = (n: number) => `₹${n % 1 === 0 ? n : n.toFixed(1)} Cr`;

// One metric's trend: sparkline + latest value + growth from first→last point.
export function Metric({ title, points }: { title: string; points: { label: string; value: number }[] }) {
  if (!points.length) return null;
  const last = points[points.length - 1], first = points[0];
  const growth = points.length >= 2 && first.value
    ? Math.round(((last.value - first.value) / Math.abs(first.value)) * 100) : null;
  return (
    <div className="rounded-xl border border-line p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-dim text-[11px] uppercase tracking-wider font-semibold">{title}</span>
        {growth !== null && (
          <span className={`text-xs font-semibold tabular-nums ${growth >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
            {growth >= 0 ? "▲" : "▼"} {Math.abs(growth)}%
          </span>
        )}
      </div>
      <div className="text-xl font-bold tabular-nums mt-0.5">{crore(last.value)}<span className="text-dim text-xs font-normal ml-1">{last.label}</span></div>
      <MiniChart points={points} />
    </div>
  );
}
