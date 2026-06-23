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
