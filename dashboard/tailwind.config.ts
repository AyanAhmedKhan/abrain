import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        mint: "#00A19B", mintdark: "#007E79", minttint: "#D7F0EE", mintglow: "#E9F8F6",
        cream: "#E4DDD3", creamlite: "#F4F0E9",
        ink: "#15221F", dim: "#6E756F", line: "#E7E0D5",
        panel: "#FFFFFF", bg: "#F4F0E9", accent: "#00A19B",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "-apple-system",
               "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(21,34,31,.04), 0 1px 3px rgba(21,34,31,.06)",
        cardhover: "0 6px 16px rgba(21,34,31,.08), 0 2px 5px rgba(21,34,31,.05)",
        soft: "0 10px 34px rgba(21,34,31,.07)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
      keyframes: {
        "fade-up": { "0%": { opacity: "0", transform: "translateY(8px)" },
                     "100%": { opacity: "1", transform: "translateY(0)" } },
      },
      animation: { "fade-up": "fade-up .45s cubic-bezier(.21,.6,.35,1) both" },
    },
  },
  plugins: [],
};
export default config;
