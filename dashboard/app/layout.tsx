import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dexter Capital · Company Brain",
  robots: { index: false, follow: false },
};

const tabs = [
  { href: "/", label: "Dashboard" },
  { href: "/deals", label: "Deals" },
  { href: "/people", label: "People" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="sticky top-0 z-10 bg-white/90 backdrop-blur border-b border-line">
          <div className="max-w-7xl mx-auto px-6 h-14 flex items-center gap-5">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <span className="w-7 h-7 rounded-lg bg-mint text-white grid place-items-center font-extrabold text-sm shadow-sm">D</span>
              Dexter Capital <span className="text-dim font-medium">· Company Brain</span>
            </Link>
            <nav className="flex gap-1 ml-2">
              {tabs.map((t) => (
                <Link key={t.href} href={t.href}
                  className="px-3 py-1.5 rounded-lg text-dim hover:bg-creamlite hover:text-mintdark font-medium transition-colors">
                  {t.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
