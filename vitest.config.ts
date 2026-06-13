import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

// Separate from vite.config.ts on purpose: that config loads the @react-router/dev plugin, which
// isn't meant to run under the test runner. Here we only need path-alias resolution (~/*) plus a
// jsdom DOM environment for component rendering.
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: "jsdom",
    setupFiles: ["./app/test/setup.ts"],
    include: ["app/**/*.{test,spec}.{ts,tsx}"],
  },
});
