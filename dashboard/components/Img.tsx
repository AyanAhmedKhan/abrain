"use client";
import { useState } from "react";

// LinkedIn media is served through our caching proxy (/img). If it still fails
// (expired token + not cached, network, non-image), fall back to an initial so
// the UI never shows a broken-image icon.
const proxied = (u?: string | null) => (u ? `/img?u=${encodeURIComponent(u)}` : null);
const initial = (s?: string | null) => (s || "?").trim().slice(0, 1).toUpperCase() || "?";

export function Avatar({ src, name, size = 28 }: { src?: string | null; name?: string; size?: number }) {
  const [err, setErr] = useState(false);
  const url = proxied(src);
  const style = { width: size, height: size, fontSize: Math.max(11, size / 2.5) };
  if (url && !err) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="" style={style} onError={() => setErr(true)}
                className="rounded-full object-cover bg-raised shrink-0 ring-1 ring-black/5 dark:ring-white/10" />;
  }
  return <span style={style} className="rounded-full bg-gradient-to-br from-accenttint to-raised text-accentink font-semibold inline-flex items-center justify-center shrink-0 ring-1 ring-black/5 dark:ring-white/10">{initial(name)}</span>;
}

export function Logo({ src, name, size = 36 }: { src?: string | null; name?: string; size?: number }) {
  const [err, setErr] = useState(false);
  const url = proxied(src);
  const style = { width: size, height: size, fontSize: Math.max(12, size / 2.2) };
  if (url && !err) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="" style={style} onError={() => setErr(true)}
                className="rounded-lg object-contain bg-white shrink-0 ring-1 ring-black/5 dark:ring-white/10 p-0.5" />;
  }
  return <span style={style} className="rounded-lg bg-gradient-to-br from-accenttint to-raised text-accentink inline-flex items-center justify-center font-bold shrink-0 ring-1 ring-black/5 dark:ring-white/10">{initial(name)}</span>;
}
