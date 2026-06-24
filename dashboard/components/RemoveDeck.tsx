"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { removeDeck } from "@/lib/actions";

// Destructive: removes this deck and everything extracted from it (shared
// company/people entities are preserved). Two-click confirm guards the action.
export function RemoveDeck({ envelopeId, company, title }: { envelopeId: string; company?: string; title?: string | null }) {
  const [armed, setArmed] = useState(false);
  const [pending, start] = useTransition();
  const router = useRouter();

  const remove = () =>
    start(async () => {
      const r = await removeDeck(envelopeId, company);
      setArmed(false);
      if (r.removed) router.refresh();
      else alert(`Couldn’t remove deck: ${r.reason ?? "unknown error"}`);
    });

  if (pending) return <span className="text-dim text-xs">removing…</span>;
  if (!armed)
    return (
      <button onClick={() => setArmed(true)}
        className="text-dim hover:text-rose-600 text-xs transition" title={`Remove ${title ?? "deck"}`}>
        remove
      </button>
    );
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <span className="text-rose-600">delete?</span>
      <button onClick={remove} className="text-rose-600 font-semibold hover:underline">yes</button>
      <button onClick={() => setArmed(false)} className="text-dim hover:underline">no</button>
    </span>
  );
}
