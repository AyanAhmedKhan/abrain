"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/", label: "Dashboard" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/deals", label: "Deals" },
  { href: "/people", label: "People" },
  { href: "/investors", label: "Investors" },
  { href: "/inbox", label: "Inbox" },
  { href: "/ask", label: "Ask" },
];

export default function Nav() {
  const path = usePathname();
  const isActive = (href: string) =>
    href === "/" ? path === "/" : path.startsWith(href);

  return (
    <nav className="flex gap-1 ml-1">
      {tabs.map((t) => {
        const on = isActive(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={on ? "page" : undefined}
            className={`px-3.5 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              on
                ? "bg-accenttint text-accentink shadow-sm ring-1 ring-accent/15"
                : "text-dim hover:bg-wash hover:text-ink"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
