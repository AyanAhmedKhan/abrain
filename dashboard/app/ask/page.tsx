"use client";

import { useState } from "react";
import Link from "next/link";
import { askBrain, type AskResult } from "@/lib/actions";
import { PageHeader } from "@/components/ui";

const SAMPLES = [
  "Which fintech companies are raising the most?",
  "Summarize everything on Park+",
  "Which DeepTech deals are at Series A?",
  "Who are the highest-revenue companies and their stage?",
];

export default function Page() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<AskResult | null>(null);
  const [loading, setLoading] = useState(false);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || loading) return;
    setQ(text); setLoading(true); setRes(null);
    try { setRes(await askBrain(text)); } finally { setLoading(false); }
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <PageHeader title="Ask the brain" subtitle="Natural-language answers over every deal note — grounded & cited" />

      <div className="card p-4">
        <div className="flex gap-2">
          <input
            value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") ask(q); }}
            placeholder="Ask anything about the deal flow…"
            className="flex-1 bg-transparent outline-none px-2 py-2 text-[15px]"
            autoFocus
          />
          <button
            onClick={() => ask(q)} disabled={loading || !q.trim()}
            className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-semibold disabled:opacity-40 hover:opacity-90 transition"
          >
            {loading ? "Thinking…" : "Ask"}
          </button>
        </div>
      </div>

      {!res && !loading && (
        <div className="flex flex-wrap gap-2">
          {SAMPLES.map((s) => (
            <button key={s} onClick={() => ask(s)}
              className="text-xs text-dim border border-line rounded-full px-3 py-1.5 hover:border-accent/40 hover:text-ink transition">
              {s}
            </button>
          ))}
        </div>
      )}

      {loading && <div className="card p-6 text-dim text-sm animate-pulse">Searching the brain & composing a cited answer…</div>}

      {res && (
        <div className="space-y-4">
          <section className="card p-5">
            <p className="text-[15px] leading-relaxed whitespace-pre-wrap">{res.answer}</p>
          </section>
          {res.sources.length > 0 && (
            <section className="card p-5">
              <h2 className="section-title mb-3">Sources</h2>
              <ul className="space-y-1.5 text-sm">
                {res.sources.map((s, i) => (
                  <li key={i} className="flex items-center justify-between gap-3">
                    {s.company
                      ? <Link href={`/companies/${encodeURIComponent(s.company)}`} className="text-accent hover:underline">{s.company}</Link>
                      : <span className="text-dim">—</span>}
                    <span className="text-dim text-xs truncate max-w-[60%]" title={s.title ?? ""}>{s.title}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
