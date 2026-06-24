"use client";

import { useRef, useState } from "react";
import { ingestDeck, type IngestResult } from "@/lib/actions";
import { PageHeader } from "@/components/ui";

const empty: IngestResult = { queued: [], skipped: [] };
const merge = (a: IngestResult, b: IngestResult): IngestResult => ({
  queued: [...a.queued, ...b.queued], skipped: [...a.skipped, ...b.skipped],
});

export default function Page() {
  const [url, setUrl] = useState("");
  const [res, setRes] = useState<IngestResult | null>(null);
  const [busy, setBusy] = useState<"" | "link" | "file">("");
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const goLink = async () => {
    const u = url.trim();
    if (!u || busy) return;
    setBusy("link"); setRes(null);
    try { setRes(await ingestDeck(u)); setUrl(""); } finally { setBusy(""); }
  };

  const uploadFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length || busy) return;
    setBusy("file"); setRes(null);
    try {
      const fd = new FormData();
      for (const f of list) fd.append("files", f);
      const r = await fetch("/api/upload-deck", { method: "POST", body: fd });
      const j = (await r.json().catch(() => empty)) as IngestResult;
      setRes(merge(empty, j));
    } catch {
      setRes({ queued: [], skipped: [{ url: "", reason: "upload failed — is the ingest service up?" }] });
    } finally {
      setBusy("");
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="space-y-5 max-w-2xl">
      <PageHeader title="Upload pitch decks" subtitle="From your computer or a Google Drive link — read by the multimodal pipeline (charts & tables included)" />

      {/* ── From your computer ─────────────────────────────── */}
      <div className="card p-4">
        <h2 className="section-title mb-2">From your computer</h2>
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); uploadFiles(e.dataTransfer.files); }}
          onClick={() => fileInput.current?.click()}
          className={`rounded-xl border-2 border-dashed px-4 py-10 text-center cursor-pointer transition
            ${drag ? "border-accent bg-accenttint/40" : "border-line hover:border-accent/40"}`}
        >
          <input ref={fileInput} type="file" accept="application/pdf,.pdf" multiple hidden
            onChange={(e) => e.target.files && uploadFiles(e.target.files)} />
          {busy === "file"
            ? <p className="text-dim text-sm animate-pulse">Uploading &amp; queueing…</p>
            : <>
                <p className="text-[15px] font-medium">Drop PDF decks here, or click to choose</p>
                <p className="text-dim text-xs mt-1">Multiple files OK · PDF only · up to 40&nbsp;MB each</p>
              </>}
        </div>
      </div>

      {/* ── From Google Drive ──────────────────────────────── */}
      <div className="card p-4">
        <h2 className="section-title mb-2">From a Google Drive link</h2>
        <div className="flex gap-2">
          <input
            value={url} onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") goLink(); }}
            placeholder="https://drive.google.com/file/d/…  or  /drive/folders/…"
            className="flex-1 bg-transparent outline-none px-2 py-2 text-[15px]"
          />
          <button onClick={goLink} disabled={!!busy || !url.trim()}
            className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-semibold disabled:opacity-40 hover:opacity-90 transition">
            {busy === "link" ? "Ingesting…" : "Ingest"}
          </button>
        </div>
        <p className="text-dim text-xs mt-2 px-1">
          The link must be shared <b>“anyone with the link”</b> (file, Slides, Docs, or a folder).
        </p>
      </div>

      <p className="text-dim text-xs px-1">
        Each deck is read by the multimodal pipeline (charts &amp; tables included), linked to its
        company, and made searchable &amp; citable. Processing takes ~1–2&nbsp;min.
      </p>

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
              <ul className="text-sm space-y-1">{res.skipped.map((s, i) => <li key={i} className="text-dim">• {s.url ? `${s.url}: ` : ""}{s.reason}</li>)}</ul>
            </section>
          )}
          {res.queued.length === 0 && res.skipped.length === 0 && <div className="card p-5 text-dim text-sm">Nothing ingested.</div>}
        </div>
      )}
    </div>
  );
}
