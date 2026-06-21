import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import Nav from "@/components/Nav";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";

export const metadata: Metadata = {
  title: "Dexter Capital · Company Brain",
  robots: { index: false, follow: false },
};

// set the theme class before paint to avoid a flash of the wrong theme
const themeInit = `(function(){try{var t=localStorage.getItem('theme');var d=t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches;if(d)document.documentElement.classList.add('dark');}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Marcellus&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="sticky top-0 z-20 border-b border-line/70 bg-bg/70 backdrop-blur-xl">
          <div className="max-w-7xl mx-auto px-6 h-16 flex items-center gap-4">
            <Link href="/" className="flex items-center gap-2.5 shrink-0">
              <BrandMark size={32} />
              <span className="hidden sm:flex items-baseline gap-2">
                <span className="wordmark text-[1.15rem] font-bold text-accent leading-none">DEXTER</span>
                <span className="text-dim font-medium text-sm">Company Brain</span>
              </span>
            </Link>
            <Nav />
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-7 animate-fade-up">{children}</main>
      </body>
    </html>
  );
}
