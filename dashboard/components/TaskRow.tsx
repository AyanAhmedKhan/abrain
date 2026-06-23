"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import type { Task } from "@/lib/types";
import { completeTask } from "@/lib/actions";

export default function TaskRow({ t }: { t: Task }) {
  const [done, setDone] = useState(false);
  const [, start] = useTransition();
  if (done) return null;
  return (
    <li className="flex items-start gap-3 py-2 border-b border-line/70 last:border-0">
      <button
        onClick={() => { setDone(true); start(() => { completeTask(t.id); }); }}
        title="Mark done"
        className="mt-0.5 h-4 w-4 rounded border border-line hover:border-accent hover:bg-accenttint shrink-0 transition-colors"
      />
      <div className="min-w-0 flex-1">
        <div className="text-sm leading-snug">{t.description}</div>
        <div className="text-[11px] text-dim mt-0.5 flex flex-wrap gap-x-2">
          {t.company && <Link href={`/companies/${encodeURIComponent(t.company)}`} className="text-accent hover:underline">{t.company}</Link>}
          {t.owner && <span>@{t.owner}</span>}
          {t.due_date && <span className={t.overdue ? "text-rose-500 font-medium" : ""}>due {String(t.due_date).slice(0, 10)}</span>}
        </div>
      </div>
      {t.overdue && <span className="text-[10px] font-semibold text-rose-500 bg-rose-500/10 rounded px-1.5 py-0.5 shrink-0">OVERDUE</span>}
    </li>
  );
}
