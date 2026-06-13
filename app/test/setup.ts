// Vitest setup, loaded once before the test suite (see vitest.config.ts `setupFiles`).
// - jest-dom/vitest registers the DOM matchers (toBeInTheDocument, etc.) and their types.
// - cleanup() unmounts React trees between tests so they don't leak into one another.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
