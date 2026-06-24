// ESLint v9 flat config — lints the frontend app (TypeScript + React).
//
// Division of labor with Prettier: `eslint-config-prettier` (last entry) switches off every
// ESLint rule that overlaps with the formatter, so ESLint only judges *code quality* (unused
// vars, unsafe patterns, React hooks correctness) and Prettier owns *all* formatting. Run them
// as separate commands — they never fight.
//
// Scope: app/. Build output, generated React Router types, dependencies, and the model/ team's
// code are never linted.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import eslintConfigPrettier from "eslint-config-prettier";
import globals from "globals";

export default tseslint.config(
  { ignores: ["build/", ".react-router/", "node_modules/", "model/"] },

  // Base JS + TypeScript recommended rules (non-type-checked: fast, no tsconfig wiring).
  js.configs.recommended,
  ...tseslint.configs.recommended,

  // React-specific rules for the app source.
  {
    files: ["app/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      "react-hooks/rules-of-hooks": "error", // hooks must run unconditionally, top-level
      "react-hooks/exhaustive-deps": "warn", // missing effect deps — warn, not block
      // Treat a leading underscore as "intentionally unused" (params, locals, caught errors) —
      // the convention this codebase already uses (e.g. the `_dte` future-use param).
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },

  // MUST be last: disables ESLint rules that would conflict with Prettier's formatting.
  eslintConfigPrettier,
);
