"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import type { PipelineDeal } from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/types";
import { moveDeal, assignOwner } from "@/lib/actions";

function OwnerCell({ d, owners }: { d: PipelineDeal; owners: string[] }) {
  const [val, setVal] = useState(d.owner ?? "");
  const [edit, setEdit] = useState(false);
  const [, start] = useTransition();
  const save = () => {
    setEdit(false);
    const v = val.trim();
    if (v !== (d.owner ?? "")) start(() => { assignOwner(d.entity_id, v); });
  };
  if (edit) {
    return (
      <input
        autoFocus list="owner-suggestions" value={val}
        onChange={(e) => setVal(e.target.value)} onBlur={save}
        onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") { setVal(d.owner ?? ""); setEdit(false); } }}
        placeholder="owner…"
        className="w-24 bg-transparent border-b border-accent text-[11px] outline-none"
        // don't let typing/drag interfere with the card
        draggable={false} onMouseDown={(e) => e.stopPropagation()}
      />
    );
  }
  return (
    <button onClick={() => setEdit(true)} className="text-[11px] text-dim hover:text-accent" title="Assign owner">
      {val ? `@${val}` : <span className="opacity-50">+ owner</span>}
    </button>
  );
}

const inr = (v: string | null) => {
  if (v == null || v === "") return null;
  const n = parseFloat(v);
  return Number.isNaN(n) ? null : `₹${n % 1 === 0 ? n : n.toFixed(1)} Cr`;
};

function Card({ d, owners, onDragStart }: { d: PipelineDeal; owners: string[]; onDragStart: (id: string) => void }) {
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
        <OwnerCell d={d} owners={owners} />
        <span className="tabular-nums">{d.last_interaction ? String(d.last_interaction).slice(0, 10) : ""}</span>
      </div>
    </div>
  );
}

export default function Board({ deals, owners = [] }: { deals: PipelineDeal[]; owners?: string[] }) {
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
      <datalist id="owner-suggestions">{owners.map((o) => <option key={o} value={o} />)}</datalist>
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
              {col.map((d) => <Card key={d.entity_id} d={d} owners={owners} onDragStart={setDrag} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
