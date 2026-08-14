/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Neutrals carry the entire interface. Hue is reserved for meaning.
        ink: {
          DEFAULT: "#15181d",
          2: "#3d4650",
          3: "#697585",
          4: "#98a3b0",
        },
        surface: {
          DEFAULT: "#ffffff",
          sunk: "#f4f6f8",
          page: "#eef1f4",
          rail: "#20242b",
        },
        line: {
          DEFAULT: "#dde2e8",
          strong: "#c3cbd4",
        },
        // Severity — the only palette the eye should scan for.
        material: { DEFAULT: "#c0392f", bg: "#fdecea", line: "#f0b5ae" },
        cosmetic: { DEFAULT: "#9a6208", bg: "#fdf3e2", line: "#eccf9a" },
        uncertain: { DEFAULT: "#5b4bab", bg: "#eeecfa", line: "#c3bcec" },
        clear: { DEFAULT: "#1d6f4e", bg: "#e8f4ee", line: "#a9d3bf" },
        focus: "#2563eb",
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto',
               'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'SF Mono', 'Menlo', 'Consolas',
               'Liberation Mono', 'DejaVu Sans Mono', 'monospace'],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.375rem" }],
      },
      borderRadius: { DEFAULT: "3px", md: "4px", lg: "6px" },
      spacing: { 4.5: "1.125rem", 13: "3.25rem" },
    },
  },
  plugins: [],
};
