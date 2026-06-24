"use server";

import { revalidatePath } from "next/cache";
import { setDealStage, setDealOwner, markTaskDone } from "./data";

export async function moveDeal(entityId: string, stage: string): Promise<boolean> {
  const ok = await setDealStage(entityId, stage);
  if (ok) revalidatePath("/pipeline");
  return ok;
}

export async function assignOwner(entityId: string, owner: string): Promise<boolean> {
  const ok = await setDealOwner(entityId, owner);
  if (ok) revalidatePath("/pipeline");
  return ok;
}

export async function completeTask(id: string): Promise<boolean> {
  const ok = await markTaskDone(id);
  if (ok) revalidatePath("/inbox");
  return ok;
}

const ASK_URL = process.env.ASK_URL || "http://127.0.0.1:8090";

export type IngestResult = { queued: { name: string; id: string }[]; skipped: { url: string; reason: string }[] };

export async function ingestDeck(url: string): Promise<IngestResult> {
  const fail = { queued: [], skipped: [{ url, reason: "ingest service unavailable" }] };
  if (!url.trim()) return { queued: [], skipped: [] };
  try {
    const r = await fetch(`${ASK_URL}/ingest-drive`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url.trim() }), cache: "no-store",
      signal: AbortSignal.timeout(180_000),
    });
    if (!r.ok) return fail;
    return await r.json();
  } catch (e) { console.error("[ingestDeck]", e); return fail; }
}

// short-lived signed URL to open an original deck PDF from bronze
export async function deckUrl(ref: string): Promise<string | null> {
  try {
    const r = await fetch(`${ASK_URL}/deck?ref=${encodeURIComponent(ref)}`, { cache: "no-store", signal: AbortSignal.timeout(20_000) });
    if (!r.ok) return null;
    return (await r.json()).url ?? null;
  } catch { return null; }
}

export type AskResult = { answer: string; sources: { company: string | null; title: string | null; deck?: boolean; page?: number | null; ref?: string | null; dist: number }[] };

export async function askBrain(question: string): Promise<AskResult> {
  const url = process.env.ASK_URL || "http://127.0.0.1:8090";
  const fail = { answer: "The brain is unavailable right now — try again in a moment.", sources: [] };
  if (!question.trim()) return { answer: "", sources: [] };
  try {
    const r = await fetch(`${url}/ask`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }), cache: "no-store",
      signal: AbortSignal.timeout(120_000),
    });
    if (!r.ok) return fail;
    const j = await r.json();
    return { answer: j.answer ?? fail.answer, sources: j.sources ?? [] };
  } catch (e) {
    console.error("[askBrain]", e);
    return fail;
  }
}
