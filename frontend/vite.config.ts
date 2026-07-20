import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only: proxy the audit API to the backend so `npm run dev` talks same-origin
// (no CORS dance). Unused by the docker build (nginx serves the static dist).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
