import type { Config } from "tailwindcss";
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // semantic tokens — values come from CSS vars and flip in dark mode
        bg: "rgb(var(--bg) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        raised: "rgb(var(--raised) / <alpha-value>)",
        wash: "rgb(var(--wash) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        dim: "rgb(var(--dim) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        accentd: "rgb(var(--accentd) / <alpha-value>)",
        accenttint: "rgb(var(--accent-tint) / <alpha-value>)",
        accentink: "rgb(var(--accent-ink) / <alpha-value>)",
        // fixed brand-blue gradient (the Dexter globe), constant across themes
        brand1: "#46B4EA",
        brand2: "#1565A8",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "Times New Roman", "serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow) / .05), 0 1px 3px rgb(var(--shadow) / .07)",
        soft: "0 10px 34px rgb(var(--shadow) / .08)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
      keyframes: {
        "fade-up": { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
      animation: { "fade-up": "fade-up .45s cubic-bezier(.21,.6,.35,1) both" },
    },
  },
  plugins: [],
};
export default config;
