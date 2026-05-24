import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Neutrals
        bg: {
          0: "#0B0E13",
          1: "#11151C",
          2: "#171C25",
          3: "#1F2630",
        },
        border: {
          DEFAULT: "#2A3340",
        },
        // Text
        text: {
          primary: "#E6EAF2",
          secondary: "#9AA4B2",
          muted: "#5C6675",
        },
        // P&L
        profit: {
          DEFAULT: "#22C55E",
          dim: "#15803D",
          cb: "#2DD4BF",
        },
        loss: {
          DEFAULT: "#EF4444",
          dim: "#991B1B",
          cb: "#F59E0B",
        },
        flat: "#94A3B8",
        // Status
        accent: "#3B82F6",
        warn: "#F59E0B",
        danger: "#DC2626",
        info: "#06B6D4",
        // Chart
        candle: {
          up: "#26A69A",
          down: "#EF5350",
        },
        grid: "#1A2030",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
