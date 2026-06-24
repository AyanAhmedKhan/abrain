"use client";

import { useState } from "react";
import { deckUrl } from "@/lib/actions";

// Opens the original deck PDF via a short-lived signed URL (fetched on click,
// never embedded in the page) — works for image decks too.
export function OpenDeck({ deckRef, sourceUrl }: { deckRef?: string | null; sourceUrl?: string | null }) {
  const [busy, setBusy] = useState(false);
  if (sourceUrl && !deckRef) {
    return <a href={sourceUrl} target="_blank" rel="noreferrer" className="text-accent hover:underline text-xs">open deck ↗</a>;
  }
  if (!deckRef) return null;
  const open = async () => {
    setBusy(true);
    try { const u = await deckUrl(deckRef); if (u) window.open(u, "_blank", "noopener"); }
    finally { setBusy(false); }
  };
  return (
    <button onClick={open} disabled={busy} className="text-accent hover:underline text-xs disabled:opacity-50">
      {busy ? "opening…" : "open deck ↗"}
    </button>
  );
}
