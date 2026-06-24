import { NextRequest, NextResponse } from "next/server";

// Direct file upload from the user's computer. The browser POSTs multipart
// form-data here; we stream each PDF's bytes to the Python ingest service on
// localhost (the service key never leaves the server). Same pipeline + idempotency
// as Drive links. Runs on the Node runtime (self-hosted, no serverless body cap).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ASK_URL = process.env.ASK_URL || "http://127.0.0.1:8090";
const MAX = (Number(process.env.MAX_UPLOAD_MB) || 40) * 1024 * 1024;

type Item = { name?: string; id?: string; url?: string; reason?: string };

export async function POST(req: NextRequest) {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ queued: [], skipped: [{ reason: "bad upload" }] }, { status: 400 });
  }
  const files = form.getAll("files").filter((f): f is File => f instanceof File);
  const queued: Item[] = [];
  const skipped: Item[] = [];

  for (const f of files) {
    const isPdf = f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) { skipped.push({ url: f.name, reason: "not a PDF" }); continue; }
    if (f.size === 0) { skipped.push({ url: f.name, reason: "empty file" }); continue; }
    if (f.size > MAX) {
      skipped.push({ url: f.name, reason: `too large (${Math.round(f.size / 1e6)}MB > ${Math.round(MAX / 1e6)}MB)` });
      continue;
    }
    try {
      const buf = new Uint8Array(await f.arrayBuffer());
      const r = await fetch(`${ASK_URL}/ingest-file?filename=${encodeURIComponent(f.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        body: buf,
        cache: "no-store",
        signal: AbortSignal.timeout(180_000),
      });
      const j = await r.json().catch(() => ({}));
      queued.push(...(j.queued ?? []));
      skipped.push(...(j.skipped ?? (r.ok ? [] : [{ url: f.name, reason: "ingest failed" }])));
    } catch (e) {
      console.error("[upload-deck]", e);
      skipped.push({ url: f.name, reason: "ingest service unavailable" });
    }
  }
  return NextResponse.json({ queued, skipped });
}
