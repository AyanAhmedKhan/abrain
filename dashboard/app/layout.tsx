import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "Dexter Capital · Company Brain",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="sticky top-0 z-20 border-b border-line/70 bg-bg/70 backdrop-blur-xl">
          <div className="max-w-7xl mx-auto px-6 h-16 flex items-center gap-4">
            <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight shrink-0">
              <span className="w-8 h-8 rounded-xl bg-gradient-to-br from-mint to-mintdark text-white grid place-items-center font-extrabold text-sm shadow-sm ring-1 ring-black/5">
                D
              </span>
              <span className="hidden sm:flex items-baseline gap-1.5">
                Dexter Capital
                <span className="text-dim font-medium text-sm">Company Brain</span>
              </span>
            </Link>
            <Nav />
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-7 animate-fade-up">{children}</main>
      </body>
    </html>
  );
}
