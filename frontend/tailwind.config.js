/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./stores/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // PIT semantic colors (PRD §12 quality + state)
        pit: {
          valid: "#10b981",       // green
          stale: "#f59e0b",       // amber
          inferred: "#a78bfa",    // purple
          failed: "#ef4444",      // red
          rejected: "#ef4444",
          degraded: "#f59e0b",
          partial: "#facc15",
          sourceFailed: "#dc2626",
          throttled: "#fb923c",
          // Z-score diverging
          zneg: "#2563eb",        // blue
          zpos: "#dc2626",        // red
          zmid: "#f3f4f6",        // gray-100
        },
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          900: "#312e81",
        },
        ink: {
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          500: "#64748b",
          700: "#334155",
          900: "#0f172a",
        },
      },
      fontFamily: {
        sans: ['"Inter"', '"Segoe UI"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', '"Fira Code"', "Menlo", "monospace"],
      },
      boxShadow: {
        drawer: "0 25px 50px -12px rgba(0,0,0,0.25)",
      },
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4,0,0.6,1) infinite",
      },
    },
  },
  plugins: [],
};
