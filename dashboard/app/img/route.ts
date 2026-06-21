import { NextRequest } from "next/server";
import crypto from "crypto";
import fs from "fs/promises";
import path from "path";

// Image proxy + on-disk cache for LinkedIn CDN media (photos / company logos).
// licdn URLs block cross-origin hot-linking (referrer check) and carry expiring
// tokens, so we fetch server-side ONCE and cache the bytes — images then render
// reliably and survive token expiry. SSRF-guarded to licdn hosts only.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CACHE = path.join(process.cwd(), ".media-cache");
const ALLOW = /(^|\.)licdn\.com$/;

export async function GET(req: NextRequest) {
  const u = req.nextUrl.searchParams.get("u");
  if (!u) return new Response("missing u", { status: 400 });
  let url: URL;
  try {
    url = new URL(u);
  } catch {
    return new Response("bad url", { status: 400 });
  }
  if (url.protocol !== "https:" || !ALLOW.test(url.hostname)) {
    return new Response("forbidden host", { status: 403 });
  }

  const key = crypto.createHash("sha1").update(u).digest("hex");
  const file = path.join(CACHE, key);
  const headers = (ct: string) => ({
    "Content-Type": ct,
    "Cache-Control": "public, max-age=31536000, immutable",
  });

  try {
    const buf = await fs.readFile(file);
    const ct = await fs.readFile(file + ".ct", "utf8").catch(() => "image/jpeg");
    return new Response(buf, { headers: headers(ct) });
  } catch {
    /* not cached yet → fetch below */
  }

  try {
    const r = await fetch(u, {
      headers: { "User-Agent": "Mozilla/5.0", Accept: "image/*", Referer: "" },
    });
    if (!r.ok) return new Response("upstream " + r.status, { status: 502 });
    const ct = r.headers.get("content-type") || "image/jpeg";
    if (!ct.startsWith("image/")) return new Response("not an image", { status: 502 });
    const ab = Buffer.from(await r.arrayBuffer());
    await fs.mkdir(CACHE, { recursive: true });
    await fs.writeFile(file, ab).catch(() => {});
    await fs.writeFile(file + ".ct", ct).catch(() => {});
    return new Response(ab, { headers: headers(ct) });
  } catch {
    return new Response("fetch error", { status: 502 });
  }
}
