import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  plugins: [tailwindcss(), reactRouter(), tsconfigPaths()],
  build: {
    outDir: "build" // keeps your folder named 'build'
  },
  // Pin the dev server to :5173. strictPort makes Vite fail loudly if the port is taken instead
  // of silently drifting to :5174 — which would otherwise break API calls, since the backend's
  // CORS only allows http://localhost:5173 (see backend/main.py).
  server: {
    port: 5173,
    strictPort: true,
  },
});
