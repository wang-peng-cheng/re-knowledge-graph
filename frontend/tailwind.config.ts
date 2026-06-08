import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        panel: "#08111f",
        accent: "#4cc9f0",
        accentSoft: "#143b51",
        success: "#7bf1a8",
        warning: "#ffd166",
        danger: "#ff6b81",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(76, 201, 240, 0.16), 0 18px 50px rgba(2, 8, 20, 0.55)",
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(76, 201, 240, 0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(76, 201, 240, 0.06) 1px, transparent 1px)",
      },
    },
  },
  plugins: [],
};

export default config;
