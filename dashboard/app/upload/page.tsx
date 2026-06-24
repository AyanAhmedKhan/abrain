"use client";

import { useState } from "react";
import { ingestDeck, type IngestResult } from "@/lib/actions";
import { PageHeader } from "@/components/ui";

export default function Page() {
  const [url, setUrl] = useState("");
  const [res, setRes] = useState<IngestResult | null>(null);
  const [loading, setLoading] = useState(false);

  const go = async () => {
    const u = url.trim();
    if (!u || loading) return;
    setLoading(true); setRes(null);
    try { setRes(await ingestDeck(u)); setUrl(""); } finally { setLoading(false); }
  };

  return (
    <div className="space-y-5 max-w-2xl">
      <PageHeader title="Upload pitch decks" subtitle="Paste a Google Drive link (file, Slides, Docs, or folder)" />

      <div className="card p-4">
        <div className="flex gap-2">
          <input
            value={url} onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") go(); }}
            placeholder="https://drive.google.com/file/d/…  or  /drive/folders/…"
            className="flex-1 bg-transparent outline-none px-2 py-2 text-[15px]" autoFocus
          />
          <button onClick={go} disabled={loading || !url.trim()}
            className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-semibold disabled:opacity-40 hover:opacity-90 transition">
            {loading ? "Ingesting…" : "Ingest"}
          </button>
        </div>
        <p className="text-dim text-xs mt-2 px-2">
          The link must be shared <b>“anyone with the link”</b>. Each deck is downloaded, read
          by the multimodal pipeline (charts &amp; tables included), and linked to its company —
          you can ask about it and open the original. Processing takes ~1–2 min.
        </p>
      </div>

      {loading && <div className="card p-6 text-dim text-sm animate-pulse">Downloading &amp; queueing decks…</div>}

      {res && (
        <div className="space-y-3">
          {res.queued.length > 0 && (
            <section className="card p-5">
              <h2 className="section-title mb-2 text-emerald-600">Queued ({res.queued.length})</h2>
              <ul className="text-sm space-y-1">{res.queued.map((q, i) => <li key={i}>✓ {q.name}</li>)}</ul>
              <p className="text-dim text-xs mt-2">Processing now — they’ll appear on their company pages shortly.</p>
            </section>
          )}
          {res.skipped.length > 0 && (
            <section className="card p-5">
              <h2 className="section-title mb-2 text-dim">Skipped ({res.skipped.length})</h2>
              <ul className="text-sm space-y-1">{res.skipped.map((s, i) => <li key={i} className="text-dim">• {s.reason}</li>)}</ul>
            </section>
          )}
          {res.queued.length === 0 && res.skipped.length === 0 && <div className="card p-5 text-dim text-sm">Nothing ingested.</div>}
        </div>
      )}
    </div>
  );
}
