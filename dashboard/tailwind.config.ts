import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        mint: "#00A19B", mintdark: "#007E79", minttint: "#D7F0EE",
        cream: "#E4DDD3", creamlite: "#F4F0E9",
        ink: "#15221F", dim: "#6E756F", line: "#E7E0D5",
        panel: "#FFFFFF", bg: "#F4F0E9", accent: "#00A19B",
      },
      boxShadow: { card: "0 1px 2px rgba(21,34,31,.04), 0 1px 3px rgba(21,34,31,.07)" },
    },
  },
  plugins: [],
};
export default config;
