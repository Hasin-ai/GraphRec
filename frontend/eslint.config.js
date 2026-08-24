// The console's lint gate.
//
// `.github/workflows/ci.yml` has run `npm run lint` in the `frontend` job since
// Phase 12. There was no `lint` script and no ESLint, so the job failed on
// "Missing script: lint" every time it ran — which is the reason this file
// exists now rather than a preference for one rule set over another.
//
// Type-aware linting (`recommendedTypeChecked`) rather than the syntactic
// rules. `tsc --noEmit` already runs in the same job, so a syntax-only rule set
// would mostly repeat it. What it cannot repeat is the class of bug that is
// well-typed and wrong: a floating promise, an `await` on a non-thenable, a
// template literal interpolating an object. This codebase is React Query and
// fetch all the way down, and an unhandled promise there is a mutation whose
// failure never reaches the error boundary.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // Generated, vendored or built. `src/api/schema.ts` is written by
    // `openapi-typescript` from `openapi.json`; linting it would be linting the
    // OpenAPI document through a code generator.
    ignores: ["dist", "coverage", "src/api/schema.ts", "src/generated/**"],
  },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // Fast Refresh only replaces a module whose exports are all components.
      // A file exporting a component *and* a constant silently falls back to a
      // full reload, which is a development papercut rather than a defect —
      // hence a warning, and `allowConstantExport` for the common case.
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],

      // `throw redirect(...)` is how a react-router loader short-circuits, and
      // `redirect()` returns a `Response`. The rule is right in general and
      // wrong here: thirteen of these are in `src/guards/index.ts`, which is
      // the file implementing the five authorization gates, and rewriting them
      // to `return` would change what the router does. Allowed by type rather
      // than by disable comment, so a genuine `throw "oops"` is still an error.
      "@typescript-eslint/only-throw-error": [
        "error",
        { allow: [{ from: "lib", name: "Response" }] },
      ],

      // The rule this file is really for. A `void` prefix is an explicit "I
      // know this is async and I am not waiting", which is legitimate in an
      // effect; an unmarked one is a lost rejection.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": [
        "error",
        { checksVoidReturn: { attributes: false } },
      ],

      // `_` prefix means deliberate. Destructuring rest siblings are how a
      // field is dropped from an object, and flagging those makes the idiom
      // unusable.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
    },
  },
  {
    // Tests assert on values the compiler has already narrowed, and a test's
    // job is to be blunt about it. `expect(x as Foo)` is not a type-safety
    // problem in a file whose purpose is to check what `x` is.
    files: ["**/*.test.{ts,tsx}", "src/test/**"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-return": "off",
      // A `fetch` mock has to return a promise whether or not its body awaits
      // anything. `async () => json(200, ...)` is the shortest correct spelling
      // and this rule wants the longer wrong-looking one.
      "@typescript-eslint/require-await": "off",
    },
  },
);
