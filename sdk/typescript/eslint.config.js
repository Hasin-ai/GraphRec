// The SDK's lint gate.
//
// The same reasoning as `frontend/eslint.config.js`: type-aware rules rather
// than syntactic ones, because `tsc -b` already runs in the same job and what
// it cannot catch is the well-typed mistake. In a client library the sharpest
// member of that class is the floating promise — a `void`-returning call that
// was actually a request, whose rejection reaches nobody and whose retry never
// happens.
//
// No React plugins and `globals.node`: this package refuses to run in a
// browser, and a config that offered browser globals would be offering a
// runtime the README spends its first section explaining is unsafe.
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist'] },
  {
    files: ['**/*.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.node,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', ignoreRestSiblings: true },
      ],
    },
  },
  {
    // Tests assert on values the compiler has already narrowed, and the fixture
    // fetch has to shape itself into `typeof globalThis.fetch` from a plainer
    // function. Both read as unsafe to a rule that cannot see the assertion.
    files: ['test/**/*.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/require-await': 'off',
    },
  },
);
