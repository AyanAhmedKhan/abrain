"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import type { PipelineDeal } from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/types";
import { moveDeal } from "@/lib/actions";

const inr = (v: string | null) => {
  if (v == null || v === "") return null;
  const n = parseFloat(v);
  return Number.isNaN(n) ? null : `₹${n % 1 === 0 ? n : n.toFixed(1)} Cr`;
};

function Card({ d, onDragStart }: { d: PipelineDeal; onDragStart: (id: string) => void }) {
  return (
    <div
      draggable
      onDragStart={(e) => { e.dataTransfer.setData("text/plain", d.entity_id); onDragStart(d.entity_id); }}
      className="rounded-lg border border-line bg-panel p-2.5 shadow-sm cursor-grab active:cursor-grabbing hover:border-accent/40 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <Link href={`/companies/${encodeURIComponent(d.company)}`} className="font-medium text-sm hover:text-accent hover:underline leading-tight">
          {d.company}
        </Link>
        {inr(d.ask_inr_cr) && <span className="text-[11px] font-semibold text-accentink bg-accenttint rounded px-1.5 py-0.5 shrink-0 tabular-nums">{inr(d.ask_inr_cr)}</span>}
      </div>
      <div className="text-dim text-[11px] mt-1 truncate">{[d.sector, d.round_type].filter(Boolean).join(" · ") || "—"}</div>
      <div className="flex items-center justify-between mt-1.5 text-[11px] text-dim">
        <span>{d.owner ? `@${d.owner}` : <span className="opacity-50">unassigned</span>}</span>
        <span className="tabular-nums">{d.last_interaction ? String(d.last_interaction).slice(0, 10) : ""}</span>
      </div>
    </div>
  );
}

export default function Board({ deals }: { deals: PipelineDeal[] }) {
  const [items, setItems] = useState(deals);
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [, start] = useTransition();

  const drop = (stage: string) => {
    setOver(null);
    const id = drag;
    if (!id) return;
    setItems((cur) => cur.map((d) => (d.entity_id === id ? { ...d, pipeline_stage: stage } : d)));  // optimistic
    start(() => { moveDeal(id, stage); });
    setDrag(null);
  };

  return (
    <div className="flex gap-3 overflow-x-auto pb-3">
      {PIPELINE_STAGES.map((stage) => {
        const col = items.filter((d) => d.pipeline_stage === stage);
        const sum = col.reduce((s, d) => s + (parseFloat(d.ask_inr_cr || "0") || 0), 0);
        return (
          <div
            key={stage}
            onDragOver={(e) => { e.preventDefault(); setOver(stage); }}
            onDragLeave={() => setOver((o) => (o === stage ? null : o))}
            onDrop={() => drop(stage)}
            className={`shrink-0 w-60 rounded-xl border p-2 transition-colors ${over === stage ? "border-accent bg-accenttint/40" : "border-line bg-wash/50"}`}
          >
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-xs font-semibold uppercase tracking-wide">{stage}</span>
              <span className="text-[11px] text-dim tabular-nums">{col.length}{sum ? ` · ₹${Math.round(sum)}Cr` : ""}</span>
            </div>
            <div className="space-y-2 min-h-[60px]">
              {col.map((d) => <Card key={d.entity_id} d={d} onDragStart={setDrag} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
