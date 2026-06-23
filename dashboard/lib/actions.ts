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

export type AskResult = { answer: string; sources: { company: string | null; title: string | null; dist: number }[] };

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
